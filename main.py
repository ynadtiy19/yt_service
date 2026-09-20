import os
import gc
import re
import json
import time
import base64
import threading
import subprocess
import urllib.request
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import yt_dlp

# 🌟 核心修复：定义 Cookie 载荷数据结构（解决 NameError）
class CookiePayload(BaseModel):
    cookies_base64: str

executor = ThreadPoolExecutor(max_workers=2)
_MEMORY_CACHE = {}
_CACHE_TTL = 1800
_tunnel_started = False


def _init_ssh_and_keys():
    """从环境变量动态读取并初始化 SSH 密码与 AtKeys 文件"""
    ssh_password = os.environ.get("PASSWORD", "noports123")
    subprocess.run(
        f'echo "root:{ssh_password}" | chpasswd',
        shell=True,
        check=True
    )

    atkeys_content = os.environ.get("ATKEYS_CONTENT", "")
    device_atsign = os.environ.get("DEVICE_ATSIGN", "@absolute3140")
    key_path = f"/root/.atsign/keys/{device_atsign}_key.atKeys"

    if atkeys_content.strip():
        try:
            data = json.loads(atkeys_content.strip())
            for k, v in data.items():
                if isinstance(v, str):
                    clean_v = v.strip().rstrip("=")
                    rem = len(clean_v) % 4
                    if rem == 2:
                        data[k] = clean_v + "=="
                    elif rem == 3:
                        data[k] = clean_v + "="
                    else:
                        data[k] = clean_v
            with open(key_path, "w") as f:
                f.write(json.dumps(data))
            os.chmod(key_path, 0o600)
            print(f"✅ [AtKeys] 成功从环境变量注入并格式化密钥: {key_path}")
        except Exception as e:
            print(f"⚠️ [AtKeys] 写入异常: {e}")
            with open(key_path, "w") as f:
                f.write(atkeys_content.strip())
            os.chmod(key_path, 0o600)
    
    return key_path


def _start_background_tunnel():
    """在后台常驻启动 sshd 与 sshnpd 守护进程"""
    global _tunnel_started
    if _tunnel_started:
        return
    _tunnel_started = True

    def _worker():
        try:
            print("🚀 [Zeabur Tunnel] 正在初始化后台 SSH 与 NoPorts 守护进程...")
            env = os.environ.copy()
            env["HOME"] = "/root"
            env["USER"] = "/root"

            key_path = _init_ssh_and_keys()

            subprocess.run(["/usr/sbin/sshd"], check=True)

            device_atsign = os.environ.get("DEVICE_ATSIGN", "@absolute3140")
            manager_atsign = os.environ.get("MANAGER_ATSIGN", "@gemini2banana")
            device_name = os.environ.get("DEVICE_NAME", "zeabur")

            cmd = [
                "/root/.local/bin/sshnpd",
                "-a", device_atsign,
                "-m", manager_atsign,
                "-d", device_name,
                "-k", key_path,
                "-s",
                "--no-hide"
            ]
            print(f"📡 [Zeabur Tunnel] sshnpd 已就绪并在后台监听 (设备名: {device_name})...")
            subprocess.Popen(cmd, env=env)
        except Exception as e:
            print(f"🔴 [Zeabur Tunnel] 启动异常: {e}")

    threading.Thread(target=_worker, daemon=True).start()


def _get_cookie_file_path() -> str | None:
    cookie_b64 = os.environ.get("YOUTUBE_COOKIES_BASE64")
    if not cookie_b64 or not cookie_b64.strip():
        return None
    try:
        sanitized_b64 = cookie_b64.replace("\r", "").replace("\n", "").strip()
        decoded_bytes = base64.b64decode(sanitized_b64)
        cookie_path = "/tmp/yt_cookies.txt"
        with open(cookie_path, "wb") as f:
            f.write(decoded_bytes)
        return cookie_path
    except Exception as e:
        print(f"⚠️ [Cookie Loader] 解密失败: {e}")
        return None


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


