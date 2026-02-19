import os
from contextlib import asynccontextmanager
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL não configurada. Configure sua URL do Postgres/Neon para usar psycopg_pool."
    )

# Para Neon, garanta sslmode=require na URL (se ainda não tiver)
if DATABASE_URL.startswith(("postgres://", "postgresql://")) and "sslmode=" not in DATABASE_URL:
    sep = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL = f"{DATABASE_URL}{sep}sslmode=require"

pool = AsyncConnectionPool(
    conninfo=DATABASE_URL,
    min_size=1,
    max_size=10,
    kwargs={"autocommit": False},  # controle explícito de transação
)

async def health_check() -> bool:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1")
            _ = await cur.fetchone()
    return True

@asynccontextmanager
async def get_db():
    """
    Uso em endpoints FastAPI:

        from fastapi import Depends

        @app.get("/algo")
        async def algo(conn = Depends(get_db)):
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT id, name FROM products LIMIT 5")
                rows = await cur.fetchall()
                return {"items": rows}
    """
    async with pool.connection() as conn:
        try:
            yield conn
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise