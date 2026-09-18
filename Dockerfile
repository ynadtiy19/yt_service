FROM python:3.11-slim

WORKDIR /app

# 🌟 安装 ffmpeg, curl 以及 Debian 官方轻量 nodejs（供 yt-dlp 自动解密 n-sig 挑战）
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl ca-certificates nodejs && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
