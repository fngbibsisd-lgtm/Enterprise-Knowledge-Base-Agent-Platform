"""
文档处理模块 —— PDF/TXT 文本提取 + 按句切片（固定长度 + overlap）。
"""
import os
import re
from dataclasses import dataclass


@dataclass
class Document:
    """一个文档单元。"""
    text: str
    metadata: dict  # 例如 {"source": "xxx.pdf"}


def extract_text_from_pdf(filepath: str) -> str:
    from PyPDF2 import PdfReader

    reader = PdfReader(filepath)
    parts = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            parts.append(page_text)
    return "\n".join(parts)


def extract_text_from_file(filepath: str) -> str:
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def load_documents(path: str) -> list[Document]:
    """读取文件或目录下所有 .pdf/.txt，返回 Document 列表。"""
    docs: list[Document] = []
    if os.path.isfile(path):
        files = [path]
    elif os.path.isdir(path):
        files = [os.path.join(path, f) for f in os.listdir(path)]
    else:
        return docs

    for filepath in files:
        if not os.path.isfile(filepath):
            continue
        filename = os.path.basename(filepath)
        if filename.endswith(".pdf"):
            text = extract_text_from_pdf(filepath)
        elif filename.endswith(".txt"):
            text = extract_text_from_file(filepath)
        else:
            continue
        if not text.strip():
            continue
        docs.append(Document(text=text, metadata={"source": filename}))
    return docs


def _split_by_sentences(text: str) -> list[str]:
    text = re.sub(r"([。！？；\n])", r"\1\n", text)
    return [s.strip() for s in text.split("\n") if s.strip()]


def _make_chunk(sentences: list[str], metadata: dict, idx: int) -> Document:
    return Document(text="".join(sentences), metadata={**metadata, "chunk_index": idx})


def chunk_documents(
    docs: list[Document],
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> list[Document]:
    """把长文档切成小块（按句拼接，相邻 chunk 带 overlap）。"""
    chunks: list[Document] = []
    for doc in docs:
        sentences = _split_by_sentences(doc.text)
        if not sentences:
            continue
        current_chunk: list[str] = []
        current_length = 0
        for s in sentences:
            sent_len = len(s)
            if sent_len > chunk_size:
                if current_chunk:
                    chunks.append(_make_chunk(current_chunk, doc.metadata, len(chunks)))
                chunks.append(_make_chunk([s], doc.metadata, len(chunks)))
                current_chunk = []
                current_length = 0
                continue
            if current_length + sent_len > chunk_size:
                chunks.append(_make_chunk(current_chunk, doc.metadata, len(chunks)))
                overlap_sentences = []
                overlap_len = 0
                for ps in reversed(current_chunk):
                    if overlap_len + len(ps) > chunk_overlap:
                        break
                    overlap_sentences.insert(0, ps)
                    overlap_len += len(ps)
                current_chunk = overlap_sentences + [s]
                current_length = overlap_len + sent_len
            else:
                current_chunk.append(s)
                current_length += sent_len
        if current_chunk:
            chunks.append(_make_chunk(current_chunk, doc.metadata, len(chunks)))
    return chunks
