FROM python:3.10-slim

WORKDIR /app

# 系统依赖（faiss-cpu/milvus-lite 的传递依赖需要 libgomp1）
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 依赖层（利用 Docker 层缓存）
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 源码 + alembic
COPY backend/ backend/
COPY alembic.ini .

EXPOSE 8000

# 启动前先跑数据库迁移，再启动服务
CMD ["sh", "-c", "alembic -c alembic.ini upgrade head && uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
