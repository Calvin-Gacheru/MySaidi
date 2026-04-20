# type: ignore
"""
Saidi — FastAPI backend
    POST /chat  → Groq API → { reply }
  GET  /*     → serves frontend/ as a SPA
"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pytz
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from groq import Groq
from pydantic import BaseModel, Field

from langsmith import traceable

# ── Env ──────────────────────────────────────────────────────────
load_dotenv(Path(__file__).parent.parent.parent / ".env")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
if not GROQ_API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY is not set. "
        "Add it to your .env file locally or to Render's environment variables."
    )

GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

# ── Paths ─────────────────────────────────────────────────────────
FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"

# ── Groq client ───────────────────────────────────────────────────
groq_client = Groq(api_key=GROQ_API_KEY)

# __ Timezone
NAIROBI_TZ = pytz.timezone("Africa/Nairobi")

def _now_nairobi() -> str:
    """Return current Nairobi time as a readable string."""
    now = datetime.now(NAIROBI_TZ)
    return now.strftime("%A, %d %B %Y – %H:%M EAT")


def _format_calendar(events: list[dict[str, Any]]) -> str:
    """Render the calendar event list for injection into the system prompt."""
    if not events:
        return "No events scheduled."

    lines = []
    for ev in events:
        start = ev.get("start_time") or "flexible"
        end = ev.get("end_time") or ""
        time_range = f"{start} → {end}" if end else start
        flexible_tag = " [FLEXIBLE]" if ev.get("is_flexible") else ""
        lines.append(f"- id={ev['id']} | {ev['title']} | {time_range}{flexible_tag}")
    return "\n".join(lines)


def _normalize_event_id(raw_id: str) -> str:
    """
    Canonicalize model-supplied IDs like "[05fc4a0a]", "id=05fc4a0a", or "id:05fc4a0a".
    """
    cleaned = raw_id.strip()
    if not cleaned:
        return ""

    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1].strip()

    lower_cleaned = cleaned.lower()
    if lower_cleaned.startswith("id="):
        cleaned = cleaned[3:].strip()
    elif lower_cleaned.startswith("id:"):
        cleaned = cleaned[3:].strip()

    return cleaned


def _normalize_incoming_events(raw_items: list[dict[str, Any] | str]) -> list[dict[str, Any]]:
    """
    Accept legacy string tasks and structured calendar events.
    Returns normalized event dictionaries.
    """
    normalized: list[dict[str, Any]] = []

    for item in raw_items:
        if isinstance(item, str):
            title = item.strip()
            if not title:
                continue
            normalized.append(
                {
                    "id": str(uuid.uuid4())[:8],
                    "title": title,
                    "start_time": None,
                    "end_time": None,
                    "is_flexible": True,
                }
            )
            continue

        if not isinstance(item, dict):
            continue

        title = str(item.get("title") or item.get("text") or "").strip()
        if not title:
            continue

        start_time = item.get("start_time")
        end_time = item.get("end_time")
        is_flexible = bool(item.get("is_flexible", not (start_time or end_time)))
        normalized_id = _normalize_event_id(str(item.get("id") or str(uuid.uuid4())[:8]))
        if not normalized_id:
            normalized_id = str(uuid.uuid4())[:8]

        normalized.append(
            {
                "id": normalized_id,
                "title": title,
                "start_time": start_time,
                "end_time": end_time,
                "is_flexible": is_flexible,
            }
        )

    return normalized


# ── Saidi's personality ───────────────────────────────────────────
SYSTEM_PROMPT = """
You are Saidi, A Calvin's personal AI task assistant and daily productivity companion.

CURRENT DATE & TIME (Nairobi / EAT):
{current_time}

CURRENT ACTIVE TASKS:
{active_tasks_list}

PERSONALITY
- Warm, optimistic, and action-oriented — like a helpful Kenyan friend who gets things done
- Address Calvin by name naturally (but not every single sentence)
- Light Kenyan flavour: weave in Nairobi life (matatus, traffic, nyama choma, family, resilience)
  when it feels natural — never forced or stereotyped
- Celebrate wins however small; completion is victory
- Slightly cheeky when the moment allows, always respectful
- Direct and honest — you encourage without empty flattery
- When things feel overwhelming, acknowledge briefly then pivot to action

YOUR ROLE & TOOLS RULES
- Help Calvin plan, prioritise, and manage his calendar.
- You have TWO tools: `manage_calendar` (add / update / remove events) and `request_clarification`.

SCHEDULING RULES — READ CAREFULLY
1. ALWAYS read the CURRENT CALENDAR above before scheduling anything.
2. CONFLICT CHECK: If a requested time overlaps with an existing fixed (non-flexible) event, you
   MUST stop immediately and propose two or three alternative times. Do NOT schedule over it.
3. FLEXIBLE TASKS: If the user is vague ("sometime tonight", "in the evening", "later"), schedule
   the event as flexible (is_flexible: true) with no strict start_time/end_time unless they insist
   on a specific hour.
