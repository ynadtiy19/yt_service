FROM python:3.11-slim

# 设置非交互模式和工作目录
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# 安装系统级依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    ffmpeg \
    unzip \
    openssh-server \
    tar \
    && rm -rf /var/lib/apt/lists/*

# 安装 Deno 解密引擎
RUN curl -fsSL https://deno.land/install.sh | sh && \
    cp /root/.deno/bin/deno /usr/local/bin/deno

# 配置 SSH 与 NoPorts 目录及基础组件
RUN mkdir -p /run/sshd /root/.local/bin /root/.atsign/keys /root/.ssh && \
    curl -sSfL https://github.com/atsign-foundation/noports/releases/latest/download/sshnp-linux-x64.tgz -o /tmp/noports.tgz && \
    tar -xzf /tmp/noports.tgz -C /tmp/ && \
    (cp -rf /tmp/sshnp/* /root/.local/bin/ 2>/dev/null || cp -rf /tmp/* /root/.local/bin/ 2>/dev/null || true) && \
    rm -rf /tmp/sshnp* /tmp/noports.tgz && \
    chmod -R +x /root/.local/bin/ && \
    echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAID+hrFcncesRZkCyIFwd6sm4QedUpZu2mUv7xQGM9Bvi ludeyu@ludeyu31abledeMacBook-Air.local" > /root/.ssh/authorized_keys && \
    chmod 700 /root/.ssh && chmod 600 /root/.ssh/authorized_keys && \
    printf "PermitRootLogin yes\nPubkeyAuthentication yes\nStrictModes no\nUsePAM no\nClientAliveInterval 15\nClientAliveCountMax 6\n" >> /etc/ssh/sshd_config

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY main.py .

# 暴露 Zeabur 绑定的端口
EXPOSE 8080

# 启动命令
CMD ["uvicorn", "main:web_app", "--host", "0.0.0.0", "--port", "8080"]
