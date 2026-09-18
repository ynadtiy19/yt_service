FROM python:3.11-slim

WORKDIR /app

# 1. 基础工具库
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      curl \
      ca-certificates \
      ffmpeg \
      unzip && \
    rm -rf /var/lib/apt/lists/*

# 2. 🌟 装回原版的 Deno 引擎（解决 n-sig 签名算法，速度快且原生支持）
RUN curl -fsSL https://deno.land/install.sh | sh -s -- -y && \
    cp /root/.deno/bin/deno /usr/local/bin/deno && \
    rm -rf /root/.deno

# 3. 安装依赖包（包含 yt-dlp-ejs）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