4. CLARIFICATION: If critical info is completely unknown (e.g., duration of a meeting, date of a
   deadline), use `request_clarification` to ask ONE targeted question. Do not guess.
5. META-TASK BAN: NEVER create events like "Resolve scheduling conflict", "Check calendar", or any
   task that is about managing tasks. Only real activities go on the calendar.
6. SILENT EXECUTION: Do NOT output raw JSON, XML tags, or tool schemas in your text reply.
7. After a successful tool call, keep your text reply under 20 words.
8. ID FORMAT: When calling `manage_calendar` with action='update' or 'remove', pass only the raw id
    value (example: 05fc4a0a). Do not include square brackets.

RESPONSE FORMAT
- Keep replies concise (under 100 words) unless Calvin explicitly asks for a detailed plan
- Use **bold** for key actions or emphasis
- No more than 4 bullet points in any list
- End with a short question or nudge to keep momentum — unless the conversation naturally closes
- Never use corporate jargon or filler phrases like "Certainly!" or "Of course!"
""".strip()

# ── App ───────────────────────────────────────────────────────────
app = FastAPI(title="Saidi API", docs_url=None, redoc_url=None)


# ── Request model ─────────────────────────────────────────────────

class CalendarEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str
    start_time: str | None = None   # ISO 8601 string, e.g. "2025-07-04T09:00:00+03:00"
    end_time: str | None = None     # ISO 8601 string
    is_flexible: bool = False

class ChatRequest(BaseModel):
    message: str                  # current user message (also present in history)
    history: list[dict[str, Any]] = Field(default_factory=list)      # [{ "role": "user"|"assistant", "content": "..." }]
    active_tasks: list[dict[str, Any] | str] = Field(default_factory=list)

# ── Tool definitions ──────────────────────────────────────────────
SAIDI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "manage_calendar",
            "description": (
                "Add, update, or remove a calendar event for Calvin. "
                "Use action='add' for new events, 'update' to change an existing one by id, "
                "'remove' to delete an event by id."

            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "update", "remove"],
                        "description": "The operation to perform."
                    },
                    "id": {
                        "type": "string",
                        "description": "Required for 'update' and 'remove'. Pass raw id only (e.g. 05fc4a0a), no square brackets."
                    },
                    "title": {
                        "type": "string",
                        "description": "Human-readable event title (required for 'add', optional for 'update')."
                    },
                    "start_time": {
                        "type": "string",
                        "description": (
                            "ISO 8601 datetime string in EAT (+03:00), e.g. '2025-07-04T09:00:00+03:00'. "
                            "Omit entirely for flexible/floating events."
                        )
                    },
                    "end_time": {
                        "type": "string",
                        "description": "ISO 8601 end datetime. Omit for flexible events."
                    },
                    "is_flexible": {
                        "type": "boolean",
                        "description": (
                            "True if the event has no strict time commitment. "
                            "Default to true when the user is vague about timing."
                        )
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "request_clarification",
            "description": (
                "Halt the ReAct loop and ask Calvin one specific question before proceeding. "
                "Use this when critical scheduling info (date, duration, priority) is completely unknown."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question_text": {
                        "type": "string",
                        "description": "A single, specific question to ask Calvin."
                    }
                },
                "required": ["question_text"]
            }
        }
    }
]

# ── Helpers ───────────────────────────────────────────────────────
def _build_history_messages(
    history: list[dict[str, Any]],
    current_message: str,
) -> list[dict[str, str]]:
    """
    Keep only clean user/assistant text history and ensure the final turn is user.
    """
    messages: list[dict[str, str]] = []
    for msg in history:
        role = msg.get("role")
        content = msg.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            messages.append({"role": role, "content": content})

    if not messages or messages[-1]["role"] != "user":
        messages.append({"role": "user", "content": current_message})

    return messages


def _parse_tool_arguments(raw_arguments: str | None) -> dict[str, Any]:
    """
    Parse tool-call arguments emitted by the model.
    """
    if not raw_arguments:
        return {}

    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def _find_event_by_id(event_id: str, events: list[dict[str, Any]]) -> dict[str, Any] | None:
    needle = _normalize_event_id(event_id).lower()
    if not needle:
        return None

    for ev in events:
        event_value = _normalize_event_id(str(ev.get("id", ""))).lower()
        if event_value == needle:
            return ev
    return None



# def _find_task_match(task_to_remove: str, current_tasks: list[str]) -> str | None:
#     """
#     Match by exact text first, then by case-insensitive containment.
#     """
#     needle = task_to_remove.strip().lower()
#     if not needle:
#         return None

#     for task in current_tasks:
#         if task.lower() == needle:
#             return task

#     for task in current_tasks:
#         lower_task = task.lower()
#         if needle in lower_task or lower_task in needle:
#             return task

#     return None

