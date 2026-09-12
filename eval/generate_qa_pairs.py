"""
检索评测集生成器 —— 从 eval/data/ 的真实语料锚定生成问题，扩充 qa_pairs.json。

用法（必须在 agent/ 根目录）：
    python eval/generate_qa_pairs.py --dry-run     # 只打印，不写文件
    python eval/generate_qa_pairs.py --write       # 生成并合并进 qa_pairs.json
    python eval/generate_qa_pairs.py --write --replace   # 直接覆盖（不用）

为什么这样生成：
    gold_keywords 由 DOC_SPECS 显式声明，不从文件名猜——保证「标准答案」可审计。
    问题由一个真实段落生成，所以「答案确实在这份文档里」是先验成立的，
    评测结果反映的是**检索排得好不好**，而不是标注是否正确。

选段策略：
    优先挑「稀有词密度高」的句子（用 BM25 分词 + IDF 打分），
    避免选出各年份公报都有的套话（"以习近平新时代中国特色社会主义思想为指导"这类），
    否则生成的问题在任何一份公报里都能找到答案，题目就没有区分度。
"""
import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from openai import AsyncOpenAI

from backend.core.config import get_settings
from backend.services.bm25 import tokenize

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
QA_FILE = os.path.join(os.path.dirname(__file__), "qa_pairs.json")

# 每份文档取几个候选段落（多取一些，让 LLM 有的挑）
PASSAGES_PER_DOC = 8
# 段落最短长度，太短没有出题价值
MIN_PASSAGE_LEN = 40


@dataclass
class DocSpec:
    """一份文档的出题规格。gold 显式声明 = 标准答案可审计。"""
    key: str                 # eval/data 下文件名的唯一前缀
    gold: list[str]          # gold_keywords（必须出现在该文档文件名里）
    type: str                # 题型
    n: int                   # 生成题数
    expected_year: int | None = None
    hint: str = ""           # 给 LLM 的出题侧重
    found: str = field(default="", init=False)


