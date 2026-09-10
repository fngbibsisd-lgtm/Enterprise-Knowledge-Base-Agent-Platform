"""
RAG 核心服务 —— 封装 V0.1 的 rag_demo 模块，提供索引构建 / 检索 / 重置 / 状态查询。

通过 sys.path 复用 ../rag_demo/ 下的 document.py、vector_store.py 模块。
"""

import sys
import os
import re
import pickle
import numpy as np
import faiss
from datetime import datetime,timedelta

from backend.database.connection import get_connection
from rag_demo.document import load_documents

RAG_DEMO_DIR=os.path.abspath(os.path.join(os.path.dirname(__file__),"..","..","rag_demo"))
if not os.path.isdir(RAG_DEMO_DIR):
    raise FileNotFoundError(f"找不到rag_demo的目录,请检查路径{RAG_DEMO_DIR}")
if RAG_DEMO_DIR not in sys.path:
    sys.path.append(RAG_DEMO_DIR)

from backend.config import Config
from rag_demo.document import chunk_documents
from rag_demo.vector_store import embed_texts
from backend.services.bm25 import BM25Index, rrf_fuse

# ========== 索引构建 ==========

def build_index_for_file(filepath: str, config: Config) -> int:
    """
    读取文件->切片->向量化->追加到 FAISS 索引
    Args:
        filepath: 要建立索引的文件路径
        config: 配置对象
    Returns:
        新增的 chunk 数量
    """
    #确认索引文件和切块路径
    index_path=(getattr(config,"index_path",None)
    or getattr(config,"faiss_index_path",os.path.join(config.data_dir,"faiss.index")))
    chunks_path=getattr(config,"chunks_path",os.path.join(config.data_dir,"chunks.pkl"))
    #确认目录存在
    os.makedirs(os.path.dirname(os.path.abspath(index_path)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(chunks_path)), exist_ok=True)
    #读取文档(load_document支持读取目录)
    docs=load_documents(filepath)
    if not docs:
        return 0
    #文档切片
    raw_chunks=chunk_documents(docs, config.chunk_size, config.chunk_overlap)
    if not raw_chunks:
        return 0
    #统一chunk格式
    chunks=[]
    for chunk in raw_chunks:
        if isinstance(chunk, dict):
            text=chunk.get("text")or chunk.get("content")or chunk.get("data")or ""
            source=chunk.get("source")or chunk.get("file")or"unknown"
            metadata=chunk.get("metadata") or {}
        elif hasattr(chunk, "text") and hasattr(chunk, "metadata"):
            text=chunk.text
            source=os.path.basename(filepath) if filepath else "unknown"
            metadata=chunk.metadata or {}
        else:
            text=str(chunk)
            source=os.path.basename(filepath) if filepath else "unknown"
            metadata={}
        text=text.strip()
        if text:
            # 把文件名注入 chunk 文本，让 embedding 能编码年份/来源信息，
            # 否则"2022"这种年份只在 source 字段里，向量检索分不清年份
            chunks.append({"text":f"【来源：{source}】{text}", "source":source, "metadata":metadata})
    if not chunks:
        return 0
    texts=[chunk["text"] for chunk in chunks]

    vectors=np.asarray(embed_texts(texts, config),dtype=np.float32)
    if vectors.size == 0:
        return 0
    faiss.normalize_L2(vectors)
    if os.path.exists(index_path) and os.path.exists(chunks_path):
        index=faiss.read_index(index_path)#读就索引
        with open(chunks_path,"rb") as f:
            existing_chunks=pickle.load(f)#读旧文本块
        if index.d!=vectors.shape[1]:
            raise ValueError("FAISS索引维度与新向量维度不匹配")
    else:
        index=faiss.IndexFlatIP(vectors.shape[1])
        existing_chunks=[]

    index.add(vectors)
    existing_chunks.extend(chunks)
    faiss.write_index(index, index_path)

    with open(chunks_path,"wb") as f:
        pickle.dump(existing_chunks, f)

    return len(chunks)


# ========== 检索 ==========

