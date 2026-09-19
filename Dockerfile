FROM python:3.11-slim

WORKDIR /app

# 1. 安装基础系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      curl \
      ca-certificates \
      ffmpeg \
      fonts-liberation \
      libnss3 \
      libatk-bridge2.0-0 \
      libgtk-3-0 \
      libasound2 \
      libdrm2 \
      libgbm1 && \
    rm -rf /var/lib/apt/lists/*

# 2. 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. 安装 Chromium 内核 (仅内核，不要多余组件)
RUN playwright install chromium

COPY . .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