# 出题规格：覆盖 34 份语料里所有尚未被现有 30 题覆盖的部分
DOC_SPECS: list[DocSpec] = [
    # ---- 五年规划纲要：数字精确 ----
    DocSpec("中华人民共和国国民经济和社会发展第十五个五年规划纲要", ["第十五个五年规划"], "数字精确", 4,
            hint="主要目标里的量化指标（如城镇化率、研发投入、人均预期寿命等）"),
    DocSpec("中华人民共和国国民经济和社会发展第十四个五年规划", ["第十四个五年规划"], "数字精确", 3,
            hint="主要目标里的量化指标"),
    DocSpec("中华人民共和国国民经济和社会发展第十一个五年规划", ["第十一个五年规划"], "数字精确", 2,
            hint="主要目标里的量化指标（注意是 2006-2010 年那份）"),
    DocSpec("国民经济和社会发展第十二个五年规划纲要", ["第十二个五年规划"], "数字精确", 2,
            hint="主要目标里的量化指标"),
    DocSpec("中华人民共和国国民经济和社会发展第十三个五年规划纲要", ["第十三个五年规划"], "数字精确", 2,
            hint="主要目标里的量化指标"),
    DocSpec("中华人民共和国国民经济和社会发展第十个五年计划纲要", ["第十个五年计划"], "数字精确", 2,
            hint="主要目标里的量化指标（注意是「计划」不是「规划」）"),

    # ---- 部门「十五五」专项规划：数字精确 + 主题语义 ----
    DocSpec("国务院关于印发《知识产权保护和运用“十五五”规划》的通知", ["知识产权保护和运用"], "数字精确", 3,
            hint="量化目标（专利拥有量、知识产权密集型产业增加值占比等）"),
    DocSpec("国务院关于印发《全民健身计划（2026—2030年）》的通知", ["全民健身计划"], "数字精确", 3,
            hint="量化目标（体育场地面积、锻炼人数比例等）"),
    DocSpec("国务院关于印发《国民健康“十五五”规划》的通知", ["国民健康"], "数字精确", 2,
            hint="健康指标量化目标"),
    DocSpec("国务院关于《扩大消费“十五五”规划》的批复", ["扩大消费"], "数字精确", 2,
            hint="消费相关量化目标"),

    # ---- 部门「十五五」专项规划：主题语义 ----
    DocSpec("国务院关于印发《国民健康“十五五”规划》的通知", ["国民健康"], "主题语义", 2,
            hint="医疗卫生体系建设、健康服务方面的部署"),
    DocSpec("国务院关于《扩大消费“十五五”规划》的批复", ["扩大消费"], "主题语义", 2,
            hint="促进消费的举措"),
    DocSpec("国务院关于《特殊教育发展提升“十五五”行动计划》的批复", ["特殊教育"], "主题语义", 2,
            hint="特殊教育发展的举措与保障"),
    DocSpec("国务院关于《中医药振兴发展“十五五”规划》的批复", ["中医药振兴"], "主题语义", 2,
            hint="中医药传承创新发展的举措"),

    # ---- 五年规划互相区分（形近标题、正文雷同）----
    DocSpec("中华人民共和国国民经济和社会发展第十五个五年规划纲要", ["第十五个五年规划"], "五年规划区分", 2,
            hint="问「十五五」的总体部署，题目里要出现「十五五」"),
    DocSpec("国民经济和社会发展第十二个五年规划纲要", ["第十二个五年规划"], "五年规划区分", 3,
            hint="问「十二五」的内容，题目里要出现「十二五」"),
    DocSpec("中华人民共和国国民经济和社会发展第十三个五年规划纲要", ["第十三个五年规划"], "五年规划区分", 2,
            hint="问「十三五」的内容，题目里要出现「十三五」"),
    DocSpec("中华人民共和国国民经济和社会发展第十一个五年规划纲要", ["第十一个五年规划"], "五年规划区分", 2,
            hint="问「十一五」的内容，题目里要出现「十一五」"),
    DocSpec("中华人民共和国国民经济和社会发展第十个五年计划纲要", ["第十个五年计划"], "五年规划区分", 1,
            hint="问「十五」计划的内容，题目里要出现「十五计划」或「十五」"),

    # ---- 相似文本：同一主题下多份文档互相干扰 ----
    DocSpec("国务院关于印发《国民健康“十五五”规划》的通知", ["国民健康"], "相似文本", 2,
            hint="问题要围绕「国民健康」这一专项规划，但措辞容易与十五五规划纲要混淆"),
    DocSpec("国务院关于《扩大消费“十五五”规划》的批复", ["扩大消费"], "相似文本", 2,
            hint="围绕「扩大消费」专项规划的措辞"),
    DocSpec("国务院关于《特殊教育发展提升“十五五”行动计划》的批复", ["特殊教育"], "相似文本", 2,
            hint="围绕「特殊教育」专项计划的措辞"),
    DocSpec("国务院关于《中医药振兴发展“十五五”规划》的批复", ["中医药振兴"], "相似文本", 2,
            hint="围绕「中医药振兴」专项规划的措辞"),
    DocSpec("国务院关于印发《知识产权保护和运用“十五五”规划》的通知", ["知识产权保护和运用"], "相似文本", 2,
            hint="围绕「知识产权」专项规划的措辞"),

    # ---- 政府信息公开系列（同一主题下十几份文件，考细分主题区分）----
    DocSpec("国务院办公厅关于印发《公共企事业单位信息公开规定制定办法》", ["公共企事业单位"], "政府信息公开", 2,
            hint="公共企事业单位信息公开规定的制定要求"),
    DocSpec("国务院办公厅政府信息与政务公开办公室关于政府信息公开处理决定送达问题的解释", ["送达"], "政府信息公开", 2,
            hint="处理决定送达的方式与要求"),
    DocSpec("国务院办公厅政府信息与政务公开办公室关于政府信息公开年度报告有关项目填报问题的解释", ["填报"], "政府信息公开", 2,
            hint="年度报告填报口径"),
    DocSpec("国务院办公厅政府信息与政务公开办公室关于政府信息公开申请接收渠道问题的解释", ["接收渠道"], "政府信息公开", 2,
            hint="申请接收渠道的规定"),
    DocSpec("国务院办公厅政府信息与政务公开办公室关于政府信息公开申请答复主体有关问题的解释", ["答复主体"], "政府信息公开", 2,
            hint="谁是有权答复主体"),
    DocSpec("国务院办公厅政府信息与政务公开办公室关于明确政府信息公开与业务查询事项界限的解释", ["业务查询"], "政府信息公开", 2,
            hint="信息公开与业务查询的界限"),
    DocSpec("国务院办公厅政府信息与政务公开办公室关于机构改革后政府信息公开申请办理问题的解释", ["机构改革"], "政府信息公开", 2,
            hint="机构改革后申请如何办理"),
    DocSpec("国务院办公厅政府信息与政务公开办公室关于规范政府信息公开平台有关事项的通知", ["公开平台"], "政府信息公开", 2,
            hint="公开平台规范化要求"),

    # ---- 年度报告：跨年份区分（同单位不同年份，正文高度雷同）----
    DocSpec("国家公务员局2019年政府信息公开工作年度报告", ["国家公务员局2019"], "年份区分", 2,
            expected_year=2019, hint="2019 年该局公开工作的具体情况"),
    DocSpec("国家公务员局2022年政府信息公开工作年度报告", ["国家公务员局2022"], "年份区分", 2,
            expected_year=2022, hint="2022 年该局公开工作的具体情况"),
    DocSpec("国家公务员局2025年政府信息公开工作年度报告", ["国家公务员局2025"], "年份区分", 2,
            expected_year=2025, hint="2025 年该局公开工作的具体情况"),
    DocSpec("国家新闻出版署（国家版权局）2019年政府信息公开工作年度报告", ["国家新闻出版署"], "年份区分", 2,
            expected_year=2019, hint="2019 年新闻出版署公开工作情况"),
    DocSpec("国家电影局2019年政府信息公开工作年度报告", ["国家电影局"], "年份区分", 2,
            expected_year=2019, hint="2019 年国家电影局公开工作情况"),
]

