# type: ignore
from typing import AsyncGenerator
from fastapi import Request
import asyncpg

async def get_db(request: Request) -> AsyncGenerator[asyncpg.Connection, None]:
    """Yields a database connection from the FastAPI app state pool."""
    async with request.app.state.db_pool.acquire() as connection:
        yield connection