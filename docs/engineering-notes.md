# 工程笔记与设计问答

> 企业智能知识库 Agent 平台文档集之一：踩坑记录、设计取舍问答、可进一步优化方向。
> 与 [架构与模块设计](./architecture.md)、[评测体系](./evaluation.md) 配套阅读。

---

## 目录

1. [工程笔记](#一工程笔记)
2. [设计问答](#二设计问答)
3. [可进一步优化方向](#三可进一步优化方向)

---

## 一、工程笔记

1. **环境变量命名冲突**：用 `MILVUS_DB_URI`，不是 `MILVUS_URI`（后者是 pymilvus 保留名，设了会报 `Illegal uri`）。
2. **系统代理残留**：代理软件关了但系统代理还在，LLM/embedding 报 `Connection error`。
3. **Windows GBK 控制台**：打印 `✓/✗` 会 `UnicodeEncodeError`，用 ASCII。
4. **pymilvus 版本差异**：`delete` 3.0 返回 list（`[count]`）、2.x 返回 dict（`{"delete_count": n}`），需兼容。
5. **Milvus 需显式 load**：建 collection 后要 `load_collection` 才能 search/query（幂等可重复调用）。
6. **启动目录**：必须从 `agent/` 根目录启动，否则 `from backend.xxx` 导入失败。
7. **Milvus Lite 是单进程独占的**：后端 uvicorn 开着时，评测脚本打不开 `./milvus.db`，抛一大段 pymilvus 堆栈。评测脚本因此都带 `_explain()`，把该异常翻译成「请先停掉后端」——否则极易被误当成代码 bug 去排查。
8. **MCP stdio 连接内部是 anyio task group**：`enter`/`exit` 必须在同一个 asyncio task，否则报 `Attempted to exit cancel scope in a different task than it was entered in`。而 `get_mcp_tools()` 由各请求协程调用、随请求结束销毁，不能由它持有连接——改为长驻后台任务独占连接，自己 enter 自己 exit。
9. **可选依赖不能写成硬依赖**：`tools.py` 原先是直接 `from examples.mcp import mcp_client`，没装 `mcp` 包的环境会让**所有** Agent 请求挂掉，而不只是 MCP 那部分功能。改为捕获 `ImportError` 降级。
10. **评测语料误写进生产 collection**：早期 `eval/build_index.py` 没做隔离，把 `eval/data/` 下的公文写进了生产库，导致「索引了 963 个 chunk，实际只有 2 份上传文件」。现改为评测使用独立的 `milvus_collection_eval`，与生产 collection 完全隔离；历史遗留数据已定点清理。

---

## 二、设计问答

<a id="q1"></a>
**Q1：介绍一下你的项目 / 架构？**
一句话 + 分层架构图 + 核心链路（见 [《架构与模块设计》第二节](./architecture.md#sec-2)）。重点讲「RAG 检索 + Agent 决策」两个能力。

<a id="q2"></a>
**Q2：RAG 的完整流程是什么？**
切片 → embedding → 入库 Milvus → 检索时（query embedding → Milvus + BM25 双路 → RRF 融合 → 去重 → 年份软排序）→ 拼 context → LLM 生成（temperature=0.2，要求基于资料、标注来源）。

<a id="q3"></a>
**Q3：为什么用混合检索（向量 + BM25）？**
向量检索擅长语义相似，但「十四五/十五五」这种形近词、精确关键词（知识产权）容易漏；BM25 擅长精确匹配。两者互补，RRF 融合后命中率显著提升。

<a id="q4"></a>
**Q4：RRF 融合是什么？为什么不用直接加权？**
见 [《架构与模块设计》3.5 节](./architecture.md#sec-3-5)。核心：分数量纲不同、不可直接比，RRF 用排名做融合，对排序位置打分 `1/(k+rank+1)`。

<a id="q5"></a>
**Q5：「年份串味」怎么解决？**
多份公报正文高度雷同，纯向量检索会把错误年份排前面。做法：① 文件名注入 chunk 文本让 embedding 编码年份；② query 正则提取年份；③ 含年份时扩大候选集；④ 按文件名年份**软排序**（不硬过滤，避免误伤「十五五」类文档）。

<a id="q6"></a>
**Q6：Function Calling 怎么实现？为什么不直接用 LangChain / LangGraph？**
见 [《架构与模块设计》4.1](./architecture.md#sec-4-1) / [4.3 节](./architecture.md#sec-4-3)。自研执行循环 + OpenAI tools schema + 全链路容错。
需要展开的是「不用的理由」：这条循环承载了 Agent 的全部工程细节（截断保护、超时、迭代上限、
history 滑动窗口、工具异常回灌、前置思考的丢弃时机、prompt 随工具集变化）。
框架的价值是把这些决策封装起来，而本项目的取舍恰好相反——这些决策正是需要被观察和调整的部分：
工具输出预算按工具分档、`get_document` 的分页续读、引文编号整轮唯一，都是在这条循环里落地的。
框架托管会把这些藏进黑盒，出问题时无从定位。`examples/langgraph_agent/` 用状态机复刻了同一套循环，
用于对照说明框架在底层做了什么；主线不引入框架。

<a id="q7"></a>
**Q7：sql_query 怎么防止 LLM 生成危险 SQL？**
提示词约束是不可靠的，必须落到代码校验。执行层四道闸：① `stmt` 必须 `startswith("SELECT")`（只允许查）；② 正则拒绝多语句/危险关键字（分号拼接、`DROP`/`UPDATE`/`DELETE` 等）；③ 无 `LIMIT` 时自动补 `LIMIT`，硬上限 `agent_sql_max_rows=50`，防全表扫描把结果灌爆上下文；④ 整个执行包在 `asyncio.wait_for` 里，5s 超时。
表结构不靠白名单写死，而是提供一个 `list_tables` 工具让 Agent 先查 schema 再写 SQL——这样加表不用改代码，且 Agent 有据可依不会瞎猜字段名。

<a id="q8"></a>
**Q8：为什么全异步？asyncmy 和 pymysql 区别？**
全异步避免同步阻塞事件循环，提升并发吞吐。asyncmy 是异步驱动（基于 asyncio），pymysql 是同步驱动会阻塞；SQLAlchemy 2.0 用 `create_async_engine` + `async_sessionmaker` 配合异步驱动。

<a id="q9"></a>
**Q9：JWT 认证流程？密码怎么存？**
登录 → 校验 pbkdf2 哈希 → 签发 JWT(sub/role/exp) → 前端带 Bearer → 后端 `decode_token` 解析 → 依赖注入鉴权。密码存 `salt$hash`（pbkdf2 sha256 10 万次），`compare_digest` 防时序攻击。

<a id="q10"></a>
**Q10：Milvus 和 FAISS 区别？为什么迁移到 Milvus？**
FAISS 是单机向量检索库（进程内、无持久化/分布式）；Milvus 是向量数据库，支持持久化、collection 管理、分布式、元数据过滤、生产部署。项目从 FAISS 迁移到 Milvus 是为了生产级能力（standalone 部署、持久化、可扩展）。

<a id="q11"></a>
**Q11：评测怎么做？Recall 指标含义？**
见 [《评测体系》](./evaluation.md)。分两层：**检索层看召回**（Recall@5/@8、MRR@8、年份 Top-1），**Agent 层看行为**（工具选择、引用命中、拒答、LLM 裁判的正确性/忠实性）。
关键设计是**消融**：4 种检索配置跑的是 `rag.py` 的同一条代码路径（只切 `mode`），保证实验结论与线上行为一致，不是另写一份「为了出数据」的实验代码。
所有指标由脚本落盘成 JSON 再渲染成文档表格，**文档里不写死数字**——数据集一变旧数字必然失效且无法验证。

<a id="q12"></a>
**Q12：如果数据量很大，怎么优化？**
① 向量索引用 HNSW/IVF 替代 FLAT；② chunk 全文放 MySQL、Milvus 只存向量+id 避免重读；③ embedding 缓存；④ 加 Rerank 模型；⑤ BM25 用 Elasticsearch 等倒排引擎；⑥ 检索结果加缓存。

<a id="q13"></a>
**Q13：如果 MCP Server 挂了，你的 Agent 会怎样？**（重点题）
先说结论：**不影响答题，只是工具集收缩**。关键是 prompt 不是写死的字符串，而是「本次真实可用工具集」的函数：`get_all_tools()` 先返回本次真实可用的工具，`build_system_prompt(tools_schema)` 据此生成工具清单和强制规则。
运行时状态类工具（查时间/系统信息）在列时，才追加「必须调工具、禁止凭记忆猜」的硬性规则；不在列时该规则根本不出现。
两条降级路径：没装 `mcp` 包 → 捕获 `ImportError` 只用 4 个内置工具；server 连不上 → client 记录错误返回空工具集，不抛异常。
为什么这么做：如果 prompt 写死「你必须调用 get_current_time」而该工具此刻不存在，模型将倾向于发起不存在的工具调用或空转。**工具可用性必须反过来影响 Agent policy**，否则降级只做了一半。

<a id="q14"></a>
**Q14：流式输出怎么实现的？为什么不用 EventSource？**
后端 `/chat/agent/stream` 是个 `async generator`，逐帧吐 SSE 事件：`thinking` / `tool_call` / `tool_result` / `answer`。Agent 一次回答要跑多轮工具调用，整段返回意味着用户对着空白等十几秒，也看不到中间决策。
前端用原生 `fetch` + 手动解析帧（按 `\n\n` 切分），不用 `EventSource`——后者只支持 GET 且无法带 `Authorization` 头，而 Agent 问答需要 POST 传 query 且需要登录态。
渲染用 `requestAnimationFrame` 批量提交，避免高频 token 触发逐帧重排。

<a id="q15"></a>
**Q15：你怎么发现性能问题的？缓存怎么保证不读到脏数据？**
**先测再改，不猜。** 把一次 `rag.search()` 拆开计时，835 个 chunk 的结果是：

```
get_all_chunks()  全量拉 chunk 正文    907.8 ms   27.8%   ← 与查询无关
BM25Index 构建    全部 chunk 重新分词   281.7 ms    8.6%   ← 与查询无关
embed_query       外部 API             621.4 ms   19.0%   ← 不可优化
search_by_vector  Milvus 真正干活      1455.9 ms   44.5%
ensure_collection + count()              3.8 ms    0.1%
```

前两项**都只依赖语料内容**，语料在一次服务期里通常不变，却每次检索都重做。而且两者失效条件完全相同，所以合并成一个「语料缓存」条目 —— 合并的好处是不会出现两套缓存各说各话。

**指纹用 `count()`**，不用全量数据：它走 `get_collection_stats`，不需要 load collection，实测 1.8ms，比全量拉取便宜两个数量级。`count` 单独用有个盲区——「删 N 条再加 N 条」数量没变但内容变了——所以所有写路径（`build_index_for_file` / `delete_by_sources` / `clear`）都显式失效，再叠 60s TTL 兜住多 worker 场景。

实测：不含年份的查询 **1531ms → 411ms（3.7x）**；含年份的（触发全量扫描）2956ms → 1941ms。脚本会校验**命中缓存前后检索结果逐条一致**——这是缓存唯一的正确性要求。

**同一轮测量还暴露了另一笔账**：年份策略把候选集放大到全量后，`search_by_vector` 从 49ms 涨到 1456ms。**年份软排序的召回收益是拿 1.2 秒延迟换的**，这笔代价之前完全没被看见。已记入「可进一步优化方向」第 3 条。

<a id="q16"></a>
**Q16：拒答为什么不放在检索层？**
检索层没有「拒答」语义。要定义「检索结果不足以回答」，得设一个相似度阈值——但这个阈值不稳定（取决于 query 长短、语料分布），阈值本身就成了新的误判源。
所以判「检索到的资料是否足以回答」这件事交给 Agent，它有完整上下文和推理能力。评测上也是分开的：检索层只算 Recall（无答案题不计入，因为算不了），拒答率由 Agent 层单独评测。
反过来，如果要加检索层阈值，前提是先用评测集把阈值标定出来——这是「可进一步优化方向」里明确写了前提条件的一项。

<a id="q17"></a>
**Q17：为什么 MCP / 多智能体 / LangGraph 放在 examples/ 而不是主线？**
因为它们不解决主线问题，只证明主线架构可扩展。主线只有两个文件：`rag.py`（混合检索）和 `executor.py`（自研 Agent 执行循环），其余都是支撑。
放到 `examples/` 有三个实际好处：① 不启动完全不影响后端，MCP 掉线/没装都不影响问答；② 依赖是可选的，不用把 `mcp`、`langgraph` 变成所有人的硬依赖；③ 明确区分「能力边界」与「主线职责」——有能力做，不等于该放进主线。
LangGraph 那份是同一套循环的框架对照实现，用于说明框架在底层做了什么。

<a id="q18"></a>
**Q18：这套评测的结果可信吗？**
可信度取决于金标准怎么来的，所以题目生成做了三道校验闸门：① 题目必须能**溯源回原段落**（与源段落 bigram 重合度达标）；② 数字类题目的源段落必须真的含数字（早期生成出过「面对国际风云变幻，要续写哪两大奇迹」这种不成立的"数字题"）；③ 与已有题目做 Jaccard 去重（早期出过语义重复题）。
另外 LLM 裁判的参照系必须与生产口径同源——重放 Agent 当时真实的工具调用并复现同样的截断与引文编号，
否则会同时犯两个方向的错（漏判幻觉 / 冤枉漏答）。三种错误口径与最终做法、连跑 8 次的复现记录见
[《评测体系》1.4 节](./evaluation.md#sec-1-4)。
最后一条是纪律：数字只从脚本跑出来，跑不出就显示「暂无数据」。**指标数字由脚本生成而非写死，是因为写死的数字必然过期。**

---

## 三、可进一步优化方向

按优先级排序，每条都写清**前提条件**——没有前提条件的优化不成立。

1. **Rerank 重排**：RRF 之后接 Cross-Encoder 精排，预期提升「相似文本」题型区分度。
   前提：它引入一次额外模型调用，得先有消融数据证明收益大于延迟代价。
2. **检索层阈值拒答**：目前拒答由 Agent 判断，可叠加相似度阈值做双保险。
   前提：先用评测集标定出稳定阈值，否则阈值本身就是新的误判源。
3. **年份策略的候选集收窄**：含年份时目前把向量检索放大到全量、再在应用层软排序，
   `search_by_vector` 因此从 49ms 涨到约 1.4s（见 Q15）。方向是先用 Milvus 标量过滤缩小候选集，
   而不是全量捞回来再排。
4. **近似向量索引**：数据量大时用 HNSW/IVF 替代 FLAT。
5. **多路召回**：Query 改写、HyDE、父文档检索（small-to-big）。
6. **引用定位**：回答中标注到具体 chunk 的原文片段，而非只到文档级。
7. **流式 RAG**：`/chat` 目前整段返回，可复用 `/chat/agent/stream` 已有的 SSE 通道。
8. **BM25 缓存跨进程共享**：目前是进程内缓存，多 worker 时每个 worker 各存一份
   （只影响首次命中，可接受）。要共享可挪到 Redis。
9. **生产向量库**：Milvus Lite 仅适合开发，生产切 standalone——docker-compose 里已备好。
10. **安全加固**：JWT refresh token、限流、上传文件大小/类型更严格校验。
11. **可观测性**：检索/生成日志、指标埋点、A/B 评测。

> 已完成的优化不再列在这里（如 SSE 流式输出已实现，见 Q14）。这张表只放**明确知道该做但还没做**的事。
