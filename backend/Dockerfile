# ===== 构建阶段：安装编译工具 + pip 安装 =====
FROM python:3.11-alpine AS builder

WORKDIR /app

# 安装编译依赖
RUN apk add --no-cache gcc musl-dev curl-dev libxml2-dev libxslt-dev linux-headers

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --no-compile -r requirements.txt \
    && rm -rf /usr/local/lib/python3.11/site-packages/pip \
              /usr/local/lib/python3.11/site-packages/setuptools* \
              /usr/local/lib/python3.11/site-packages/wheel*

# ===== 运行阶段：最小运行环境 =====
FROM python:3.11-alpine

# 运行时所需最小系统库
RUN apk add --no-cache libcurl libxml2 libxslt

WORKDIR /app

# 复制 site-packages 和可执行文件（不含编译工具）
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 复制代码
COPY app/ ./app/

# 创建数据目录
RUN mkdir -p data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
