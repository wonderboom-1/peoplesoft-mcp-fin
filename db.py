"""
Database connection management for PeopleSoft Finance MCP.
Provides centralized query execution with async support and connection pooling.
"""
import asyncio
import os
from typing import Any

import oracledb
from dotenv import load_dotenv

load_dotenv()

_pool = None
_pool_lock = asyncio.Lock()


def get_connection_params() -> dict[str, str]:
    """Get database connection parameters from environment variables."""
    dsn = os.getenv("ORACLE_DSN")
    user = os.getenv("ORACLE_USER")
    password = os.getenv("ORACLE_PASSWORD")

    if not all([dsn, user, password]):
        raise ValueError(
            "Missing database credentials. Set ORACLE_DSN, ORACLE_USER, and ORACLE_PASSWORD environment variables."
        )

    return {"dsn": dsn, "user": user, "password": password}


async def _get_pool():
    """Lazily create and return an Oracle async connection pool (double-check locking)."""
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is not None:
            return _pool
        params = get_connection_params()
        _pool = oracledb.create_pool_async(
            user=params["user"],
            password=params["password"],
            dsn=params["dsn"],
            min=2,
            max=10,
        )
        return _pool


async def execute_query(
    sql: str,
    params: list[Any] | None = None,
    fetch_one: bool = False,
) -> dict:
    """
    Execute a SQL query and return results as a dictionary.
    """
    if params is None:
        params = []

    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(sql, params)

                if cursor.description is None:
                    return {"results": [], "message": "Query executed successfully (no results)"}

                columns = [col[0] for col in cursor.description]

                if fetch_one:
                    row = await cursor.fetchone()
                    if row:
                        return {"results": [dict(zip(columns, row))]}
                    return {"results": []}

                rows = await cursor.fetchall()
                return {"results": [dict(zip(columns, row)) for row in rows]}

    except oracledb.Error as e:
        return {"error": f"Database error: {str(e)}"}
    except ValueError as e:
        return {"error": str(e)}


async def execute_query_with_limit(
    sql: str,
    params: list[Any] | None = None,
    limit: int = 100,
) -> dict:
    """Execute a query with a row limit."""
    if params is None:
        params = []

    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(sql, params)

                if cursor.description is None:
                    return {"results": [], "truncated": False}

                columns = [col[0] for col in cursor.description]
                rows = await cursor.fetchmany(limit + 1)

                truncated = len(rows) > limit
                if truncated:
                    rows = rows[:limit]

                return {
                    "results": [dict(zip(columns, row)) for row in rows],
                    "truncated": truncated,
                    "row_count": len(rows),
                }

    except oracledb.Error as e:
        return {"error": f"Database error: {str(e)}"}
    except ValueError as e:
        return {"error": str(e)}
