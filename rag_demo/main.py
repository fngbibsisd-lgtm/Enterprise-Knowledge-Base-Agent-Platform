"""
主入口 —— 串联整个 RAG 流程。

流程：
    1. 加载文档 (document.py)
    2. 切片 (document.py)
    3. Embedding + 建索引 (vector_store.py)
    4. 用户提问 → 检索 → LLM 生成回答 (vector_store.py + llm.py)

用法：
    python main.py index          # 第一步：建索引
    python main.py ask "你的问题"  # 第二步：问答
"""

import sys
from config import Config
from document import load_documents, chunk_documents
from vector_store import embed_texts, build_and_save_index, load_index, search
from llm import generate_answer


def cmd_index(config: Config):
    """建索引命令：读取文档 → 切片 → Embedding → 存入 FAISS"""
    print("[1/4] 加载文档...")
    docs=load_documents(config.data_dir)
    if not docs:
        print("加载文档出现错误")
        return
    print("[2/4] 文本切片...")
    chunks=chunk_documents(docs, config.chunk_size,config.chunk_overlap)
    print("共切出 {} 个片段".format(len(chunks)))
    print("[3/4] 向量化...")
    texts=[c.text for c in chunks]
    vectors=embed_texts(texts,config)
    print(f"共生成{len(vectors)}个向量")

    print("[4/4] 构建 FAISS 索引...")
    build_and_save_index(vectors, chunks, config)
    print("索引构建完成！")


def cmd_ask(config: Config, query: str):
    """问答命令：加载索引 → 检索 → 生成回答"""
    print(f"问题: {query}\n")

    index,chunks=load_index(config)
    if not index:
        print("索引加载失败，请先运行 python main.py index 构建索引")
        return
    result=search(query,index,chunks,config)
    if not result:
        print("未找到相关内容")
        return
    print(f"找到{len(result)}条相关内容，正在生成回答...\n")
    for i,(doc,score) in enumerate(result,1):
        source=doc.metadata.get("source","?")
        preview=doc.text[:100].replace("\n", " ")
        print(f"  [{i}]  {source} (相关度:{score:.3f})")
        print(f"  [{i}]  {preview}\n")
    answer=generate_answer(query,result,config)
    print(f"回答: {answer}")


def main():
    config = Config()

    if len(sys.argv) < 2:
        print("用法:")
        print("  python main.py index          构建索引")
        print("  python main.py ask <问题>     问答")
        return

    command = sys.argv[1]

    if command == "index":
        cmd_index(config)
    elif command == "ask":
        query = " ".join(sys.argv[2:])
        if not query:
            print("请输入问题，例如: python main.py ask 报销流程是什么？")
            return
        cmd_ask(config, query)
    else:
        print(f"未知命令: {command}")


if __name__ == "__main__":
    main()
