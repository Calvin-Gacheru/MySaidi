# type: ignore
from typing import Any, List, Optional
from datetime import datetime
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

# --- Task Models ---
class TaskBase(BaseModel):
    title: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    is_flexible: bool = False
    done: bool = False

class TaskCreate(TaskBase):
    id: UUID = Field(default_factory=uuid4)

class TaskResponse(TaskBase):
    id: UUID

# --- Habit Models ---
class HabitBase(BaseModel):
    name: str
    habit_type: str  # 'tracker' or 'breaker'
    daily_quota: int = 1

class HabitResponse(HabitBase):
    id: UUID
    created_at: datetime

class HabitLog(BaseModel):
    id: UUID
    habit_id: UUID
    date: datetime
    completions: int

# --- API Request Models ---
class ChatRequest(BaseModel):
    message: str
    history: List[dict[str, Any]] = Field(default_factory=list)
    
    # Note: Once the database migration is complete, the backend should fetch active_tasks 
    # directly from Postgres instead of relying on the client. 
    # We keep this field temporarily to avoid breaking your current frontend.
    active_tasks: List[Any] = Field(default_factory=list)