# 无答案题：语料里根本没有的主题，考察检索是否会硬凑结果
UNANSWERABLE: list[tuple[str, str]] = [
    ("公司年会的抽奖规则是怎么规定的？", "年会抽奖"),
    ("员工食堂的午餐补贴标准是多少？", "食堂补贴"),
    ("公司内部转岗的审批流程是什么？", "内部转岗"),
    ("差旅费报销的发票要求有哪些？", "差旅报销"),
    ("年假未休完能否折算成工资？", "年假折算"),
]

GEN_PROMPT = """你是企业知识库检索评测的出题专家。下面是摘自《{doc}》的若干段落。

{extra}请为**每个段落各出 1 道**中文问题，要求：
- 问题必须能、且只能从对应段落找到答案（不要在问题里透露答案）
- 像真实用户提问，不要出现"第几段""上文""本文档"这类元信息
- 提到政策名称时用原文的简称（如"十五五规划""全民健身计划"）
- 只输出 JSON 数组，不要 markdown 代码块，格式：[{{"i": 0, "q": "问题"}}]

段落：
{passages}
"""


def _load_corpus() -> dict[str, str]:
    """读取 eval/data 下所有 txt，返回 {文件名: 正文}。"""
    corpus = {}
    for name in sorted(os.listdir(DATA_DIR)):
        if not name.endswith(".txt"):
            continue
        with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
            corpus[name] = f.read()
    return corpus