def search(query: str, config: Config) -> list[dict]:
    """
    向量化query->faiss索引->返回sources列表
    Args:
        query: 用户问题
        config: 配置对象

    Returns:
        检测到的资料列表,格式:
        {
            {
                "source": "..",
                "text",""
                "preview": "","
                "score": 0.85
            }
        }
    """
    index_path=(getattr(config,"index_path",None))
    chunks_path=(getattr(config,"chunks_path",None))
    if not os.path.exists(index_path) or not os.path.exists(chunks_path):
        return []
    #加载两项数据
    index=faiss.read_index(index_path)
    if index.ntotal==0:
        return []
    with open(chunks_path,"rb") as f:
        chunks=pickle.load(f)
    if not chunks:
        return []
    #将用户回答转化为向量
    query_vec=np.asarray(embed_texts([query], config),dtype=np.float32)

    if query_vec.size == 0:
        return []

    if query_vec.ndim==1:
        query_vec=query_vec.reshape(1,-1)
    faiss.normalize_L2(query_vec)
    # 年份过滤需在更大候选集上做：各年份公报正文雷同，正确年份常排不进 top_k
    years=re.findall(r'20\d{2}',query)
    search_k=index.ntotal if years else config.top_k

    # ---- 向量检索 ----
    scores,indic=index.search(query_vec, search_k)
    vector_ranked=[int(i) for i in indic[0] if 0<=i<len(chunks)]
    vector_scores={int(i):float(s) for s,i in zip(scores[0],indic[0]) if 0<=i<len(chunks)}

    # ---- BM25 关键词检索 ----
    corpus=[c.get("text","") if isinstance(c,dict) else str(c) for c in chunks]
    bm25=BM25Index(corpus)
    bm25_ranked=[idx for idx,_ in bm25.search(query,k=search_k)]

    # ---- RRF 融合（向量 + BM25） ----
    fused=rrf_fuse(vector_ranked,bm25_ranked)

    # ---- 按融合顺序构建结果（按文档去重，避免大文件多 chunk 霸榜） ----
    results=[]
    seen_sources=set()
    for idx in fused:
        chunk=chunks[idx]
        if isinstance(chunk, dict):
            text=chunk.get("text","")
            source=chunk.get("source","")
        else:
            text=str(chunk)
            source=""
        text=text.strip()
        if not text:
            continue
        if source in seen_sources:
            continue
        seen_sources.add(source)
        results.append({
            "source":source,
            "text":text,
            "preview":text[:100],
            "score":vector_scores.get(idx,0.0),
        })
    # 年份软排序：query 含年份时，把文件名含该年份的文档排到前面（不硬过滤，
    # 避免把「目标年份」如 2030/2035 误当文档年份而误伤「十五五」类规划文档）。
    # Python sort 稳定，含年份的文档内部仍保持 RRF 融合顺序。
    results=results[:config.top_k]
    if years:
        results.sort(key=lambda r: 0 if any(y in r.get("source","") for y in years) else 1)
    # 终端日志：显示最终检索结果
    print(f"\n[检索] query=\"{query[:50]}...\" 共 {len(results)} 条:")
    for i, r in enumerate(results, 1):
        print(f"  [{i}] score={r['score']:.4f}  {r['source']}")
    print()
    return results

# ========== 知识库重置 ==========

def reset_index(config: Config, hours: int | None) -> int:
    """
    重置 FAISS 索引和 chunks

    Args:
        config: 配置对象
        hours: 删除最近 N 小时内上传的，None 表示全部删除

    Returns:
        删除的 chunk 数量
    """
    index_path = getattr(config, "index_path", None)
    chunks_path = getattr(config, "chunks_path", None)

    if hours is None:
        total_chunks=get_index_status(config)["total_chunks"]
        if os.path.exists(index_path):
            os.remove(index_path)
        if os.path.exists(chunks_path):
            os.remove(chunks_path)
        return total_chunks

    if not os.path.exists(index_path) or not os.path.exists(chunks_path):
        return 0

    with open(chunks_path,"rb") as f:
        chunks=pickle.load(f)
    if not chunks:
        return 0
    deadline=datetime.now()-timedelta(hours=hours)
    with get_connection(config)as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            select filename from uploaded_files where created_at>%s
            """,(deadline.strftime("%Y-%m-%d %H:%M:%S"),)
        )
        rows = cursor.fetchall()
    recent_files={row["filename"] for row in rows}
    cur_chunks=[c for c in chunks if c["source"] not in recent_files]
    deleted_chunks=len(chunks)-len(cur_chunks)
    if deleted_chunks==0:
        return 0
    if not cur_chunks:
        # 全部 chunk 都被删除 → 直接删索引文件，等价于全删（避免用空向量重建索引报错）
        if os.path.exists(index_path):
            os.remove(index_path)
        if os.path.exists(chunks_path):
            os.remove(chunks_path)
        return deleted_chunks
    texts=[c["text"] for c in cur_chunks]
    vectors=np.asarray(embed_texts(texts,config),dtype=np.float32)
    faiss.normalize_L2(vectors)
    index=faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    faiss.write_index(index, index_path)
    with open(chunks_path,"wb") as f:
        pickle.dump(cur_chunks, f)
    return deleted_chunks




# ========== 状态查询 ==========

def get_index_status(config: Config) -> dict:
    """
    返回当前索引状态 {"indexed": bool, "total_chunks": int}
    Args:
        config: 配置对象
    Returns:
        索引状态字典:{"indexed": bool, "total_chunks": int}
    """
    index_path=(getattr(config,"index_path",None))
    chunks_path=(getattr(config,"chunks_path",None))
    if not os.path.exists(index_path) or not os.path.exists(chunks_path):
        return {
            "indexed": False,
            "total_chunks": 0,
        }
    try:
        with open(chunks_path,"rb") as f:
            chunks=pickle.load(f)
        total_chunks=len(chunks)
    except Exception:
        total_chunks=0
    return {
        "indexed": total_chunks>0,
        "total_chunks": total_chunks,
    }