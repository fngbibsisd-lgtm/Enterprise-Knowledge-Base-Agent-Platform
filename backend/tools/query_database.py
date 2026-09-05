"""
工具：sql_query — Agent 调用它查询数据库（chat_history / uploaded_files 表）。

返回格式：{"success": bool, "rows": [...], "row_count": int, "error": str}
安全限制：只允许 SELECT 语句。
"""
from backend.config import Config
from backend.database.connection import get_connection
def sql_query_fn(sql: str) -> dict:
    """
    执行 SQL 查询（仅限 SELECT），返回 {"success": bool, "rows": [...], "row_count": int, "error": str}。
    """
    if not sql.strip().upper().startswith("SELECT"):
        return {
            "success": False,
            "rows": [],
            "row_count": 0,
            "error":"仅允许SELECT查询"
        }
    config = Config()
    try:
        with get_connection(config) as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            result = list(rows)   # DictCursor 下 row 已是 dict
            return {
                "success": True,
                "rows": result,
                "row_count": len(result),
                "error":""
            }
    except Exception as e:
        return {
            "success": False,
            "rows": [],
            "row_count": 0,
            "error":str(e)
        }