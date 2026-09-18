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
# 🌟 2. 组装具备高容错特性的 yt-dlp 核心配置
# ==========================================
def get_ydl_opts(use_cookies: bool = True):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': False,
        'no_color': True,
        # 🌟 核心防报错：即使默认格式未完全匹配，也绝不抛出 500 异常，保留全部提取到的格式列表
        'ignore_no_formats_error': True,
        'check_formats': False,
        # 🌟 多路客户端智能降级链：ios (免挑战高速) -> web (Node.js解密) -> android
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'web', 'mweb', 'android']
            }
        }
    }
    if use_cookies and COOKIE_FILE_PATH:
        opts['cookiefile'] = COOKIE_FILE_PATH
    return opts


def _extract_worker(url: str):
    # 策略 1：如果配置了 Cookie，优先带 Cookie 提取
    if COOKIE_FILE_PATH:
        try:
            with yt_dlp.YoutubeDL(get_ydl_opts(use_cookies=True)) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and info.get('formats'):
                    return info
        except Exception as e:
            print(f"⚠️ [Cookie 提取重试] 带 Cookie 提取受阻 ({e})，正在自动无缝降级免 Cookie 重试...")

    # 策略 2：免 Cookie 兜底提取（应对 Cookie 过期或客户端互斥场景）
    with yt_dlp.YoutubeDL(get_ydl_opts(use_cookies=False)) as ydl:
        return ydl.extract_info(url, download=False)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "has_cookies": COOKIE_FILE_PATH is not None
    }


@app.get("/extract")
async def extract(url: str = Query(..., description="YouTube Video ID or Full URL")):
    # 🌟 修复原代码中的拼接错误
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
