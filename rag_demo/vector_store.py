"""
向量存储模块

职责：
    1. 调用 Embedding 模型把文本转成向量
    2. 写入 FAISS 索引
    3. 根据 query 检索最相关的 top_k 个 chunk

核心函数（你需要实现）：
    - build_index(chunks, config) -> FAISS index
    - search(query, index, config) -> list[tuple[str, float]]

提示：
    - OpenAI 的 embedding API：openai.embeddings.create(model="text-embedding-3-small", input=[text])
    - FAISS: faiss.IndexFlatIP (内积) 或 IndexFlatL2 (欧氏距离)
    - 也可以用 LlamaIndex 的 VectorStoreIndex，一行代码搞定
"""

import pickle
import faiss
import numpy as np
from openai import OpenAI
from config import Config
from document import Document


def create_embedding_client(config:Config) -> OpenAI:
    return OpenAI(
        api_key=config.embedding_api_key or config.llm_api_key,
        base_url=config.embedding_base_url or config.llm_base_url,
    )

def embed_texts(texts: list[str], config: Config) -> list[list[float]]:
    """
    把文本列表转成向量列表。

    Args:
        texts: 文本列表，每个元素是一个 chunk 的文本
        config: 配置对象

    Returns:
        list[list[float]]: 每个文本对应的向量（维度取决于模型）

    你需要实现：
        1. 调用 Embedding API
        2. 处理 batch（一次 API 调用可能有文本数量限制）
    """
    client=create_embedding_client(config)
    vectors=[]
    batch_size=20
    for i in range(0,len(texts),batch_size):
        batch=texts[i:i+batch_size]
        resp=client.embeddings.create(
            model=config.embedding_model,
            input=batch,
        )
        vectors.extend([d.embedding for d in resp.data])
    return vectors


def build_and_save_index(vectors: list[list[float]],chunks: list[Document],config: Config,):
    """
    用向量列表构建 FAISS 索引。

    Args:
        vectors: embed_texts 的返回值

    Returns:
        faiss.Index: 构建好的 FAISS 索引对象

    你需要实现：
        1. 确定向量维度 dim = len(vectors[0])
        2. 创建 faiss.IndexFlatIP(dim)   # 内积相似度
        3. 把向量转成 numpy array，add 进去
    """
    dim=len(vectors[0])
    index=faiss.IndexFlatIP(dim)
    vecs_np=np.array(vectors).astype("float32")
    faiss.normalize_L2(vecs_np)
    index.add(vecs_np)
    print(f" 索引入库:{index.ntotal}条向量,维度={dim}")

    faiss.write_index(index,config.index_path)
    with open(config.chunks_path,"wb")as f:
        pickle.dump(chunks,f)
    print(f" 索引和 chunks 已保存到磁盘: {config.index_path}, {config.chunks_path}")



def load_index(config: Config) -> tuple:
    """
    从磁盘加载索引和 chunk 信息。

    Returns:
        (faiss.Index, list[Document])

    你需要实现：
        1. faiss.read_index(path)
        2. 反序列化 chunks
        3. 如果文件不存在，返回 (None, None)
    """
    try:
        index=faiss.read_index(config.index_path)
        with open(config.chunks_path,"rb")as f:
            chunks=pickle.load(f)
        print(f"   索引已加载:{index.ntotal}条向量")
        return index,chunks
    except FileNotFoundError:
        print("  未找到索引文件,请先运行:python main.py index")
        return None,None



def search(
    query: str,
    index: "faiss.Index",
    chunks: list[Document],
    config: Config,
) -> list[tuple[Document, float]]:
    """
    给定 query，检索最相关的 chunk。

    Args:
        query: 用户问题
        index: FAISS 索引
        chunks: 所有 chunk 的列表
        config: 配置（含 top_k）

    Returns:
        list[tuple[Document, float]]: 每个元素是 (chunk, 相似度分数)，按分数降序

    你需要实现：
        1. 把 query 向量化
        2. index.search(query_vector, k=top_k)
        3. 用返回的索引去 chunks 里取原文
    """
    vectors=embed_texts([query],config)
    query_vec=np.array(vectors[0]).astype("float32")
    query_vec=query_vec.reshape(1,-1)
    faiss.normalize_L2(query_vec)
    scores,indics=index.search(query_vec,config.top_k)
    result=[]
    for score,idx in zip(scores[0],indics[0]):
        if idx >= 0 and idx < len(chunks):
            result.append((chunks[idx],float(score)))
    return result


