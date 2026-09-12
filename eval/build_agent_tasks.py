"""
Agent 评测集构建脚本 —— 把 11 题扩充到 40 题，覆盖 8 类 Agent 行为。

用法（必须在 agent/ 根目录）：
    python eval/build_agent_tasks.py            # 打印，不写
    python eval/build_agent_tasks.py --write    # 写入 agent_tasks.json

字段说明：
    type               题型
    query              用户问题
    expected_tools     「至少命中其一」即算工具选择正确
    expected_all_tools True 表示 expected_tools 必须**全部**命中
                       （多工具协作 / 工具链场景才这么要求）
    gold_keywords      文档类题的金标准文档关键词（用于引用命中率）
    requires           该题依赖的外部能力；"mcp" 表示需要 MCP server 在线，
                       离线时本类题会失败，评测脚本会单独标注

文档问答类题目直接从 qa_pairs.json 里抽取（那些题已经过生成校验），
避免手抄题干引入错误。
"""
import argparse
import json
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
QA_FILE = os.path.join(os.path.dirname(__file__), "qa_pairs.json")
OUT_FILE = os.path.join(os.path.dirname(__file__), "agent_tasks.json")

# 保留原有 11 题（作为历史基线，便于对比）
BASE_TASKS = [
    {"type": "文档问答", "query": "十四五时期，常住人口城镇化率的目标是多少？",
     "expected_tools": ["knowledge_search"], "gold_keywords": ["第十四个五年规划"]},
    {"type": "文档问答", "query": "到2030年，人均体育场地面积要达到多少平方米？",
     "expected_tools": ["knowledge_search"], "gold_keywords": ["全民健身计划"]},
    {"type": "文档问答", "query": "国家如何保护专利权人的合法权益、打击侵权假冒行为？",
     "expected_tools": ["knowledge_search"], "gold_keywords": ["知识产权保护和运用"]},
    {"type": "文档问答", "query": "十五五规划纲要的总体部署是什么？",
     "expected_tools": ["knowledge_search"], "gold_keywords": ["第十五个五年规划"]},
    {"type": "文档问答", "query": "2023年国家公务员局的政府信息公开情况？",
     "expected_tools": ["knowledge_search"], "gold_keywords": ["国家公务员局2023"]},
    {"type": "文档问答", "query": "政府信息公开条例规定了哪些内容？",
     "expected_tools": ["knowledge_search"], "gold_keywords": ["政府信息公开条例"]},
    {"type": "统计问答", "query": "最近上传了几个文件？",
     "expected_tools": ["sql_query"], "gold_keywords": []},
    {"type": "统计问答", "query": "数据库里现在一共有多少条聊天记录？",
     "expected_tools": ["sql_query"], "gold_keywords": []},
    {"type": "结构自省", "query": "数据库里有哪些表？每张表分别有哪些字段？",
     "expected_tools": ["list_tables"], "gold_keywords": []},
    {"type": "拒答", "query": "我们公司食堂今天中午吃什么？",
     "expected_tools": [], "gold_keywords": []},
    {"type": "拒答", "query": "下周一A股大盘会涨还是跌？",
     "expected_tools": [], "gold_keywords": []},
]

# 补充的文档问答：从 qa_pairs 里挑新题，覆盖各子主题
DOC_PICKS = [
    ("数字精确", "第十五个五年规划"),
    ("数字精确", "第十四个五年规划"),
    ("数字精确", "第十二个五年规划"),
    ("主题语义", "国民健康"),
    ("主题语义", "中医药振兴"),
    ("相似文本", "特殊教育"),
    ("相似文本", "扩大消费"),
    ("政府信息公开", "送达"),
    ("年份区分", "国家公务员局2025"),
    ("年份区分", "国家电影局"),
]

