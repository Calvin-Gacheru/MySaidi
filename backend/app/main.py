# type: ignore
"""
Saidi — FastAPI backend
    POST /chat  → Groq API → { reply }
  GET  /*     → serves frontend/ as a SPA
"""

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from groq import Groq
from pydantic import BaseModel, Field

from langsmith import traceable

# ── Env ──────────────────────────────────────────────────────────
# Load .env when running locally; on Render the var is set in the dashboard
load_dotenv(Path(__file__).parent.parent.parent / ".env")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
if not GROQ_API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY is not set. "
        "Add it to your .env file locally or to Render's environment variables."
    )

GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

# ── Paths ─────────────────────────────────────────────────────────
# backend/app/main.py  →  ../../  →  repo root  →  frontend/
FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"

# ── Groq client ───────────────────────────────────────────────────
groq_client = Groq(api_key=GROQ_API_KEY)

# ── Saidi's personality ───────────────────────────────────────────
SYSTEM_PROMPT = """
You are Saidi, A Calvin's personal AI task assistant and daily productivity companion.

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
- Help Calvin plan, prioritise, and crush his tasks.
- CRITICAL TOOL RULE: You have access to `add_task` and `remove_task` tools. You MUST use them to keep the dashboard synced with reality.
- IMPLICIT COMPLETIONS: If Calvin states as a fact that he has completed an activity (e.g., "I already bought bread", "finished the report"), IMMEDIATELY check the CURRENT ACTIVE TASKS list. If the activity logically matches an active task, you MUST trigger `remove_task`. Do not wait for him to explicitly say "remove this task".
- EXPLICIT REQUESTS: If Calvin explicitly asks you to add or remove a task, trigger the respective tool immediately.
- SILENT EXECUTION: Do NOT output XML tags like <attempt_tool_call> or raw JSON in your text response.
- If you use a tool, keep your text reply extremely short (e.g., "Sawa, crossed that off!", "Done boss.").

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
class ChatRequest(BaseModel):
    message: str                  # current user message (also present in history)
    history: list[dict[str, Any]] = Field(default_factory=list)      # [{ "role": "user"|"assistant", "content": "..." }]
    active_tasks: list[str] = Field(default_factory=list)  # ["Buy groceries", "Finish report"]

# _____ /saidi tools definition ─────────────────────────────────────────────
SAIDI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Add a new task to Calvin's dashboard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_text": {"type": "string", "description": "The task to add"}
                },
                "required": ["task_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remove_task",
            "description": "Complete a task from Calvin's dashboard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_text": {"type": "string", "description": "A close match to the task name to remove"}
                },
                "required": ["task_text"]
            }
        }
    }
]


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


def _find_task_match(task_to_remove: str, current_tasks: list[str]) -> str | None:
    """
    Match by exact text first, then by case-insensitive containment.
    """
    needle = task_to_remove.strip().lower()
    if not needle:
        return None

    for task in current_tasks:
        if task.lower() == needle:
            return task

    for task in current_tasks:
        lower_task = task.lower()
        if needle in lower_task or lower_task in needle:
            return task

    return None

@app.post("/chat")
@traceable(run_type="chain", name="Saidi ReAct Loop")
async def chat(req: ChatRequest):
    # Format the active tasks for the system prompt
    task_string = "\n".join(f"- {task}" for task in req.active_tasks) if req.active_tasks else "No active tasks."

    # Inject the active tasks into the system prompt
    dynamic_system_prompt = SYSTEM_PROMPT.format(active_tasks_list=task_string)

    messages: list[dict[str, Any]] = [{"role": "system", "content": dynamic_system_prompt}]
    messages.extend(_build_history_messages(req.history, req.message))

    # Local state to track modification during ReAct loop
    current_tasks = req.active_tasks.copy()
    actions: list[dict[str, Any]] = []
    reply_text = ""

    # Cap tool loops to avoid accidental infinite tool-calling cycles.
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
            raise HTTPException(
                status_code=502,
                detail=f"Groq API error: {exc}",
            ) from exc

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

        # If model wants to use tools, execute them and append tool messages.
        for call in tool_calls:
            tool_name = call.function.name
            tool_args = _parse_tool_arguments(call.function.arguments)
            print(f"Tool call: {tool_name} with args {tool_args}")

            if tool_name == "add_task":
                new_task = str(tool_args.get("task_text", "")).strip()
                if new_task:
                    current_tasks.append(new_task)
                    actions.append({"type": "add_task", "payload": {"task_text": new_task}})
                    result_content = f"Success: Added '{new_task}'"
                else:
                    result_content = "Error: task_text was empty."

            elif tool_name == "remove_task":
                task_to_remove = str(tool_args.get("task_text", "")).strip()
                matched_task = _find_task_match(task_to_remove, current_tasks)
                if matched_task:
                    current_tasks.remove(matched_task)
                    actions.append({"type": "remove_task", "payload": {"task_text": matched_task}})
                    result_content = f"Success: Removed '{matched_task}'"
                else:
                    result_content = (
                        f"Error: Task '{task_to_remove}' not found in current tasks."
                    )
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

    # Return the text AND the updated state so the frontend can sync
    return {
        "reply": reply_text,
        "updated_tasks": current_tasks,
        "actions": actions,
    }      

# ── Serve frontend SPA ────────────────────────────────────────────
# This MUST be last — the static mount catches everything not matched above.
# html=True makes it serve index.html for any unmatched path (SPA routing).
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
else:
    @app.get("/")
    def missing_frontend():
        return {"error": f"Frontend not found at {FRONTEND_DIR}. Run from repo root."}
