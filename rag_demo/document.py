"""
文档处理模块

职责：
    1. 读取 PDF / Markdown / TXT 文件
    2. 把长文本切成适合 Embedding 的短片段 (chunk)

核心函数（你需要实现）：
    - load_documents(dir_path: str) -> list[Document]
    - chunk_documents(docs: list[Document], chunk_size: int, overlap: int) -> list[str]

提示：
    - 建议用 LlamaIndex 的 SimpleDirectoryReader 读文件
    - 建议用 LlamaIndex 的 SentenceSplitter 切文本
    - 如果不能装 LlamaIndex，可以先手写简单的按段落切分
"""

from dataclasses import dataclass
import re
import os

@dataclass
class Document:
    """一个文档单元"""
    text: str
    metadata: dict  # 例如 {"source": "员工报销制度.pdf", "page": 3}

def extract_text_from_pdf(filepath:str)->str:
    """
    从 PDF 提取纯文本。
    """
    from PyPDF2 import PdfReader
    reader=PdfReader(filepath)
    text_parts=[]
    for page in reader.pages:
        page_text=page.extract_text()
        if page_text:
            text_parts.append(page_text)
    return "\n".join(text_parts)


def load_documents(dir_path: str) -> list[Document]:
    """
    读取目录下所有支持的文件，返回 Document 列表。

    Args:
        dir_path: 文档所在目录路径，如 "./data"

    Returns:
        list[Document]: 每个元素是一份文档的完整文本 + 元数据

    你需要实现：
        1. 遍历 dir_path 下的 .pdf / .md / .txt 文件
        2. 读取文本内容（PDF 用 PyPDF2 或 pdfplumber，或直接用 LlamaIndex 的 reader）
        3. 包装成 Document 对象
    """
    docs=[]

    if os.path.isfile(dir_path):
        files=[dir_path]
    elif os.path.isdir(dir_path):
        files=[os.path.join(dir_path,f)for f in os.listdir(dir_path)]
    else:
        print(f"[错误]路径不存在:{dir_path}")
        return docs

    for filepath in files:
        if not os.path.isfile(filepath):
            continue
        filename=os.path.basename(filepath)

        if filename.endswith(".pdf"):
            text=extract_text_from_pdf(filepath)
        elif filename.endswith(".txt"):
            text=extract_text_from_text(filepath)
        else:
            print(f"[跳过]不支持的文件类型:{filepath}")
            continue
        if not text.strip():
            print(f"[跳过]文件内容为空:{filepath}")
        docs.append(Document(text=text, metadata={"source": filepath}))
        print(f"[完成]{filepath}读取完成,长度:{len(docs)}")
    return docs

def extract_text_from_text(data_dir: str) -> str:
    with open(data_dir,"r",encoding="utf-8")as f:
        return f.read()

def _split_by_sentences(text: str) -> list[str]:
    text=re.sub(r'([。！？；\n])', "\1\n", text)
    setences=[s.strip() for s in text.split("\n") if s.strip()]
    return setences

def _make_chunk(sentences: list[str], metadata: dict,idx:int) -> Document:
    return Document(
        text="".join(sentences),
        metadata={**metadata, "chunk_index": idx}
    )

def chunk_documents(
    docs: list[Document],
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> list[Document]:
    """
    把长文档切成小块。

    Args:
        docs: load_documents 的返回值
        chunk_size: 每个 chunk 的 token 数上限
        chunk_overlap: 相邻 chunk 重叠的 token 数

    Returns:
        list[Document]: 切好的 chunk，每个带原始来源信息

    你需要实现：
        1. 用 SentenceSplitter 或按句号/换行手写切分
        2. 每个 chunk 保留 metadata（来源文件、页码等）
    """
    chunks=[]
    for doc in docs:
        sentence=_split_by_sentences(doc.text)
        if not sentence:
            continue
        current_chunk=[]
        current_length=0
        for s in sentence:
            sent_len=len(s)
            if sent_len>chunk_size:
                if current_chunk:
                    chunks.append(_make_chunk(current_chunk,doc.metadata,len(chunks)))
                chunks.append(_make_chunk([s],doc.metadata,len(chunks)))
                current_chunk=[]
                current_length=0
                continue
            if current_length+sent_len>chunk_size:
                chunks.append(_make_chunk(current_chunk,doc.metadata,len(chunks)))
                overlap_sentences=[]
                overlap_len=0
                for ps in reversed(current_chunk):
                    if overlap_len+len(ps)>chunk_overlap:
                        break
                    overlap_sentences.insert(0,ps)
                    overlap_len+=len(ps)
                current_chunk=overlap_sentences+[s]
                current_length=overlap_len+sent_len
            else:
                current_chunk.append(s)
                current_length+=sent_len
        if current_chunk:
            chunks.append(_make_chunk(current_chunk,doc.metadata,len(chunks)))

    return chunks