def get_ydl_opts():
    cookie_file = _get_cookie_file_path()
    opts = {
        'skip_download': True,
        'extract_flat': False,
        'noplaylist': True,
        'no_warnings': True,
        'socket_timeout': 15,
        'no_color': True,
        'ignore_no_formats_error': True,
        'writesubtitles': False,
        'writeautomaticsub': False,
        'remote_components': ['ejs:github'],
        'extractor_args': {
            'youtube': {
                'player_client': ['android_vr', 'ios', 'web_safari', 'android'],
            }
        }
    }
    if cookie_file:
        opts['cookiefile'] = cookie_file
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

    sanitized = yt_dlp.YoutubeDL().sanitize_info(info)

    for useless_key in ['automatic_captions', 'subtitles', 'heatmap', 'comments']:
        sanitized.pop(useless_key, None)

    raw_formats = sanitized.get('formats') or []
    valid_formats = [
        f for f in raw_formats 
        if isinstance(f, dict) 
        and f.get('url') 
        and not str(f.get('format_note', '')).lower().startswith('storyboard')
        and not str(f.get('format_id', '')).startswith('sb')
        and f.get('ext') != 'mhtml'
        and (f.get('vcodec') != 'none' or f.get('acodec') != 'none')
    ]

    sanitized['formats'] = valid_formats

    format_streams = []
    adaptive_video_streams = []
    adaptive_audio_streams = []

    for f in valid_formats:
        vcodec = f.get('vcodec') or 'none'
        acodec = f.get('acodec') or 'none'
        height = f.get('height') or 0
        ext = f.get('ext') or 'mp4'
        quality_label = f"{height}p" if height > 0 else (f.get('format_note') or '360p')

        # 1. 复合流 (音画合一)
        if vcodec != 'none' and acodec != 'none':
            format_streams.append({
                'itag': str(f.get('format_id')),
                'quality_label': quality_label,
                'container': ext,
                'url': f.get('url'),
                'is_adaptive': False
            })
        # 2. 独立高清视频流 (720p, 1080p, 1440p, 4K)
        elif vcodec != 'none' and acodec == 'none':
            adaptive_video_streams.append({
                'itag': str(f.get('format_id')),
                'quality_label': quality_label,
                'resolution': quality_label,
                'container': ext,
                'fps': f.get('fps') or 30,
                'height': height,
                'url': f.get('url'),
                'is_adaptive': True
            })
        # 3. 独立音频流 (M4A / Opus)
        elif vcodec == 'none' and acodec != 'none':
            adaptive_audio_streams.append({
                'itag': str(f.get('format_id')),
                'container': ext,
                'bitrate': str(f.get('abr') or '128'),
                'url': f.get('url')
            })

    adaptive_video_streams.sort(key=lambda x: x.get('height') or 0, reverse=True)
    adaptive_audio_streams.sort(key=lambda x: float(x.get('bitrate') or 0), reverse=True)

    sanitized['format_streams'] = format_streams
    sanitized['adaptive_video_streams'] = adaptive_video_streams
    sanitized['adaptive_audio_streams'] = adaptive_audio_streams

    avatar_url = extract_channel_avatar(sanitized)
    sanitized['author_avatar'] = avatar_url
    sanitized['uploader_avatar'] = avatar_url

    _MEMORY_CACHE[url] = (now, sanitized)
    if len(_MEMORY_CACHE) > 30:
        oldest_key = min(_MEMORY_CACHE.keys(), key=lambda k: _MEMORY_CACHE[k][0])
        _MEMORY_CACHE.pop(oldest_key, None)

    gc.collect()
    return sanitized


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
        if len(_MEMORY_CACHE) > 30:
            oldest_key = min(_MEMORY_CACHE.keys(), key=lambda k: _MEMORY_CACHE[k][0])
            _MEMORY_CACHE.pop(oldest_key, None)

        gc.collect()
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
        if len(_MEMORY_CACHE) > 30:
            oldest_key = min(_MEMORY_CACHE.keys(), key=lambda k: _MEMORY_CACHE[k][0])
            _MEMORY_CACHE.pop(oldest_key, None)

        gc.collect()
        return results


# ==================== FastAPI 生命周期与端点 ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 服务启动时初始化并启动隧道
    _start_background_tunnel()
    yield
    # 服务退出清理
    executor.shutdown(wait=False)

web_app = FastAPI(title="Ultra-Stable Lightweight YT-DLP Service", lifespan=lifespan)

@web_app.get("/health")
def health():
    has_cookies = _get_cookie_file_path() is not None
    return {
        "status": "ok",
        "has_cookies": has_cookies,
        "tunnel_active": _tunnel_started,
        "device_name": os.environ.get("DEVICE_NAME", "zeabur"),
        "cached_entries": len(_MEMORY_CACHE)
    }

@web_app.get("/extract")
async def extract(url: str = Query(..., description="YouTube Video ID or Full URL")):
    clean_url = url.strip()
    if not clean_url.startswith("http"):
        target_url = f"https://www.youtube.com/watch?v={clean_url}"
    else:
        target_url = clean_url

    try:
        import asyncio
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(executor, _extract_worker, target_url)
        if not info:
            raise HTTPException(status_code=404, detail="Could not extract video info")
        return info
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@web_app.get("/search")
async def search(q: str = Query(..., description="Search keyword"), limit: int = 20):
    try:
        import asyncio
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(executor, _flat_search_worker, q, limit)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@web_app.post("/update_cookies")
def update_cookies(payload: CookiePayload):
    global _MEMORY_CACHE
    try:
        raw_bytes = base64.b64decode(payload.cookies_base64.strip())
        target_path = "/tmp/yt_cookies.txt"
        with open(target_path, "wb") as f:
            f.write(raw_bytes)

        _MEMORY_CACHE.clear()
        gc.collect()
        return {"status": "success", "message": "Cookies updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to update cookies: {e}")

@web_app.get("/trending")
async def trending():
    try:
        import asyncio
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(executor, _flat_trending_worker)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
