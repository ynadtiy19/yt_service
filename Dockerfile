FROM python:3.11-slim

WORKDIR /app

# 1. 安装基础工具库与音视频转码工具
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      curl \
      ca-certificates \
      ffmpeg \
      unzip && \
    rm -rf /var/lib/apt/lists/*

# 2. 安装 Deno 引擎（专门辅助 yt-dlp 处理 YouTube 最新的 n-sig 签名算法）
RUN curl -fsSL https://deno.land/install.sh | sh -s -- -y && \
    cp /root/.deno/bin/deno /usr/local/bin/deno && \
    rm -rf /root/.deno

# 3. 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
