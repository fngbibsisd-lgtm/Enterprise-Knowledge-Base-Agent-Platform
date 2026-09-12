# CLAUDE.md

企业智能知识库 Agent 平台 —— 基于 RAG + Function Calling 的企业知识库问答系统。

## 技术栈
- 后端：FastAPI（全异步）+ SQLAlchemy 2.0（asyncmy）+ Alembic + JWT（pyjwt）+ pbkdf2
- 向量库：Milvus（开发用 Milvus Lite 本地文件 `./milvus.db`，生产用 standalone）
- Embedding：Qwen/Qwen3-VL-Embedding-8B（硅基流动，4096 维）；LLM：deepseek-chat
- 数据库：MySQL 8.x；前端：Vue 3 + Vite + TypeScript + Element Plus + Pinia

## 启动（必须在 agent/ 根目录）
- 后端：`uvicorn backend.main:app --host 0.0.0.0 --port 8000`
- 前端：`cd web && npm run dev`（Vite 代理 `/api` → 8000）

## 目录
- `backend/`：core(配置/安全/依赖注入)、db(异步引擎)、models(ORM)、schemas(Pydantic)、repositories、services、agent、tools、api、alembic
- `web/`：Vue 前端；`eval/`：评测集(104题检索/39题Agent) + 脚本，结果以 eval/*_result.json 为准（勿在文档里写死指标数字）
- `examples/`：非主线的可选扩展（MCP / 多智能体 / LangGraph 对照），不启动不影响后端

## 关键规则
- sql_query 工具只允许 SELECT（防 LLM 生成危险 SQL）
- 混合检索：Milvus 向量 + BM25(bigram) → RRF 融合 → 文档去重 → 年份软排序
- 年份是精确枚举值，用字符串匹配，不做向量相似度过滤
- Agent 是手写 Function Calling 循环（面试亮点，勿换成框架）

## 踩坑
- 环境变量用 `MILVUS_DB_URI`，不是 `MILVUS_URI`（后者是 pymilvus 保留名，设了会报 `Illegal uri`）
- 系统代理残留会导致 LLM/embedding 报 Connection error
- Windows GBK 控制台打印 ✓/✗ 会 UnicodeEncodeError，用 ASCII

## 分支
V2 架构重构在 `refactor/architecture` 分支（未合并 main）。