EXTRA_TASKS = [
    # ---- 统计问答：考察 Agent 是否会写 SQL ----
    {"type": "统计问答", "query": "知识库里一共索引了多少个文本块？",
     "expected_tools": ["sql_query"], "gold_keywords": []},
    {"type": "统计问答", "query": "系统里目前有几个用户账号？分别是什么角色？",
     "expected_tools": ["sql_query"], "gold_keywords": []},
    {"type": "统计问答", "query": "最近一次上传文件是什么时候？",
     "expected_tools": ["sql_query"], "gold_keywords": []},
    {"type": "统计问答", "query": "目前一共有多少个对话会话？",
     "expected_tools": ["sql_query"], "gold_keywords": []},
    {"type": "统计问答", "query": "用户问过的所有问题里，字符数最多的是哪一条？",
     "expected_tools": ["sql_query"], "gold_keywords": []},

    # ---- 结构自省：考察是否会先看表结构再写 SQL ----
    {"type": "结构自省", "query": "系统里记录了哪些类型的数据？分别存在哪些表、有哪些字段？",
     "expected_tools": ["list_tables"], "gold_keywords": []},
    {"type": "结构自省", "query": "用户和他的对话记录之间是怎么关联的？",
     "expected_tools": ["list_tables"], "gold_keywords": []},

    # ---- 拒答：库外问题应当如实说明，不能编造 ----
    {"type": "拒答", "query": "明天北京的天气怎么样？", "expected_tools": [], "gold_keywords": []},
    {"type": "拒答", "query": "帮我写一首关于春天的诗", "expected_tools": [], "gold_keywords": []},
    {"type": "拒答", "query": "我们公司CEO的电子邮箱是多少？", "expected_tools": [], "gold_keywords": []},
    {"type": "拒答", "query": "2030年世界杯冠军会是哪个国家？", "expected_tools": [], "gold_keywords": []},

    # ---- 多工具协作：文档 + 数据库，必须两个都调 ----
    {"type": "多工具协作", "query": "知识库里现在有多少份文件？其中关于全民健身的那份讲了什么目标？",
     "expected_tools": ["knowledge_search", "sql_query"], "expected_all_tools": True, "gold_keywords": ["全民健身计划"]},
    {"type": "多工具协作", "query": "系统里有多少条问答记录？最新的政策文件里关于知识产权讲了什么？",
     "expected_tools": ["knowledge_search", "sql_query"], "expected_all_tools": True, "gold_keywords": ["知识产权保护和运用"]},
    {"type": "多工具协作", "query": "目前上传了几份文件？这些文件里十五五规划的主要指标是什么？",
     "expected_tools": ["knowledge_search", "sql_query"], "expected_all_tools": True, "gold_keywords": ["第十五个五年规划"]},

    # ---- 工具链：先自省结构再查询，考察多轮工具编排 ----
    {"type": "工具链", "query": "系统里的用户表有哪些字段？其中管理员角色有几个账号？",
     "expected_tools": ["list_tables", "sql_query"], "expected_all_tools": True, "gold_keywords": []},
    {"type": "工具链", "query": "上传记录表有哪些字段？一共记录了多少个文本块？",
     "expected_tools": ["list_tables", "sql_query"], "expected_all_tools": True, "gold_keywords": []},
    {"type": "工具链", "query": "对话相关的表有哪些？现在一共存了多少条消息？",
     "expected_tools": ["list_tables", "sql_query"], "expected_all_tools": True, "gold_keywords": []},

    # ---- 运行时状态：只能靠 MCP 工具，凭记忆答一定是错的 ----
    {"type": "运行时状态", "query": "现在的日期和时间是多少？",
     "expected_tools": ["get_current_time"], "requires": "mcp", "gold_keywords": []},
    {"type": "运行时状态", "query": "当前程序运行在什么操作系统上？工作目录是哪里？",
     "expected_tools": ["get_system_info"], "requires": "mcp", "gold_keywords": []},
]


def _pick_doc_tasks() -> list[dict]:
    """从 qa_pairs.json 抽取文档类题目（题干与 gold 都取自已校验的数据集）。"""
    with open(QA_FILE, encoding="utf-8") as f:
        pairs = json.load(f)
    tasks, used = [], set()
    for typ, gold in DOC_PICKS:
        for p in pairs:
            if p["type"] == typ and p["gold_keywords"] == [gold] and p["query"] not in used:
                tasks.append({
                    "type": "文档问答",
                    "query": p["query"],
                    "expected_tools": ["knowledge_search"],
                    "gold_keywords": p["gold_keywords"],
                })
                used.add(p["query"])
                break
        else:
            print(f"  [警告] qa_pairs 里没找到 [{typ}] gold={gold} 的题，跳过")
    return tasks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="写入 agent_tasks.json")
    args = parser.parse_args()

    doc_tasks = _pick_doc_tasks()
    tasks = BASE_TASKS + doc_tasks + EXTRA_TASKS

    # 去重
    seen, deduped = set(), []
    for t in tasks:
        if t["query"] in seen:
            continue
        seen.add(t["query"])
        deduped.append(t)

    from collections import Counter
    print(f"总题数：{len(deduped)}（原 {len(BASE_TASKS)} 题 + 文档 {len(doc_tasks)} + 新增 {len(EXTRA_TASKS)}）")
    print("题型分布：")
    for t, c in Counter(x["type"] for x in deduped).most_common():
        print(f"  {t:<12} {c}")

    multi = sum(1 for x in deduped if x.get("expected_all_tools"))
    need_mcp = sum(1 for x in deduped if x.get("requires") == "mcp")
    print(f"\n其中「必须全部命中工具」的题：{multi}；依赖 MCP 的题：{need_mcp}")

    if not args.write:
        print("\n[dry-run] 未写入。加 --write 才会更新 agent_tasks.json")
        return 0

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)
    print(f"\n已写入 {os.path.relpath(OUT_FILE, PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