# ── Chat endpoint ─────────────────────────────────────────────────
@app.post("/chat")
@traceable(run_type="chain", name="Saidi ReAct Loop")
async def chat(req: ChatRequest):
    # Normalize request payload so both legacy task strings and event objects work.
    current_tasks: list[dict[str, Any]] = _normalize_incoming_events(req.active_tasks)

    # 1. Live clock
    current_time = _now_nairobi()

    # 2. Format calendar for prompt
    calendar_str = _format_calendar(current_tasks)

    # 3. Inject both into system prompt
    dynamic_system_prompt = SYSTEM_PROMPT.format(
        current_time=current_time,
        active_tasks_list=calendar_str,
    )

    messages: list[dict[str, Any]] = [{"role": "system", "content": dynamic_system_prompt}]
    messages.extend(_build_history_messages(req.history, req.message))

    # Mutable calendar state for this request
    actions: list[dict[str, Any]] = []
    reply_text = ""

    for _ in range(6):
        try:
            response = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                tools=SAIDI_TOOLS,
                tool_choice="auto",
                max_tokens=512,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Groq API error: {exc}") from exc

        if not response.choices:
            raise HTTPException(status_code=502, detail="Groq returned no completion choices.")

        assistant_message = response.choices[0].message
        print("Assistant message:", assistant_message)
        tool_calls = list(assistant_message.tool_calls or [])

        assistant_payload: dict[str, Any] = {
            "role": "assistant",
            "content": assistant_message.content or "",
        }
        if tool_calls:
            assistant_payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments or "{}",
                    },
                }
                for call in tool_calls
            ]
        messages.append(assistant_payload)

        if not tool_calls:
            reply_text = (assistant_message.content or "").strip()
            break

        # ── Execute tool calls ────────────────────────────────────
        for call in tool_calls:
            tool_name = call.function.name
            tool_args = _parse_tool_arguments(call.function.arguments)
            print(f"Tool call: {tool_name} with args {tool_args}")

            # ── request_clarification: halt and surface question ──
            if tool_name == "request_clarification":
                question = str(tool_args.get("question_text", "")).strip()
                if question:
                    # Surface the question directly — no further loop iterations needed
                    return {
                        "reply": question,
                        "updated_tasks": current_tasks,
                        "actions": actions,
                        "clarification_requested": True,
                    }
                result_content = "Error: question_text was empty."

            # ── manage_calendar ───────────────────────────────────
            elif tool_name == "manage_calendar":
                action = str(tool_args.get("action", "")).strip().lower()

                if action == "add":
                    title = str(tool_args.get("title", "")).strip()
                    if not title:
                        result_content = "Error: title is required for add."
                    else:
                        new_event: dict[str, Any] = {
                            "id": str(uuid.uuid4())[:8],
                            "title": title,
                            "start_time": tool_args.get("start_time"),
                            "end_time": tool_args.get("end_time"),
                            "is_flexible": bool(tool_args.get("is_flexible", False)),
                        }
                        current_tasks.append(new_event)
                        actions.append({"type": "add_event", "payload": new_event})
                        result_content = f"Success: Added event '{title}' (id={new_event['id']})"

                elif action == "update":
                    event_id = _normalize_event_id(str(tool_args.get("id", "")))
                    target = _find_event_by_id(event_id, current_tasks)
                    if not target:
                        known_ids = ", ".join(str(ev.get("id", "")).strip() for ev in current_tasks if ev.get("id")) or "none"
                        result_content = f"Error: No event found with id '{event_id}'. Available ids: {known_ids}."
                    else:
                        for field in ("title", "start_time", "end_time", "is_flexible"):
                            if field in tool_args:
                                target[field] = tool_args[field]
                        actions.append({"type": "update_event", "payload": dict(target)})
                        result_content = f"Success: Updated event '{target['title']}' (id={target.get('id')})"

                elif action == "remove":
                    event_id = _normalize_event_id(str(tool_args.get("id", "")))
                    target = _find_event_by_id(event_id, current_tasks)
                    if not target:
                        known_ids = ", ".join(str(ev.get("id", "")).strip() for ev in current_tasks if ev.get("id")) or "none"
                        result_content = f"Error: No event found with id '{event_id}'. Available ids: {known_ids}."
                    else:
                        current_tasks.remove(target)
                        actions.append({"type": "remove_event", "payload": {"id": target.get("id"), "title": target.get("title")}})
                        result_content = f"Success: Removed event '{target['title']}'"

                else:
                    result_content = f"Error: Unknown action '{action}'. Must be add, update, or remove."

            else:
                result_content = f"Error: Unknown tool '{tool_name}'."

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result_content,
                }
            )
    else:
        raise HTTPException(
            status_code=500,
            detail="Tool loop exceeded max iterations without final text response.",
        )

    if not reply_text and actions:
        reply_text = "Done boss."

    return {
        "reply": reply_text,
        "updated_tasks": current_tasks,
        "actions": actions,
        "clarification_requested": False,
    }

# ── Serve frontend SPA ────────────────────────────────────────────
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
else:
    @app.get("/")
    def missing_frontend():
        return {"error": f"Frontend not found at {FRONTEND_DIR}. Run from repo root."}
