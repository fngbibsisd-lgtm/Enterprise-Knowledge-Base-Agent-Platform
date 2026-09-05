"""
聊天记录 CRUD：save_chat 插入一条记录，get_history 查询最近 N 条。
"""
import json

from backend.database.connection import get_connection

def save_chat(config, query, answer, sources):
    """
    Args:
        config:配置对象,包含db_path
        query: 用户的查询
        answer: AI的回复
        sources: 源数据列表

    Returns:
        新插入记录的id
    """
    sources = sources or []
    source_json=json.dumps(sources, ensure_ascii=False)
    with get_connection(config) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO chat_history (query, answer, sources)
            VALUES (%s, %s, %s)
            """,
            (query, answer, source_json)
        )
        return cursor.lastrowid


def get_history(config, limit=20):
    """
    Args:
        config: 配置对象
        limit: 查询记录数量

    Returns:
        聊天记录列表,每条包含 query / answer / sources / created_at
    """
    with get_connection(config) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT query, answer, sources, created_at
            FROM chat_history
            ORDER BY created_at DESC
            LIMIT %s
            """
            , (limit,)
        )
        rows = cursor.fetchall()
        result=[]
        for row in rows:
            item=row   # DictCursor 下 row 已是 dict
            try:
                item["sources"]=json.loads(item["sources"] or "[]")
            except(json.JSONDecodeError, TypeError):
                item["sources"]=[]
            result.append(item)
        return result