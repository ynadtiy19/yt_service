import os
import re
import base64
import asyncio
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException, Query
import yt_dlp

app = FastAPI(title="Persistent YT-DLP Internal Service")

# 限制全局并发，保障内存稳定
executor = ThreadPoolExecutor(max_workers=2)

# ==========================================
# 🌟 1. 自动解析环境变量中的 YOUTUBE_COOKIES_BASE64
# ==========================================
COOKIE_FILE_PATH = None
cookie_b64 = os.environ.get("YOUTUBE_COOKIES_BASE64")

if cookie_b64 and cookie_b64.strip():
    try:
        sanitized_b64 = cookie_b64.replace("\r", "").replace("\n", "").strip()
        decoded_bytes = base64.b64decode(sanitized_b64)
        
        COOKIE_FILE_PATH = "/tmp/yt_cookies.txt"
        with open(COOKIE_FILE_PATH, "wb") as f:
            f.write(decoded_bytes)
        print("✅ [Cookie Loader] 成功装载 YouTube Cookie 凭据！")
    except Exception as e:
        print(f"⚠️ [Cookie Loader] Cookie 解密失败: {e}")
        COOKIE_FILE_PATH = None
else:
    print("ℹ️ [Cookie Loader] 未提供 Cookie，将以免登录模式出流")


def _format_duration(seconds: int) -> str:
    if not seconds or seconds <= 0:
        return "00:00"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ==========================================
# 🌟 2. 核心作者头像嗅探函数 (支持 800x800 超清头像)
# ==========================================
def extract_channel_avatar(info: dict) -> str:
    for key in ['uploader_avatar', 'channel_avatar', 'avatar']:
        val = info.get(key)
        if val and isinstance(val, str) and ('ggpht.com' in val or 'googleusercontent.com' in val):
            return val

    for t in info.get('channel_thumbnails') or []:
        if isinstance(t, dict) and t.get('url'):
            return t['url']

    for t in info.get('thumbnails') or []:
        if isinstance(t, dict):
            url = t.get('url', '')
            if 'yt3.ggpht.com' in url or 'yt3.googleusercontent.com' in url:
                return url

    channel_url = info.get('channel_url') or info.get('uploader_url')
    if not channel_url:
        uploader_id = info.get('uploader_id')
        if uploader_id and uploader_id.startswith('@'):
            channel_url = f"https://www.youtube.com/{uploader_id}"
        elif info.get('channel_id'):
            channel_url = f"https://www.youtube.com/channel/{info.get('channel_id')}"

    if channel_url:
        try:
            req = urllib.request.Request(
                channel_url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept-Language': 'en-US,en;q=0.9',
                }
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                head_chunk = resp.read(65536).decode('utf-8', errors='ignore')
                og_match = re.search(r'<meta\s+(?:property|name)=["\']og:image["\']\s+content=["\']([^"\']+)["\']', head_chunk, re.IGNORECASE)
                if og_match:
                    return og_match.group(1)
                yt3_match = re.search(r'(https://yt3\.(?:ggpht|googleusercontent)\.com/[^\s"\'<]+)', head_chunk)
                if yt3_match:
                    return yt3_match.group(1)
        except Exception as e:
            print(f"⚠️ [Avatar Scraper] 提取头像异常: {e}")

    return ""


# ==========================================
# 🌟 3. 详细提取 Worker
# ==========================================
def get_original_ydl_opts(use_cookie: bool = True):
    opts = {
        'skip_download': True,
        'extract_flat': False,
        'noplaylist': True,
        'no_warnings': True,
        'socket_timeout': 15,
        'extractor_args': {
            'youtube': {
                'player_client': ['default', '-tv_downgraded', 'web_embedded']
            }
        }
    }
    if use_cookie and COOKIE_FILE_PATH:
        opts['cookiefile'] = COOKIE_FILE_PATH
    return opts


def _extract_worker(url: str):
    info = None
    try:
        with yt_dlp.YoutubeDL(get_original_ydl_opts(use_cookie=True)) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        print(f"⚠️ [通道 A 异常]: {e}，尝试免 Cookie 纯净重试...")
        with yt_dlp.YoutubeDL(get_original_ydl_opts(use_cookie=False)) as ydl:
            info = ydl.extract_info(url, download=False)

    if not info:
        return None

    avatar_url = extract_channel_avatar(info)
    info['author_avatar'] = avatar_url
    info['uploader_avatar'] = avatar_url
    return info


# ==========================================
# 🌟 4. 高速扁平搜索与热门 Worker（extract_flat = 0.3秒直出）
# ==========================================
def _flat_search_worker(query: str, limit: int = 20):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': 'in_playlist',
        'noplaylist': False,
        'socket_timeout': 8,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        res = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        entries = res.get('entries') or []
        results = []
        for item in entries:
            if not item:
                continue
            video_id = item.get('id') or item.get('url')
            if not video_id:
                continue
            duration = int(item.get('duration') or 0)
            view_count = item.get('view_count') or 0
            results.append({
                'video_id': video_id,
                'title': item.get('title') or '',
                'author': item.get('uploader') or item.get('channel') or '',
                'author_id': item.get('uploader_id') or item.get('channel_id') or '',
                'author_verified': True,
                'author_avatar': '',
                'duration': _format_duration(duration),
                'length_seconds': duration,
                'is_live': item.get('is_live') or False,
                'views': f"{view_count} views",
                'thumbnail': f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                'published_text': str(item.get('upload_date') or ''),
                'description': item.get('description') or '',
            })
        return results


def _flat_trending_worker():
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': 'in_playlist',
        'socket_timeout': 8,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        res = ydl.extract_info("https://www.youtube.com/feed/trending", download=False)
        entries = res.get('entries') or []
        results = []
        for item in entries:
            if not item:
                continue
            video_id = item.get('id') or item.get('url')
            if not video_id:
                continue
            duration = int(item.get('duration') or 0)
            view_count = item.get('view_count') or 0
            results.append({
                'video_id': video_id,
                'title': item.get('title') or '',
                'author': item.get('uploader') or item.get('channel') or '',
                'author_id': item.get('uploader_id') or item.get('channel_id') or '',
                'author_verified': True,
                'author_avatar': '',
                'duration': _format_duration(duration),
                'length_seconds': duration,
                'is_live': item.get('is_live') or False,
                'views': f"{view_count} views",
                'thumbnail': f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                'published_text': str(item.get('upload_date') or ''),
                'description': item.get('description') or '',
            })
        return results


@app.get("/health")
def health():
    return {"status": "ok", "has_cookies": COOKIE_FILE_PATH is not None}


@app.get("/extract")
async def extract(url: str = Query(..., description="YouTube Video ID or Full URL")):
    if not url.startswith("http"):
        target_url = f"https://www.youtube.com/watch?v={url}"
    else:
        target_url = url

    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(executor, _extract_worker, target_url)
        if not info:
            raise HTTPException(status_code=404, detail="Could not extract video info")
        return info
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/search")
async def search(q: str = Query(..., description="Search keyword"), limit: int = 20):
    try:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(executor, _flat_search_worker, q, limit)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/trending")
async def trending():
    try:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(executor, _flat_trending_worker)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
