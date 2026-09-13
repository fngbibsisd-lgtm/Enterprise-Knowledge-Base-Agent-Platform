# 架构与模块设计

> 企业智能知识库 Agent 平台文档集之一，覆盖整体架构、RAG 检索链路、Agent 实现、后端与前端。
> 所有数值与实现细节均来自当前代码（`backend/` + `web/`），建议对照代码阅读。

**同系列**：[评测体系](./evaluation.md) · [工程笔记与设计问答](./engineering-notes.md)

---

## 目录

1. [项目概览](#一项目概览)
2. [整体架构](#二整体架构)
3. [RAG 检索链路（核心）](#三rag-检索链路核心)
4. [Agent 实现（核心设计）](#四agent-实现核心设计)
5. [后端与数据库](#五后端与数据库)
6. [权限认证](#六权限认证)
7. [前端](#七前端)
8. [容器化部署](#八容器化部署)

---

## 一、项目概览

**一句话**：基于 RAG + Function Calling 的企业内部知识库智能问答平台，既能检索制度/政策文档，也能查询结构化数据（上传记录、聊天记录），并提供 Agent 自主决策能力。

**核心技术栈**：

| 层 | 技术 |
|---|---|
| 后端框架 | FastAPI（全异步 async/await） |
| ORM / 迁移 | SQLAlchemy 2.0（asyncmy 异步驱动）+ Alembic |
| 数据库 | MySQL 8.x |
| 向量库 | Milvus（开发用 Milvus Lite 本地文件 `milvus.db`，生产 standalone） |
| 关键词检索 | 自实现 BM25（字符 bigram，零依赖） |
| Embedding | Qwen/Qwen3-VL-Embedding-8B（硅基流动，**4096 维**） |
| LLM | deepseek-chat |
| 认证 | JWT（pyjwt）+ pbkdf2 密码哈希 |
| 前端 | Vue 3 + Vite + TypeScript + Element Plus + Pinia |
| 部署 | Docker Compose（nginx + backend + MySQL + Milvus） |

---

<a id="sec-2"></a>
## 二、整体架构

```
web/ (Vue3)  ──/api 代理──▶  FastAPI 后端 (backend/)
                                │
        ┌───────────────────────┼───────────────────────────┐
        │                       │                           │
   api/ (路由层)           services/ (业务)             agent/ (智能体)
   auth/upload/chat      document/embedding/llm        tools.py(工具schema)
   agent_chat/admin      bm25/vector_store/rag         executor.py(循环)
        │                       │
   schemas/ (校验)      repositories/ (数据访问)      tools/(工具实现)
        │                       │                 search_document / query_database
   core/ (配置/安全/依赖)   models/ (ORM)  ──▶  MySQL
                                  │
                            db/ (异步引擎)
                                  │
                            Milvus (向量)  +  BM25 (关键词)
```

> 上面这张图是**主线**。`examples/`（MCP / 多智能体 / LangGraph 对照）不在其中——
> 它们是可插拔的扩展能力，不启动完全不影响后端运行。为什么这么放，见
> [《工程笔记与设计问答》Q17](./engineering-notes.md#q17)。

### 2.1 目录结构

```
agent/
├── backend/                    FastAPI 后端（全异步）
│   ├── main.py                 入口：app 工厂 + CORS + lifespan（建表/预置admin/建collection/释放MCP）
│   ├── core/                   config(Pydantic Settings) / security(JWT) / deps(依赖注入) / tool_output(工具结果预算+引文编号)
│   ├── db/                     base(声明基类) + session(async 引擎)
│   ├── models/                 ORM：User / UploadedFile / ChatHistory / AgentSession / AgentMessage
│   ├── schemas/                Pydantic 请求响应模型
│   ├── repositories/           数据访问层
│   ├── services/               document(切片) / embedding / llm / bm25 / vector_store(Milvus) / rag ★
│   ├── agent/                  tools.py(工具schema) + executor.py(Agent循环) ★
│   ├── tools/                  search_document / query_database
│   ├── api/                    auth / upload / chat / agent_chat / admin
│   └── alembic/                数据库迁移
├── web/                        Vue 3 前端
│   ├── src/api/                axios 封装
│   ├── src/stores/             Pinia（auth / chat）
│   ├── src/views/              LoginView / ChatView
│   └── src/components/         SideBar / MessageItem
├── eval/                       评测：数据集 + 脚本 + 结果 JSON（见《评测体系》）
│   ├── qa_pairs.json           检索评测集（104 题）
│   ├── agent_tasks.json        Agent 评测集（39 题）
│   ├── generate_qa_pairs.py    从真实语料生成题目（带溯源校验）
│   ├── evaluate_retrieval_ablation.py   检索消融 ★
│   ├── evaluate_agent.py       Agent 评测 ★
│   ├── render_results.py       把结果 JSON 渲染成 README 表格
│   └── bench_search_latency.py 检索延迟构成 + 语料缓存基准
├── examples/                   ★ 可选扩展（非主线）：MCP / 多智能体 / LangGraph 对照
│   └── README.md               三个子包的作用、依赖与降级设计
├── docs/                       文档集：架构 / 评测 / 工程笔记
├── scripts/                    辅助脚本
│   └── test_backend.py         接口冒烟测试
└── docker-compose.yml          Docker 部署（backend + mysql + milvus + nginx）
```

★ = 值得重点阅读的部分。主线仅为 `rag.py` 与 `executor.py` 两个文件，其余均为其支撑。

### 2.2 分层职责

**这样分层的理由**：
- `api/`：只做参数接收、鉴权依赖、调 service、返回响应。
- `services/`：业务逻辑（切片、检索、LLM、向量库封装）。
- `repositories/`：数据访问层，隔离 ORM 操作。
- `schemas/`：Pydantic 请求/响应模型，自动校验。
- `core/`：配置（Settings）、安全（JWT/pbkdf2）、依赖注入（get_current_user）。
- `models/`：SQLAlchemy ORM 模型。

好处：单向依赖、职责单一、便于单测和替换实现（如换向量库只改 `vector_store.py`）。

---

## 三、RAG 检索链路（核心）

完整流程：**切片 → 向量化 → Milvus 向量检索 + BM25 关键词检索 → RRF 融合 → 文档级去重 → 年份软排序**。

### 3.1 文档切片（`services/document.py`）

- 支持 `.pdf`（PyPDF2 提取）和 `.txt`。
- 先**按句切分**（正则 `[。！？；\n]` 断句），再**按固定长度拼接**：`chunk_size=512`（字符）、`chunk_overlap=50`。
- 单句超过 512 时单独成 chunk；相邻 chunk 从尾部回退补 overlap。
- **关键技巧**：入库前把文件名注入 chunk 文本，形如 `【来源：xxx.pdf】正文`，让 embedding 能编码「年份/来源」信息（否则正文雷同、年份分不开）。

### 3.2 Embedding（`services/embedding.py`）

- 模型 `Qwen/Qwen3-VL-Embedding-8B`，输出 **4096 维**向量，走硅基流动 OpenAI 兼容接口。
- 用 `AsyncOpenAI` 异步调用，**批量 20 条**分批请求。
- query 与文档用同一模型，保证向量空间一致。

### 3.3 Milvus 向量库（`services/vector_store.py`）

- collection `knowledge_chunks`，字段：`id`(int64 自增) / `text`(varchar) / `source`(varchar) / `embedding`(float vector, 4096 维)。
- 索引：**FLAT**，度量 **COSINE**（余弦相似度）。
  - 为什么 FLAT：数据量小（demo/评测级别），FLAT 是精确检索、零配置；生产大规模可换 HNSW/IVF 近似索引。
  - 为什么 COSINE：高维向量用余弦更稳定，不受模长影响。
- pymilvus 是同步库，统一用 `asyncio.to_thread` 丢线程池，避免阻塞事件循环。
- collection 需**显式 load 后才能 search/query**（幂等）。

### 3.4 BM25 关键词检索（`services/bm25.py`，零依赖自实现）

- **字符 bigram 分词**：连续数字/字母整体成 token，中文相邻两字成组。
  - 为什么不用 jieba：检索难点是「十四五 / 十五五 / 十三五」这类**形近词**区分，bigram 能精确区分且不引入额外依赖。
- BM25 公式：`score = Σ idf(t) × (tf·(k1+1)) / (tf + k1·(1-b+b·|d|/avgdl))`，`k1=1.5, b=0.75`。
- 每篇文档建倒排索引（posting list），query 时对命中 token 累加得分。

<a id="sec-3-5"></a>
### 3.5 RRF 融合（Reciprocal Rank Fusion）

- 为什么不用「向量分 + BM25 分直接加权」：两者分数**量纲完全不同**（余弦 ∈[-1,1]，BM25 无上界），直接加权会有一方主导。
- RRF 只关心**排名**，对两个检索器各自的 top-k 排名打分：`score += 1/(k + rank + 1)`，`k=60`，再按融合分降序。

### 3.6 文档去重 + 年份软排序（`services/rag.py`）

- **文档级去重**：同一文件多个 chunk 都命中时只保留一个（按融合顺序取首个 source），避免大文件多 chunk「霸榜」。
  **例外**：显式传了 `source`（"精查这一份文档"）时不去重、候选池也扩到全量——
  这时用户的意图是"读这一份"，去重会把同文档里真正答到问题的那条丢掉
  （实测目标 chunk 的 BM25 全量排名是第 0 名却取不到）；不带 source 的路径行为完全不变。
- **年份软排序**：
  1. 正则 `20\d{2}` 从 query 提取年份。
  2. 若含年份，把向量检索的 `search_k` 扩到全量（否则正确年份常排不进 top_k，因各年份公报正文雷同）。
  3. 结果按「文件名是否含该年份」排前面——**软排序而非硬过滤**，避免把「目标年份」误当文档年份、误伤「十五五」类规划文档。

<a id="sec-3-7"></a>
### 3.7 完整检索流程（`rag.search`）

```
query ──▶ embed_query ──▶ Milvus 向量 top-k
        └──▶ BM25(bigram) top-k
              └──▶ RRF 融合 ──▶ 文档去重 ──▶ 年份软排序 ──▶ top_k=8 结果
```

---

## 四、Agent 实现（核心设计）

**一句话**：不引入 Agent 框架，自研 Function Calling 执行循环，让 LLM 自主决策调用「文档检索」或「SQL 查询」两个工具。

<a id="sec-4-1"></a>
### 4.1 为什么自主实现而非框架托管

- 这条循环是 Agent 的**全部工程细节**所在：截断保护、超时、迭代上限、history 滑动窗口、
  工具异常怎么回灌给模型、什么时候丢弃模型的前置思考、prompt 怎么随工具集变化。
  交给框架会把这些决策藏进黑盒，出问题时无从下手。
- 自主实现能完全掌控循环、容错、system prompt 和工具 schema，代价与收益都可见、可改，
  从而降低对框架内部执行机制的依赖——**而不是为了「不用框架」而不用框架**。
- 作为对照，`examples/langgraph_agent/` 里用 LangGraph 状态机复刻了同一套循环，
  用于说明框架在底层做了什么。但主线**不换**（本项目刻意保留自研执行循环，不引入框架）。

### 4.2 工具定义（`agent/tools.py`）

| 工具 | 用途 | 参数 | 说明 |
|---|---|---|---|
| `knowledge_search` | 检索知识库文档 | `query`（自然语言） | 文档类问题（制度/流程/规定），返回带引用编号 `[id]` 的片段 |
| `get_document` | 读某份文档全文 | `source`（文件名） | 需要完整上下文时用，避免只看到片段 |
| `list_tables` | 查数据库表结构 | 无 | 写 SQL **之前**先调它了解字段，避免瞎猜表名 |
| `sql_query` | 查询结构化数据 | `sql`（SQL 语句） | 统计/计数/历史记录类问题 |

- 用 OpenAI `tools` 参数格式（JSON Schema）描述工具，`tool_choice="auto"` 让 LLM 决定是否调用。
- `get_tool_map()` 把工具名映射到实际函数。
- `list_tables` + `sql_query` 构成**工具链**：Agent 需要按依赖顺序先查结构再写 SQL，这是评测里单独一个题型。
- 工具集不全是写死的——MCP 工具是运行时动态发现的，见 [《工程笔记与设计问答》Q13](./engineering-notes.md#q13)。

<a id="sec-4-3"></a>
### 4.3 循环流程（`agent/executor.py`）

```
tools_schema, tool_map = await get_all_tools()      ← 先取本次真实可用的工具
  └─ build_system_prompt(tools_schema)              ← prompt 是工具集的函数（见 Q13）
        └─▶ 循环（最多 agent_max_iterations=6 轮）：
             ├─ 调 LLM（带 tools）
             ├─ 无 tool_calls → 直接返回 answer（结束）
             └─ 有 tool_calls → 并发执行工具 → 结果追加为 tool 消息 → 继续循环
        超轮数 → 返回「处理超时」提示
```

- 循环实现为 `async generator`，每轮 yield SSE 事件（`thinking` / `tool_call` / `tool_result` / `answer`），
  所以同一份循环既能整段返回（`/chat/agent`）也能流式吐出（`/chat/agent/stream`）。
- **有 `tool_calls` 时丢弃模型的前置思考内容**：模型常边想边说「我来查一下……」，
  这段文字会先于工具结果到达前端，造成「答案先于证据」的错觉。
- 多轮对话保留最近 `agent_max_history=12` 条消息（滑动窗口），防止上下文无限增长。
- 单条工具结果按**工具分档**的字符预算截断（`core/tool_output.py`：`knowledge_search` 6000、
  `get_document` 10000、其余兜底 4000），防一次检索灌爆上下文。
  两个坑：① 预算必须按「整条结果」算，按每个片段算会让 8 条 × 6000 一到外层就被砍成第 1 条；
  ② 结构化结果（`sources` 列表）要**逐条裁剪**而不是文本截断——从中间切断 JSON 会让模型读到半条记录，
  甚至把 `"score": 0.1234` 截成 `"score": 0.12`。
- `get_document` 超预算时按 `offset` **分页**（返回 `total_chars`/`has_more`/`next_offset` 让模型续读），
  而不是截断了事：截断后模型不知道自己漏了内容，会把"我没读到"当成"文档里没有"。
  工具层自己保证序列化后不超预算，否则外层一截，`next_offset` 可能落在被切掉的部分。
- 引文编号由 executor 在结果进 messages 前**重编号**为整轮唯一：`rag.search` 的 `id` 只是单次检索内的
  展示序号，一次回答调两次工具就从 1 重来，答案里的 `[4]` 会指不清哪一篇。
  必须在**序列化/截断之前**改——截断可能把 `"id": 12` 切成 `"id": 1`，静默错号。
- **实测证据与验证**（依据，非推断）：目标句位于工具返回文本的**第 5068 字**，而外层截断在 4000 字；
  《十二五规划纲要》全文 **58306 字**；目标 chunk 的 **BM25 全量排名第 0** 却被文档级去重丢弃。
  `eval/repro_context_budget.py` 把当时的一次性测量固化为 **53 条断言**：预算不变量（含 10 条 × 超长文本、
  JSON 必须合法、预算利用率不得因丢条而空置）、长文档可达、分页拼接与全文**逐字相同**、
  5 种非法 `offset`（负数 / 越界 / 非字符串）全部被钳制、引文编号整轮唯一且答案仅引用已存在的编号。
  回归门禁：104 题检索消融的 `bm25` / `vector` / `hybrid` 三个模式与改动前**逐位相同**
  （改动均写成守卫式，不带 `source` 的路径零接触）；延迟基准冷/热一致性未破，
  平均延迟 3.8s、迭代 2.4 轮与改动前持平（39 题平均值，正常波动 ±0.1）。

### 4.4 异常容错（全链路）

- 参数 JSON 解析失败 → 返回错误 tool 消息，不让整体崩。
- 未知工具名 → 返回「未知工具」。
- 工具执行抛异常 → 捕获返回「工具执行失败」。
- LLM 调用失败 → 返回「LLM 调用失败」。
- system prompt 明确「回答必须基于工具返回结果，不能凭空编造」「多次找不到如实告知」。

### 4.5 sql_query 安全限制（`tools/query_database.py`）

防的是 LLM 生成破坏性语句。**提示词约束不可靠，必须落到代码校验**，执行层四道闸：

1. **只允许 SELECT**：`stmt.upper().startswith("SELECT")` 否则直接拒绝。
2. **拒绝多语句与危险关键字**：正则拦截分号拼接、`DROP`/`UPDATE`/`DELETE` 等。
3. **强制行数上限**：无 `LIMIT` 时自动补 `LIMIT agent_sql_max_rows`(=50)，防全表扫描把结果灌爆上下文。
4. **超时**：整个执行包在 `asyncio.wait_for` 里，`agent_sql_timeout_sec`(=5s)。

注意这里**没有表白名单**——加一张表就要改代码，且 Agent 仍不知道字段名。
改用 `list_tables` 工具暴露 schema 让 Agent 先查再写：加表不用改代码，Agent 也有据可依。

---

## 五、后端与数据库

### 5.1 全异步

- FastAPI + `async/await` 全程异步；MySQL 用 `asyncmy` 驱动 + SQLAlchemy 2.0 异步引擎，避免同步 I/O 阻塞事件循环。
- `get_db` 依赖：请求作用域 session，成功 commit、异常 rollback、结束 close。
- `pool_pre_ping=True` 防连接失效。

### 5.2 数据模型（5 张表）

| 表 | 字段 | 说明 |
|---|---|---|
| `users` | id, username(unique), password_hash, role, created_at | role ∈ admin/user |
| `uploaded_files` | id, filename, md5_hash(unique), chunk_count, created_at | 上传文件，MD5 去重 |
| `chat_history` | id, query, answer, sources(JSON 字符串), created_at | RAG 模式聊天记录 |
| `agent_sessions` | id, user_id, title, created_at | Agent 会话（历史列表用） |
| `agent_messages` | id, session_id, role, content, tool_calls(JSON), iterations, created_at | Agent 每轮消息 + 工具调用轨迹 |

后两张是后加的：原先 Agent 历史只存在于前端内存，刷新即丢失，也无法审计 Agent 到底调了什么工具。

### 5.3 Alembic 迁移

- `alembic/versions/0001_initial.py` 建三张表；生产用 `alembic upgrade head`，启动时自动迁移。
- `env.py` 从 Settings 读数据库 URL 覆盖 alembic.ini 占位符。

### 5.4 API 一览

| 接口 | 鉴权 | 说明 |
|---|---|---|
| `POST /auth/login` | 无 | 登录，返回 JWT |
| `POST /auth/register` | 无 | 注册（默认 user 角色） |
| `POST /upload` | admin | 上传 pdf/txt → 建索引（MD5 去重） |
| `POST /chat` | 登录 | RAG 问答（检索→LLM→存记录） |
| `POST /chat/agent` | 登录 | Agent 问答（自主决策工具，整段返回） |
| `POST /chat/agent/stream` | 登录 | Agent 问答（SSE 流式，前端在用） |
| `POST /admin/reset` | admin | 重置知识库（按 2h/12h/24h/all） |
| `GET /status` | 无 | 索引状态（chunk 数） |

---

## 六、权限认证

- **密码哈希**：`pbkdf2_hmac("sha256", ..., 100000)`，存 `salt$hash` 格式；校验用 `secrets.compare_digest` 防时序攻击。
- **JWT**：登录签发 `{sub: username, role, exp}`，HS256，过期 1440 分钟，无状态、可水平扩展。
- **依赖注入**：`HTTPBearer` 解析 token → `get_current_user` 返回 `{username, role}` → `require_admin` 校验 admin 角色（403）。

---

## 七、前端

- Vue 3 + Vite + TypeScript + Element Plus + Pinia + Vue Router。
- `api/http.ts`：axios 封装，请求拦截器自动带 token，响应拦截器统一错误处理（把后端 `detail` 转成 `Error.message`）。
- `stores/auth.ts`：Pinia 存 token/user/role。
- `router`：登录守卫，未登录跳 `/login`。
- 两个视图：`LoginView`、`ChatView`（RAG 问答 / Agent 问答切换）。
- 回答渲染用 `markdown-it`（代码块语法高亮 + 复制按钮 + KaTeX 数学公式）。

---

## 八、容器化部署

- `docker-compose.yml` 四服务：**mysql**(8.4) + **milvus**(standalone, 嵌入式 etcd) + **backend**(FastAPI) + **frontend**(nginx 托管 Vue 构建产物)。
- healthcheck 保证启动顺序（backend 依赖 mysql/milvus 健康）。
- 启动时 Alembic 自动迁移 + 预置 admin + 确保 Milvus collection。
