import os
import re
import time
import base64
import asyncio
import traceback
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import yt_dlp

class CookiePayload(BaseModel):
    cookies_base64: str

app = FastAPI(title="Raw Format Inspector Service")

executor = ThreadPoolExecutor(max_workers=1)

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


# 🌟 全量探针配置：不做任何格式筛选，不丢弃任何流，原生抓取
def get_raw_inspector_opts():
    opts = {
        'skip_download': True,
        'extract_flat': False,
        'noplaylist': True,
        'no_warnings': False,
        'socket_timeout': 20,
        'no_color': True,
        # 允许所有可用格式并忽略格式选择错误，确保全部流进入 formats
        'ignore_no_formats_error': True,
        'extractor_args': {
            'youtube': {
                # 允许多客户端回退，以获取最大范围的音视频流
                'player_client': ['android', 'web', 'mweb', 'ios'],
            }
        }
    }
    if COOKIE_FILE_PATH:
        opts['cookiefile'] = COOKIE_FILE_PATH
    return opts


def _raw_extract_worker(target_url: str):
    try:
        with yt_dlp.YoutubeDL(get_raw_inspector_opts()) as ydl:
            # 抓取未做任何删减的全部原始信息
            info = ydl.extract_info(target_url, download=False)
            if not info:
                return {"error": "yt-dlp returned empty info", "raw_formats": []}
            
            # 使用 yt-dlp 自带的安全序列化工具，保证全部字典可被 JSON 输出
            sanitized = ydl.sanitize_info(info)
            
            # 把全部原始 formats 提取出来
            raw_formats = sanitized.get("formats") or []
            
            return {
                "id": sanitized.get("id"),
                "title": sanitized.get("title"),
                "duration": sanitized.get("duration"),
                "channel": sanitized.get("channel"),
                "total_formats_found": len(raw_formats),
                "has_cookies": COOKIE_FILE_PATH is not None,
                # 🌟 包含全部原生流信息（包括所有的 format_id, itag, ext, vcodec, acodec, url）
                "all_formats_list": raw_formats,
                "thumbnails": sanitized.get("thumbnails"),
                "full_sanitized_info": sanitized
            }
    except Exception as e:
        return {
            "error_type": type(e).__name__,
            "error_message": str(e),
            "traceback": traceback.format_exc(),
            "has_cookies": COOKIE_FILE_PATH is not None
        }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "has_cookies": COOKIE_FILE_PATH is not None,
        "cookie_path": COOKIE_FILE_PATH
    }


# 🌟 核心探针接口：永远返回 200，并吐出全部格式数据
@app.get("/extract")
async def extract(url: str = Query(..., description="YouTube Video ID or Full URL")):
    clean_url = url.strip()
    if not clean_url.startswith("http"):
        target_url = f"https://www.youtube.com/watch?v={clean_url}"
    else:
        target_url = clean_url

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, _raw_extract_worker, target_url)
    return result


@app.post("/update_cookies")
def update_cookies(payload: CookiePayload):
    global COOKIE_FILE_PATH
    try:
        raw_bytes = base64.b64decode(payload.cookies_base64.strip())
        target_path = "/tmp/yt_cookies.txt"
        with open(target_path, "wb") as f:
            f.write(raw_bytes)

        COOKIE_FILE_PATH = target_path
        print("🎉 [Hot Reload] 成功更新 YouTube Cookie！")
        return {"status": "success", "message": "Cookies updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to update cookies: {e}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
