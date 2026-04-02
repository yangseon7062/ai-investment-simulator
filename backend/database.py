"""
PostgreSQL (Neon) 연결 — asyncpg 기반
- 커넥션 풀 싱글톤
- fetchone / fetchall / execute / executemany 헬퍼
- 플레이스홀더: $1, $2, ... (PostgreSQL 방식)
"""

import asyncpg
from contextlib import asynccontextmanager
from backend.config import DATABASE_URL

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,
            max_size=10,
            ssl="require",           # Neon은 SSL 필수
        )
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def get_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def fetchone(query: str, params: tuple = ()):
    async with get_db() as conn:
        row = await conn.fetchrow(query, *params)
        return dict(row) if row else None


async def fetchall(query: str, params: tuple = ()):
    async with get_db() as conn:
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]


async def execute(query: str, params: tuple = ()):
    async with get_db() as conn:
        await conn.execute(query, *params)


async def executemany(query: str, params_list: list):
    async with get_db() as conn:
        await conn.executemany(query, params_list)


async def fetchval(query: str, params: tuple = ()):
    async with get_db() as conn:
        return await conn.fetchval(query, *params)
