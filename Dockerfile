FROM python:3.10-slim

WORKDIR /app

# 先复制依赖文件并安装（利用 Docker 层缓存）
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目源码（backend/ + rag_demo/，其余由 .dockerignore 排除）
COPY . .

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
