# type: ignore
"""
Saidi — FastAPI backend
  POST /chat  → Claude API → { reply }
  GET  /*     → serves frontend/ as a SPA
"""

import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Env ──────────────────────────────────────────────────────────
# Load .env when running locally; on Render the var is set in the dashboard
load_dotenv(Path(__file__).parent.parent.parent / ".env")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_API_KEY:
    raise RuntimeError(
        "ANTHROPIC_API_KEY is not set. "
        "Add it to your .env file locally or to Render's environment variables."
    )

# ── Paths ─────────────────────────────────────────────────────────
# backend/app/main.py  →  ../../  →  repo root  →  frontend/
FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"

# ── Anthropic client ──────────────────────────────────────────────
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

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
    history: list[dict] = []      # [{ "role": "user"|"assistant", "content": "..." }]
    active_tasks: list[str] = []  # ["Buy groceries", "Finish report"]

# _____ /saidi tools definition ─────────────────────────────────────────────
SAIDI_TOOLS = [
    {
        "name": "add_task",
        "description": "Add a new task to Calvin's dashboard.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_text": {"type": "string", "description": "The task to add"}
            },
            "required": ["task_text"]
        }
    },
    {
        "name": "remove_task",
        "description": "Remove or complete a task from Calvin's dashboard.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_text": {"type": "string", "description": "A close match to the task name to remove"}
            },
            "required": ["task_text"]
        }
    }
]

def _enforce_alternating(messages: list[dict]) -> list[dict]:
    """
    Claude requires strict user/assistant alternation starting with 'user'.
    Merge consecutive same-role messages by joining their content.
    """
    if not messages:
        return messages

    merged = [messages[0]]
    for msg in messages[1:]:
        if msg["role"] == merged[-1]["role"]:
            # Same role back-to-back → merge
            merged[-1]["content"] += "\n" + msg["content"]
        else:
            merged.append(msg)

    # Must start with 'user'
    if merged[0]["role"] != "user":
        merged.pop(0)

    return merged

@app.post("/chat")
async def chat(req: ChatRequest):
    # Format the active tasks for the system prompt
    task_string = "\n".join(f"- {task}" for task in req.active_tasks) if req.active_tasks else "No active tasks."

    # Inject the active tasks into the system prompt
    dynamic_system_prompt = SYSTEM_PROMPT.format(active_tasks_list=task_string)

    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in req.history
        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and m["content"].strip()
    ]

    if not messages or messages[-1]["role"] != "user":
        messages.append({"role": "user", "content": req.message})

    messages = _enforce_alternating(messages)

    try:
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=dynamic_system_prompt,
            messages=messages,
            tools=SAIDI_TOOLS # Inject the tools here
        )
        
        reply_text = ""
        actions = []

        # Claude's response can contain both text and tool requests
        for block in response.content:
            if block.type == "text":
                reply_text += block.text
            elif block.type == "tool_use":
                # Catch the AI's intent to use a tool
                actions.append({
                    "type": block.name,
                    "payload": block.input
                })

        print(f"DEBUG - Claude text: {reply_text}")
        print(f"DEBUG - Claude actions: {actions}")
        return {"reply": reply_text, "actions": actions}

    except Exception as exc:
        raise HTTPException(502, f"API error: {exc}")


# ── Serve frontend SPA ────────────────────────────────────────────
# This MUST be last — the static mount catches everything not matched above.
# html=True makes it serve index.html for any unmatched path (SPA routing).
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
else:
    @app.get("/")
    def missing_frontend():
        return {"error": f"Frontend not found at {FRONTEND_DIR}. Run from repo root."}
