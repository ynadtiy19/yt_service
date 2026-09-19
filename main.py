import os
import re
import time
import base64
import asyncio
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import yt_dlp

class CookiePayload(BaseModel):
    cookies_base64: str

app = FastAPI(title="Ultra-Stable Lightweight YT-DLP Service")

executor = ThreadPoolExecutor(max_workers=1)
_MEMORY_CACHE = {}
_CACHE_TTL = 1800  # 30 分钟

# 载入环境变量 Cookie
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


def _format_duration(seconds: int) -> str:
    if not seconds or seconds <= 0:
        return "00:00"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


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
                    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15',
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
        except Exception:
            pass

    return ""


# 🌟 核心破局配置：使用移动端客户端，不触发 Web 端 Botguard
def get_ydl_opts():
    opts = {
        'skip_download': True,
        'extract_flat': False,
        'noplaylist': True,
        'no_warnings': True,
        'socket_timeout': 15,
        'no_color': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'android', 'mweb'],
                'player_skip': ['webpage', 'configs'],
            }
        }
    }
    if COOKIE_FILE_PATH:
        opts['cookiefile'] = COOKIE_FILE_PATH
    return opts


def _extract_worker(url: str):
    now = time.time()
    if url in _MEMORY_CACHE:
        cached_time, cached_data = _MEMORY_CACHE[url]
        if now - cached_time < _CACHE_TTL:
            return cached_data

    info = None
    try:
        with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        print(f"⚠️ [提取异常]: {e}")
        return None

    if not info:
        return None

    avatar_url = extract_channel_avatar(info)
    info['author_avatar'] = avatar_url
    info['uploader_avatar'] = avatar_url

    _MEMORY_CACHE[url] = (now, info)
    if len(_MEMORY_CACHE) > 100:
        oldest_key = min(_MEMORY_CACHE.keys(), key=lambda k: _MEMORY_CACHE[k][0])
        _MEMORY_CACHE.pop(oldest_key, None)

    return info


def _flat_search_worker(query: str, limit: int = 20):
    cache_key = f"search_{query}_{limit}"
    now = time.time()
    if cache_key in _MEMORY_CACHE:
        cached_time, cached_data = _MEMORY_CACHE[cache_key]
        if now - cached_time < 600:
            return cached_data

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

        _MEMORY_CACHE[cache_key] = (now, results)
        return results


def _flat_trending_worker():
    cache_key = "trending_global"
    now = time.time()
    if cache_key in _MEMORY_CACHE:
        cached_time, cached_data = _MEMORY_CACHE[cache_key]
        if now - cached_time < 1800:
            return cached_data

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': 'in_playlist',
        'noplaylist': False,
        'socket_timeout': 8,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        res = ydl.extract_info("ytsearch25:trending", download=False)
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

        _MEMORY_CACHE[cache_key] = (now, results)
        return results


@app.get("/health")
def health():
    return {
        "status": "ok",
        "has_cookies": COOKIE_FILE_PATH is not None,
        "cached_entries": len(_MEMORY_CACHE)
    }


@app.get("/extract")
async def extract(url: str = Query(..., description="YouTube Video ID or Full URL")):
    clean_url = url.strip()
    if not clean_url.startswith("http"):
        target_url = f"https://www.youtube.com/watch?v={clean_url}"
    else:
        target_url = clean_url

    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(executor, _extract_worker, target_url)
        if not info:
            raise HTTPException(status_code=404, detail="Could not extract video info")
        return info
    except HTTPException:
        raise
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


@app.post("/update_cookies")
def update_cookies(payload: CookiePayload):
    global COOKIE_FILE_PATH, _MEMORY_CACHE
    try:
        raw_bytes = base64.b64decode(payload.cookies_base64.strip())
        target_path = "/tmp/yt_cookies.txt"
        with open(target_path, "wb") as f:
            f.write(raw_bytes)

        COOKIE_FILE_PATH = target_path
        _MEMORY_CACHE.clear()
        print("🎉 [Hot Reload] 成功更新 YouTube Cookie！")
        return {"status": "success", "message": "Cookies updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to update cookies: {e}")


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
