
# type ignore
import os
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import asyncpg
from backend.auth import get_password_hash, verify_password, create_access_token, get_current_user_id

# Traverse from backend/app/main.py up to the root directory
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# This will now successfully read from your .env
DATABASE_URL = os.environ.get("DATABASE_URL")
FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"

try:
    import asyncpg # type: ignore
except ModuleNotFoundError:
    asyncpg = None  # type: ignore[assignment]

try:
    from backend.routers import chat, tasks
except ModuleNotFoundError:
    from routers import chat, tasks


async def _ensure_schema(pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                first_name TEXT,
                last_name TEXT
            );
            '''
        )
        await conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS tasks (
                id UUID PRIMARY KEY,
                title TEXT NOT NULL,
                start_time TIMESTAMPTZ,
                end_time TIMESTAMPTZ,
                is_flexible BOOLEAN DEFAULT FALSE,
                done BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                user_id UUID NOT NULL
            );
            '''
        )
        await conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS HabitLogs (
                id UUID PRIMARY KEY,
                habit_id UUID NOT NULL,
                date DATE NOT NULL,
                completions INTEGER DEFAULT 0,
                user_id UUID NOT NULL
            );
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

# Initialize FastAPI with lifespan for DB connection management
app = FastAPI(title="Saidi API", lifespan=lifespan)

# Add CORS middleware to allow frontend to communicate with backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://mysaidi-production.up.railway.app",
        "http://127.0.0.1:8000" # Dev container
    ],  # Allow all origins in development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(tasks.router)

class UserCreate(BaseModel):
    email: str
    password: str = Field(..., max_length=72)
    first_name: str | None = None
    last_name: str | None = None

@app.post("/register")
async def register(user: UserCreate):
    print(f"[DEBUG] Register endpoint hit for email: {user.email}")
    db_pool = getattr(app.state, "db_pool", None)
    if db_pool is None:
        raise HTTPException(status_code=500, detail="Database is not available. Registration is currently disabled.")
    
    hashed_pw = get_password_hash(user.password)
    try:
        async with db_pool.acquire() as conn:
            new_id = await conn.fetchval(
                "INSERT INTO users (email, password_hash, first_name, last_name) VALUES ($1, $2, $3, $4) RETURNING id",
                user.email, hashed_pw, user.first_name, user.last_name
            )
        return {"message": "User created", "user_id": str(new_id)}
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Email already registered")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")
    
@app.post("/login")
async def login(user: UserCreate):
    print(f"[DEBUG] Login endpoint hit for email: {user.email}")
    db_pool = getattr(app.state, "db_pool", None)
    if db_pool is None:
        raise HTTPException(status_code=500, detail="Database is not available. Login is currently disabled.")
    
    try:
        async with db_pool.acquire() as conn:
            db_user = await conn.fetchrow(
                "SELECT id, password_hash FROM Users WHERE email = $1", 
                user.email
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")
    
    if not db_user or not verify_password(user.password, db_user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    try:        
        token = create_access_token(data={"sub": str(db_user["id"])})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Token creation failed: {str(e)}")
    return {"access_token": token, "token_type": "bearer"}

# Static file serving for frontend
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
else:
    @app.get("/")
    def missing_frontend():
        return {"error": f"Frontend directory not found at {FRONTEND_DIR}."} 



