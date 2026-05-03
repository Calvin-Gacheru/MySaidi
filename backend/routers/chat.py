# type: ignore
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from backend.schemas import ChatRequest
from backend.auth import get_current_user_id

router = APIRouter()


def _extract_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts).strip()

    return str(content).strip() if content is not None else ""


def _safe_active_tasks(req: ChatRequest) -> list[Any]:
    return req.active_tasks if isinstance(req.active_tasks, list) else []


def _serialize_task(row: Any) -> dict[str, Any]:
    created_at = row["created_at"]
    created_ms = int(created_at.timestamp() * 1000) if created_at else int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    start_time = row["start_time"]
    end_time = row["end_time"]

    return {
        "id": str(row["id"]),
        "title": row["title"],
        "text": row["title"],
        "start_time": start_time.isoformat() if start_time else None,
        "end_time": end_time.isoformat() if end_time else None,
        "is_flexible": bool(row["is_flexible"]),
        "done": bool(row["done"]),
        "createdAt": created_ms,
    }


async def _snapshot_tasks(request: Request, fallback: list[Any]) -> list[Any]:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        return fallback

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, title, start_time, end_time, is_flexible, done, created_at
                FROM Tasks
                ORDER BY COALESCE(start_time, created_at) DESC NULLS LAST, created_at DESC
                """
            )
        return [_serialize_task(row) for row in rows]
    except Exception as exc:
        print(f"[Saidi] Failed to fetch task snapshot: {exc}")
        return fallback

@router.post("/chat")
async def chat_endpoint(req: ChatRequest, request: Request):
    # Combine history and current message
    messages = req.history + [{"role": "user", "content": req.message}]
    active_tasks = _safe_active_tasks(req)

    try:
        from backend.agents import graph
    except ModuleNotFoundError:
        try:
            from agents import graph
        except Exception as exc:
            print(f"[Saidi] Agent import failed: {exc}")
            return {
                "reply": "Saidi backend is online, but the AI agent failed to initialize.",
                "clarification_requested": False,
                "actions": [],
                "updated_tasks": await _snapshot_tasks(request, active_tasks),
            }
    except Exception as exc:
        print(f"[Saidi] Agent import failed: {exc}")
        return {
            "reply": "Saidi backend is online, but the AI agent failed to initialize.",
            "clarification_requested": False,
            "actions": [],
            "updated_tasks": await _snapshot_tasks(request, active_tasks),
        }
    
    # Inject the database pool into the LangGraph configuration
    config = {
        "configurable": {
            "db_pool": getattr(request.app.state, "db_pool", None),
            "user_id": user_id
            }
        }
    
    try:
        result = await asyncio.wait_for(
            graph.ainvoke({"messages": messages}, config),
            timeout=25,
        )
        print(result)
    except asyncio.TimeoutError:
        print("[Saidi] Chat invocation timed out.")
        return {
            "reply": "I took too long to respond. Please try again in a moment.",
            "clarification_requested": False,
            "actions": [],
            "updated_tasks": await _snapshot_tasks(request, active_tasks),
        }
    except Exception as exc:
        print(f"[Saidi] Chat invocation failed: {exc}")
        return {
            "reply": "I hit a backend issue while processing that. Please try again.",
            "clarification_requested": False,
            "actions": [],
            "updated_tasks": await _snapshot_tasks(request, active_tasks),
        }


    result_messages = result.get("messages", []) if isinstance(result, dict) else []
    if result_messages:
        last_message = result_messages[-1]
        final_message = _extract_message_text(getattr(last_message, "content", ""))

        # Fallback - extract text from tool calls if content is empty
        if not final_message and getattr(last_message, "too_calls", None):
            for tool in last_message.tool_calls:
                if tool.get("name") == "request_clarification":
                    final_message = tool.get("args", {}).get("question_text", "")
                    break                
    
    else:
        final_message = ""

    if not final_message:
        final_message = "I did not generate a response. Please try again."

    clarification = bool(result.get("clarification_requested", False)) if isinstance(result, dict) else False

    return {
        "reply": final_message,
        "clarification_requested": clarification,
        "actions": [],
        "updated_tasks": await _snapshot_tasks(request, active_tasks),
    }