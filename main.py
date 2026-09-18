import os
import base64
import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException, Query
import yt_dlp

app = FastAPI(title="Persistent YT-DLP Internal Service")

# 限制全局最多允许 2 个提取线程并行，确保内存稳固在 100MB 以内
executor = ThreadPoolExecutor(max_workers=2)

# ==========================================
# 🌟 1. 自动解析环境变量中的 YOUTUBE_COOKIES_BASE64
# ==========================================
COOKIE_FILE_PATH = None
cookie_b64 = os.environ.get("YOUTUBE_COOKIES_BASE64")

if cookie_b64 and cookie_b64.strip():
    try:
        # 去除换行与杂质
        sanitized_b64 = cookie_b64.replace("\r", "").replace("\n", "").strip()
        decoded_bytes = base64.b64decode(sanitized_b64)
        
        COOKIE_FILE_PATH = "/tmp/yt_cookies.txt"
        with open(COOKIE_FILE_PATH, "wb") as f:
            f.write(decoded_bytes)
        print("✅ [Cookie Loader] 成功从环境变量加载 YouTube Cookie 文件！")
    except Exception as e:
        print(f"⚠️ [Cookie Loader] Cookie Base64 解密失败: {e}")
        COOKIE_FILE_PATH = None
else:
    print("ℹ️ [Cookie Loader] 未配置 YOUTUBE_COOKIES_BASE64，将以免登录模式出流")

# ==========================================
# 🌟 2. 组装 yt-dlp 核心配置
# ==========================================
YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'skip_download': True,
    'extract_flat': False,
    # 🌟 使用官方 Android 客户端：速度快、不走网页挑战、内存占用极低
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web_embedded']
        }
    }
}

# 如果成功还原出 Cookie 文件，注入 yt-dlp
if COOKIE_FILE_PATH:
    YDL_OPTS['cookiefile'] = COOKIE_FILE_PATH


def _extract_worker(url: str):
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
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
        # 抛给线程池执行，不阻塞 FastAPI 的主异步事件循环
        info = await loop.run_in_executor(executor, _extract_worker, target_url)
        if not info:
            raise HTTPException(status_code=404, detail="Could not extract video info")
        return info
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    # 🌟 线上优先读取平台注入的 PORT 环境变量，默认 8080
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
