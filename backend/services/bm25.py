"""
BM25 关键词检索器（零依赖，字符 bigram 分词）

为什么用 bigram 而不是 jieba：
    本项目的检索难点是「十四五 / 15五五 / 十三五」这类形近词区分，
    以及「知识产权」这类精确关键词命中。字符 bigram（相邻两字成组）已能
    精确区分这些词，且不引入额外依赖。

BM25 公式：
    score(d, q) = Σ_t  idf(t) * (tf * (k1+1)) / (tf + k1 * (1 - b + b*|d|/avgdl))
"""
import math
import re
from collections import Counter, defaultdict


def tokenize(text: str) -> list[str]:
    """字符 bigram 分词：连续数字/字母整体成 token，其余相邻两字成组。"""
    tokens: list[str] = []
    tokens.extend(re.findall(r"\d+", text))                    # 数字串整体
    tokens.extend(w.lower() for w in re.findall(r"[A-Za-z]+", text))  # 字母串整体
    rest = re.sub(r"[0-9A-Za-z]+", "", text)                    # 去掉数字字母
    for i in range(len(rest) - 1):
        tokens.append(rest[i:i + 2])                            # 中文 bigram
    return tokens


class BM25Index:
    """轻量 BM25 倒排索引。"""

    def __init__(self, corpus: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.n = len(corpus)
        self.doc_len: list[int] = []
        self.doc_tf: list[dict[str, int]] = []   # 每文档 token -> tf
        self.posting: dict[str, list[tuple[int, int]]] = defaultdict(list)  # token -> [(doc_idx, tf)]
        self.df: dict[str, int] = {}
        self.idf: dict[str, float] = {}
        self.avgdl: float = 0.0

        for i, text in enumerate(corpus):
            tf = Counter(tokenize(text))
            self.doc_tf.append(dict(tf))
            self.doc_len.append(sum(tf.values()))
            for t, c in tf.items():
                self.posting[t].append((i, c))
                self.df[t] = self.df.get(t, 0) + 1

        if self.n:
            self.avgdl = sum(self.doc_len) / self.n
        for t, df in self.df.items():
            self.idf[t] = math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def search(self, query: str, k: int = 50) -> list[tuple[int, float]]:
        """返回 [(doc_idx, score)]，按分数降序。"""
        scores: list[float] = [0.0] * self.n
        for t in set(tokenize(query)):
            idf = self.idf.get(t)
            if idf is None:
                continue
            for doc_idx, tf in self.posting.get(t, []):
                denom = tf + self.k1 * (1 - self.b + self.b * self.doc_len[doc_idx] / self.avgdl)
                scores[doc_idx] += idf * (tf * (self.k1 + 1)) / denom
        ranked = sorted(((i, s) for i, s in enumerate(scores) if s > 0),
                        key=lambda x: x[1], reverse=True)
        return ranked[:k]


def rrf_fuse(vector_ranked: list[int], bm25_ranked: list[int], k: int = 60) -> list[int]:
    """
    Reciprocal Rank Fusion：融合两个检索器的排名，返回重排后的 doc_idx 列表。

    Args:
        vector_ranked: 向量检索返回的 doc_idx（按相关性降序）
        bm25_ranked:   BM25 返回的 doc_idx（按相关性降序）
        k:             RRF 常数，默认 60

    Returns:
        list[int]: 融合后的 doc_idx（按融合分降序）
    """
    score: dict[int, float] = defaultdict(float)
    for rank, idx in enumerate(vector_ranked):
        score[idx] += 1.0 / (k + rank + 1)
    for rank, idx in enumerate(bm25_ranked):
        score[idx] += 1.0 / (k + rank + 1)
    return [idx for idx, _ in sorted(score.items(), key=lambda x: x[1], reverse=True)]
