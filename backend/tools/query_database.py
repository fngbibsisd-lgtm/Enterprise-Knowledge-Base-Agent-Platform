"""
工具：sql_query —— Agent 调用它查询数据库（chat_history / uploaded_files 表）。

返回格式：{"success": bool, "rows": [...], "row_count": int, "error": str}
安全限制：只允许 SELECT 语句。
"""
from sqlalchemy import text

from backend.db.session import AsyncSessionLocal


async def sql_query_fn(sql: str) -> dict:
    """执行 SQL 查询（仅限 SELECT），返回 dict。"""
    if not sql.strip().upper().startswith("SELECT"):
        return {"success": False, "rows": [], "row_count": 0, "error": "仅允许SELECT查询"}

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text(sql))
            rows = [dict(r) for r in result.mappings().all()]
            return {"success": True, "rows": rows, "row_count": len(rows), "error": ""}
    except Exception as e:
        return {"success": False, "rows": [], "row_count": 0, "error": str(e)}