def _build_idf(corpus: dict[str, str]) -> dict[str, float]:
    """用现有 BM25 分词统计 IDF，用于挑「有区分度」的句子。"""
    import math
    from collections import Counter

    df: Counter = Counter()
    for text in corpus.values():
        df.update(set(tokenize(text)))
    n = len(corpus)
    return {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"([。！？；])", r"\1\n", text)
    return [s.strip() for s in text.split("\n") if s.strip()]


def _pick_passages(
    text: str, idf: dict[str, float], k: int, require_digit: bool = False
) -> list[tuple[int, str]]:
    """挑稀有词密度最高的 k 个句子，返回 [(原句序, 句子)]。

    require_digit: 数字类出题只从含量化指标的段落里选，
    避免 LLM 把"要续写哪两大奇迹"这种非数字句也标成"数字精确"。
    """
    import statistics

    scored: list[tuple[float, int, str]] = []
    for idx, sent in enumerate(_split_sentences(text)):
        if len(sent) < MIN_PASSAGE_LEN:
            continue
        # 跳过目录行（"第三章 xxx"这类没有句末标点）
        if not sent.endswith(("。", "！", "？")):
            continue
        if require_digit and not re.search(r"\d", sent):
            continue
        toks = tokenize(sent)
        if not toks:
            continue
        mean_idf = statistics.mean(idf.get(t, 0.0) for t in toks)
        scored.append((mean_idf, idx, sent))

    scored.sort(key=lambda x: x[0], reverse=True)

    # 分散取：按原句序拉开距离，避免选到连续三句导致出题雷同
    picked: list[tuple[int, str]] = []
    for _, idx, sent in scored:
        if len(picked) >= k:
            break
        if all(abs(idx - kept_idx) > 3 for kept_idx, _ in picked):
            picked.append((idx, sent))
    picked.sort()
    return picked


def _is_grounded(question: str, passage: str, min_overlap: float = 0.25) -> bool:
    """校验问题确实是在问这个段落（题干与段落的 bigram 重合度）。

    挡住 LLM 偶尔跑偏生成的、与源段落无关的问题。
    """
    q_toks = set(tokenize(question))
    p_toks = set(tokenize(passage))
    if not q_toks:
        return False
    return len(q_toks & p_toks) / len(q_toks) >= min_overlap


def _similar_to_existing(question: str, existing: list[str], threshold: float = 0.75) -> bool:
    """与已有题目高度相似则视为重复（按题干 bigram Jaccard）。"""
    q = set(tokenize(question))
    if not q:
        return True
    for prev in existing:
        p = set(tokenize(prev))
        if not p:
            continue
        if len(q & p) / len(q | p) >= threshold:
            return True
    return False


