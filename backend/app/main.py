# type ignore
import os
from contextlib import asynccontextmanager
from pathlib import Path

try:
    import asyncpg
except ModuleNotFoundError:
    asyncpg = None  # type: ignore[assignment]

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

try:
    from backend.routers import chat, tasks
except ModuleNotFoundError:
    from routers import chat, tasks

DATABASE_URL = os.environ.get("DATABASE_URL")
FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"


async def _ensure_schema(pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS Tasks (
                id UUID PRIMARY KEY,
                title TEXT NOT NULL,
                start_time TIMESTAMPTZ,
                end_time TIMESTAMPTZ,
                is_flexible BOOLEAN DEFAULT FALSE,
                done BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS HabitLogs (
                id UUID PRIMARY KEY,
                habit_id UUID NOT NULL,
                date DATE NOT NULL,
                completions INTEGER DEFAULT 0
            );
            ALTER TABLE Tasks
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
            ALTER TABLE Tasks
                ALTER COLUMN start_time DROP NOT NULL;
            '''
        )

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_pool = None

    if DATABASE_URL and asyncpg is not None:
        try:
            app.state.db_pool = await asyncpg.create_pool(DATABASE_URL)
            await _ensure_schema(app.state.db_pool)
            print("[Saidi] Database pool initialized.")
        except Exception as exc:
            print(f"[Saidi] Database initialization failed, continuing without DB: {exc}")
            if app.state.db_pool is not None:
                await app.state.db_pool.close()
                app.state.db_pool = None
    elif not DATABASE_URL:
        print("[Saidi] DATABASE_URL not set, running without database features.")
    else:
        print("[Saidi] asyncpg is not installed, running without database features.")

    try:
        yield
    finally:
        if app.state.db_pool is not None:
            await app.state.db_pool.close()

app = FastAPI(title="Saidi API", lifespan=lifespan)

app.include_router(chat.router)
app.include_router(tasks.router)

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
else:
    @app.get("/")
    def missing_frontend():
        return {"error": f"Frontend not found at {FRONTEND_DIR}. Run from repo root."}