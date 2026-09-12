"""
工具：sql_query / list_tables —— Agent 调用它们查询结构化数据（MySQL）。

sql_query 返回格式：{"success": bool, "rows": [...], "row_count": int, "error": str}
list_tables 返回格式：{"tables": {table: [{column, type}]}, "table_count": int}

安全限制（sql_query）：
    - 仅允许单条 SELECT 语句
    - 黑名单拦截（INTO OUTFILE / LOAD_FILE / SLEEP / BENCHMARK / INFORMATION_SCHEMA 等）
    - 无 LIMIT 时自动补 LIMIT 并硬上限行数
    - asyncio.wait_for 超时保护
"""
import asyncio
import re

from sqlalchemy import text

from backend.core.config import get_settings
from backend.db.session import AsyncSessionLocal

_FORBIDDEN = re.compile(
    r"\b(INTO|LOAD_FILE|SLEEP|BENCHMARK|INFORMATION_SCHEMA|OUTFILE|DUMPFILE)\b",
    re.IGNORECASE,
)


async def sql_query_fn(sql: str) -> dict:
    """执行 SQL 查询（仅限单条 SELECT），带 LIMIT/行数/超时防护，返回 dict。"""
    settings = get_settings()
    stmt = (sql or "").strip()
    if not stmt.upper().startswith("SELECT"):
        return {"success": False, "rows": [], "row_count": 0, "error": "仅允许SELECT查询"}
    if re.search(r";\s*\S", stmt):
        return {"success": False, "rows": [], "row_count": 0, "error": "仅允许单条SELECT语句"}
    if _FORBIDDEN.search(stmt):
        return {"success": False, "rows": [], "row_count": 0, "error": "SQL包含被禁止的关键字"}

    # 无 LIMIT 时自动补上限，防止全表扫描 / 结果爆上下文
    if "LIMIT" not in stmt.upper():
        stmt = f"{stmt} LIMIT {settings.agent_sql_max_rows}"

    async def _execute() -> dict:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text(stmt))
            rows = [dict(r) for r in result.mappings().all()]
        rows = rows[: settings.agent_sql_max_rows]  # 硬上限兜底
        return {"success": True, "rows": rows, "row_count": len(rows), "error": ""}

    try:
        return await asyncio.wait_for(_execute(), timeout=settings.agent_sql_timeout_sec)
    except asyncio.TimeoutError:
        return {"success": False, "rows": [], "row_count": 0, "error": "查询超时"}
    except Exception as e:
        return {"success": False, "rows": [], "row_count": 0, "error": str(e)}


async def list_tables_fn() -> dict:
    """自省当前库的表与字段，供 LLM 在写 SQL 前了解结构（替代 prompt 里硬编码 schema）。"""
    settings = get_settings()
    sql = text(
        """
        SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = :db
        ORDER BY TABLE_NAME, ORDINAL_POSITION
        """
    )
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(sql, {"db": settings.mysql_database})).mappings().all()
    tables: dict[str, list[dict]] = {}
    for r in rows:
        tables.setdefault(r["TABLE_NAME"], []).append(
            {"column": r["COLUMN_NAME"], "type": r["DATA_TYPE"]}
        )
    return {"tables": tables, "table_count": len(tables)}