def _match_doc(corpus: dict[str, str], key: str) -> str | None:
    """按前缀唯一匹配文件名。"""
    hits = [name for name in corpus if name.startswith(key)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        return None
    # 多个命中时取最短（前缀匹配到多个说明 key 不够独特）
    return sorted(hits, key=len)[0]


async def _gen_for_doc(client: AsyncOpenAI, model: str, spec: DocSpec, doc_name: str,
                       text: str, idf: dict[str, float]) -> list[dict]:
    """对一份文档出题，返回经校验的 [{type, query, gold_keywords, expected_year}]。

    三道校验闸（不合格的题直接丢弃，不将就）：
        1. 段落序号合法 —— 挡住 LLM 编造段落号
        2. 题干与源段落 bigram 重合度达标 —— 挡住与源文无关的跑偏问题
        3. 数字类题型只从含数字的段落出题 —— 挡住"XX是多少"式的伪数字题
    """
    # 数字类题型（数字精确 / 年份区分）只从含量化指标的段落出题
    require_digit = spec.type in ("数字精确", "年份区分")
    passages = _pick_passages(text, idf, PASSAGES_PER_DOC, require_digit=require_digit)
    if not passages:
        print(f"  [跳过] 没选出可用段落：{doc_name}")
        return []

    extra = f"侧重：{spec.hint}\n" if spec.hint else ""
    if require_digit:
        extra += "注意：本组问题必须是**数字类**，答案是一个具体数字/比例/指标，题干里要能看出在问数量。\n"
    extra = extra + "\n" if extra else ""

    numbered = "\n".join(f"[{i}] {p}" for i, (_, p) in enumerate(passages))
    prompt = GEN_PROMPT.format(doc=doc_name.split("_")[0], extra=extra, passages=numbered)

    resp = await client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}], temperature=0.7,
    )
    raw = (resp.choices[0].message.content or "").strip()
    m = re.search(r"\[.*\]", raw, re.S)
    if m:
        raw = m.group(0)
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        print(f"  [解析失败] {doc_name}")
        return []

    out: list[dict] = []
    dropped = 0
    for it in items:
        if len(out) >= spec.n:
            break
        q = str(it.get("q", "")).strip()
        try:
            i = int(it.get("i"))
        except (TypeError, ValueError):
            dropped += 1
            continue
        if not q or len(q) < 8 or not (0 <= i < len(passages)):
            dropped += 1
            continue
        passage = passages[i][1]
        # 数字类：题干要真的在问数量
        if require_digit and not re.search(r"(多少|几|达到|超过|比例|目标|以上|以下|增长)", q):
            dropped += 1
            continue
        if not _is_grounded(q, passage):
            dropped += 1
            continue
        out.append({
            "type": spec.type,
            "query": q,
            "gold_keywords": spec.gold,
            "expected_year": spec.expected_year,
        })
    if dropped:
        print(f"      (校验丢弃 {dropped} 题)")
    return out


async def amain() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="写入 qa_pairs.json（默认只打印）")
    parser.add_argument("--preview", type=int, default=15, help="预览多少条新题")
    args = parser.parse_args()

    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url,
                         timeout=settings.llm_timeout_sec)
    corpus = _load_corpus()
    idf = _build_idf(corpus)
    print(f"语料 {len(corpus)} 份，开始出题...\n")

    with open(QA_FILE, encoding="utf-8") as f:
        existing = json.load(f)

    generated: list[dict] = []
    for spec in DOC_SPECS:
        doc_name = _match_doc(corpus, spec.key)
        if doc_name is None:
            print(f"  [未匹配到文档] {spec.key}")
            continue
        items = await _gen_for_doc(client, settings.llm_model, spec, doc_name, corpus[doc_name], idf)
        generated.extend(items)
        print(f"  +{len(items):<2} [{spec.type}] {doc_name[:38]}")

    for q, _topic in UNANSWERABLE:
        generated.append({"type": "无答案", "query": q, "gold_keywords": [], "expected_year": None})

    # 去重：题干完全相同的、或与已有题/已选题高度相似的都丢弃
    # （相似判定用 bigram Jaccard，挡住"十四五脱贫人数"vs"十三五脱贫人数"这种换皮重复）
    kept_texts = [e["query"] for e in existing]
    deduped: list[dict] = []
    dup = 0
    for item in generated:
        if _similar_to_existing(item["query"], kept_texts):
            dup += 1
            continue
        deduped.append(item)
        kept_texts.append(item["query"])

    print(f"\n新生成 {len(deduped)} 题（含无答案 {len(UNANSWERABLE)} 题），因重复丢弃 {dup} 题")

    merged = existing + deduped
    print(f"合并后总题量：{len(existing)} → {len(merged)}")

    from collections import Counter
    print("题型分布：")
    for t, c in Counter(x["type"] for x in merged).most_common():
        print(f"  {t:<14} {c}")

    if not args.write:
        print("\n[dry-run] 未写入。加 --write 才会更新 qa_pairs.json")
        print(f"\n--- 新题预览（前 {args.preview} 条）---")
        for x in deduped[: args.preview]:
            print(f"  [{x['type']:<8}] {x['query']}")
        return 0

    with open(QA_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"\n已写入 {os.path.relpath(QA_FILE, PROJECT_ROOT)}")
    return 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
