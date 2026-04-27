# type: ignore
import os
import uuid
from datetime import datetime
import pytz
from typing import Annotated, TypedDict, Any

from langchain_core.messages import SystemMessage, BaseMessage, AIMessage
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

# --- State Definition ---
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    clarification_requested: bool

# --- Database Tools ---
# We use RunnableConfig to pass the FastAPI db_pool into the tools without globals.


def _pool_from_config(config: RunnableConfig | None):
    if not config or not isinstance(config, dict):
        return None
    configurable = config.get("configurable")
    if not isinstance(configurable, dict):
        return None
    return configurable.get("db_pool")

@tool
async def manage_calendar(
    action: str,
    title: str = "",
    start_time: str | None = None,
    end_time: str | None = None,
    is_flexible: bool | None = None,
    task_id: str | None = None,
    event_id: str | None = None,
    id: str | None = None,
    config: RunnableConfig | None = None,
) -> str:
    """Add, update, or remove a calendar event. Action must be 'add', 'update', or 'remove'."""
    pool = _pool_from_config(config)
    if pool is None:
        return "Error: Database is not configured. Set DATABASE_URL to enable calendar updates."

    target_id = task_id or event_id or id
    normalized_start = start_time or None
    normalized_end = end_time or None
    
    async with pool.acquire() as conn:
        if action == "add":
            if not title.strip():
                return "Error: title is required for add."
            new_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO Tasks (id, title, start_time, end_time, is_flexible) VALUES ($1, $2, $3, $4, $5)",
                new_id,
                title,
                normalized_start,
                normalized_end,
                bool(is_flexible) if is_flexible is not None else False,
            )
            return f"Success: Added event '{title}' (id={new_id})"
            
        elif action == "remove":
            if not target_id:
                return "Error: task_id/id is required for remove."
            result = await conn.execute("DELETE FROM Tasks WHERE id = $1", uuid.UUID(target_id))
            if result.endswith("0"):
                return f"Error: No event found with id={target_id}."
            return f"Success: Removed event id={target_id}"

        elif action == "update":
            if not target_id:
                return "Error: task_id/id is required for update."

            updates: list[str] = []
            args: list[Any] = []
            arg_index = 2

            if title.strip():
                updates.append(f"title = ${arg_index}")
                args.append(title)
                arg_index += 1
            if start_time is not None:
                updates.append(f"start_time = ${arg_index}")
                args.append(normalized_start)
                arg_index += 1
            if end_time is not None:
                updates.append(f"end_time = ${arg_index}")
                args.append(normalized_end)
                arg_index += 1
            if is_flexible is not None:
                updates.append(f"is_flexible = ${arg_index}")
                args.append(is_flexible)
                arg_index += 1

            if not updates:
                return "Error: No update fields were provided."

            query = f"UPDATE Tasks SET {', '.join(updates)} WHERE id = $1"
            result = await conn.execute(query, uuid.UUID(target_id), *args)
            if result.endswith("0"):
                return f"Error: No event found with id={target_id}."
            return f"Success: Updated event id={target_id}"
            
        return "Error: Action must be add, update, or remove."

@tool
async def log_habit_progress(habit_id: str, completions: int, config: RunnableConfig | None = None) -> str:
    """Log daily progress for a habit. Increments the completion count for today."""
    pool = _pool_from_config(config)
    if pool is None:
        return "Error: Database is not configured. Set DATABASE_URL to log habits."

    today = datetime.now(pytz.timezone("Africa/Nairobi")).date()
    
    async with pool.acquire() as conn:
        # Upsert logic for habit logging
        new_id = uuid.uuid4()
        await conn.execute('''
            INSERT INTO HabitLogs (id, habit_id, date, completions) 
            VALUES ($1, $2, $3, $4)
        ''', new_id, uuid.UUID(habit_id), today, completions)
        return f"Success: Logged {completions} completions for habit {habit_id} today."

@tool
def request_clarification(question_text: str) -> str:
    """Ask Calvin a specific question when critical scheduling info is missing."""
    return f"CLARIFICATION_NEEDED: {question_text}"

tools = [manage_calendar, log_habit_progress, request_clarification]

# --- Agent Node ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
if GROQ_API_KEY:
    llm = ChatGroq(
        api_key=GROQ_API_KEY,
        model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        temperature=0,
    ).bind_tools(tools)
else:
    llm = None

SYSTEM_PROMPT = """
You are Saidi, Calvin's personal AI task assistant.
Time: {current_time}

Help plan, prioritise, manage calendar, and track habits.
Use tools to interact with the Postgres database.
If clarification is needed, use request_clarification. Do not guess.
"""

async def call_model(state: AgentState, config: RunnableConfig):
    messages = state["messages"]

    if llm is None:
        return {
            "messages": AIMessage(
                content="Saidi is online, but GROQ_API_KEY is missing. Set it to enable AI chat responses."
            ),
            "clarification_requested": False,
        }
    
    # Inject dynamic context (time) into system prompt
    current_time = datetime.now(pytz.timezone("Africa/Nairobi")).strftime("%A, %d %B %Y – %H:%M EAT")
    sys_msg = SystemMessage(content=SYSTEM_PROMPT.format(current_time=current_time))
    
    response = await llm.ainvoke([sys_msg] + messages, config)
    
    # Check if the model called request_clarification to flag state
    clarification = False
    if response.tool_calls:
        for call in response.tool_calls:
            if call["name"] == "request_clarification":
                clarification = True
                
    return {"messages": response, "clarification_requested": clarification}

# --- Edge Logic ---
def should_continue(state: AgentState):
    messages = state["messages"]
    last_message = messages[-1]
    
    if state.get("clarification_requested", False):
        return END
        
    if not last_message.tool_calls:
        return END
        
    return "tools"

# --- Graph Compilation ---
workflow = StateGraph(AgentState)
workflow.add_node("agent", call_model)
workflow.add_node("tools", ToolNode(tools))

workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
workflow.add_edge("tools", "agent")

graph = workflow.compile()