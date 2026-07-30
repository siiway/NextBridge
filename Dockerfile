# 使用官方Python 3.13镜像作为基础镜像
FROM python:3.13-slim

# 引入 astral uv (包管理器)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY pyproject.toml uv.lock ./

# 安装Python依赖 (使用 lockfile, 不含 dev 依赖)
RUN uv sync --frozen --no-dev

# 复制项目文件
COPY . .

# 创建数据目录
RUN mkdir -p /app/data

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV NEXTBRIDGE_DATA_DIR=/app/data
# 使用 uv 创建的虚拟环境
ENV PATH="/app/.venv/bin:$PATH"

# 启动命令
CMD ["python", "-m", "main"]
