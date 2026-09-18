import os
import base64
import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException, Query
import yt_dlp

app = FastAPI(title="Persistent YT-DLP Internal Service")

# 限制全局最多 2 个提取并发，避免突发高负载
executor = ThreadPoolExecutor(max_workers=2)

# ==========================================
# 🌟 1. 还原原版 Cookie 解密逻辑
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
    print("ℹ️ [Cookie Loader] 未提供 YOUTUBE_COOKIES_BASE64")

# ==========================================
# 🌟 2. 1:1 还原原版提取参数（黄金组合）
# ==========================================
def get_original_ydl_opts(use_cookie: bool = True):
    opts = {
        'skip_download': True,
        'extract_flat': False,
        'noplaylist': True,
        'no_warnings': True,
        'socket_timeout': 15,
        # 🌟 原版 Dart 代码中写死的黄金组合：排除报错的 tv 端，激活 web 与内嵌流
        'extractor_args': {
            'youtube': {
                'player_client': ['default', '-tv_downgraded', 'web_embedded']
            }
        }
    }
    
    # 原版逻辑：如果有 cookie 则挂载 --cookies
    if use_cookie and COOKIE_FILE_PATH:
        opts['cookiefile'] = COOKIE_FILE_PATH
        
    return opts


def _extract_worker(url: str):
    # 策略 A：采用原版配置（带 Cookie 与 Deno 解密）
    try:
        with yt_dlp.YoutubeDL(get_original_ydl_opts(use_cookie=True)) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats') or []
            if formats:
                return info
    except Exception as e:
        print(f"⚠️ [原版通道 A 异常]: {e}，尝试免 Cookie 通道重试...")

    # 策略 B：免 Cookie 纯净重试（防止 Cookie 自身被 Google 风控污染）
    with yt_dlp.YoutubeDL(get_original_ydl_opts(use_cookie=False)) as ydl:
        return ydl.extract_info(url, download=False)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "has_cookies": COOKIE_FILE_PATH is not None
    }


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


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
