# type: ignore
from math import e
import os
import uuid
from datetime import datetime
import pytz
from typing import Annotated, TypedDict, Any, Optional
from pydantic import BaseModel, Field

from langchain_core.messages import SystemMessage, BaseMessage, AIMessage
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.prompts import PromptTemplate

# Define the Structured Output Schema
class SemanticIntent(BaseModel):
    category: str = Field(description="Must be one of: 'direct_command', 'implicit_event', 'general_chat'")
    confidence: float = Field(description="Confidence score from 0.0 to 1.0")
    detected_subject: Optional[str] = Field(description="The core topic, e.g., 'Data Science Exam' or 'Gym'")
    detected_time: Optional[str] = Field(description="Any time reference, e.g., 'next Thursday at 10am'")
    requires_proactive_offer: bool = Field(description="True if Saidi should offer to add this to the calendar/tracker")

# --- State Definition ---
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    clarification_requested: bool
    extracted_intent: Optional[SemanticIntent] # this state holds the parse intent

# --- Database Tools ---
def _pool_from_config(config: RunnableConfig | None):
    if not config:
        print("[Saidi-Tools] Config is entirely missing.")
        return None
        
    # LangGraph wraps configurations. We need to check both top-level and 'configurable'
    configurable = config.get("configurable", {})
    pool = configurable.get("db_pool")
    
    if pool is None:
        print("[Saidi-Tools] db_pool not found in config. Current config:", config)
        return None
        
    return pool

# Unindented parse_datatime funtion to be used by the manage_calendar tool
def parse_datetime(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    try:
        # Try standard ISO format first
        return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
    except ValueError:
        try:
            # Handle formats like "5:00 PM" by combining with today's date
            today = datetime.now(pytz.timezone("Africa/Nairobi")).date()
            # Try 12-hour format
            time_obj = datetime.strptime(dt_str.strip(), "%I:%M %p").time()
            dt = datetime.combine(today, time_obj)
            return pytz.timezone("Africa/Nairobi").localize(dt)
        except ValueError:
            try:
                # Try 24-hour format "17:00"
                time_obj = datetime.strptime(dt_str.strip(), "%H:%M").time()
                dt = datetime.combine(today, time_obj)
                return pytz.timezone("Africa/Nairobi").localize(dt)
            except ValueError:
                print(f"[Saidi] Could not parse date string: {dt_str}")
                return None

@tool
async def manage_calendar(
    action: str,
    config: RunnableConfig,
    title: str = "",
    start_time: str | None = None,
    end_time: str | None = None,
    is_flexible: bool | None = None,
    task_id: str | None = None,
    event_id: str | None = None,
    id: str | None = None,
) -> str:
    """Add, update, or remove a calendar event. Action must be 'add', 'update', or 'remove'."""
    pool = _pool_from_config(config)
    if pool is None:
        return "Error: Database is not configured. Set DATABASE_URL to enable calendar updates."
    
    target_id = task_id or event_id or id
    normalized_start = parse_datetime(start_time)
    normalized_end = parse_datetime(end_time)
    
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
    
        # ID validation
        if not target_id:
            return "Error: A valid ID is required for update or remove actions."
        try:
            uuid_obj = uuid.UUID(str(target_id))
        except ValueError:
            return f"Error: {target_id} is not a valid UUID." 

            
        if action == "remove":
            result = await conn.execute("DELETE FROM Tasks WHERE id = $1", uuid.UUID)
            return f"Success: Removed event id={target_id}" if not result.endswith("0") else f"Error: No event found with id={target_id}"

        if action == "update":
            updates, args = [], []
            if title.strip():
                updates.append(f"title = ${len(args) + 2}"); args.append(title)
            if start_time is not None:
                updates.append(f"start_time = ${len(args) + 2}"); args.append(normalized_start)
            if end_time is not None:
                updates.append(f"end_time = ${len(args) + 2}"); args.append(normalized_end)
            if is_flexible is not None:
                updates.append(f"is_flexible = ${len(args) + 2}"); args.append(is_flexible)

            if not updates:
                return "Error: No update fields provided."

            query = f"UPDATE Tasks SET {', '.join(updates)} WHERE id = $1"
            result = await conn.execute(query, uuid_obj, *args)
            return f"Success: Updated event id={target_id}" if not result.endswith("0") else f"Error: No event found with id={target_id}."
        
    return "Error: Action must be add, update, or remove."

@tool
async def log_habit_progress(habit_id: str, completions: int, config: RunnableConfig) -> str:
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
async def get_schedule(config: RunnableConfig) -> str:
    """Read current active calender events and tasks"""
    pool = _pool_from_config(config)
    if pool is None:
        return "Error: Database is not configured."
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, start_time, end_time, is_flexible
            FROM Tasks
            WHERE done = FALSE
            ORDER BY start_time ASC NULLS LAST
            """
        )
    if not rows:
        return "The schedule is currently empty"
    
    schedule = []
    for r in rows:
        start = r['start_time'].strftime('%Y-%m-%d %H:%M') if r['start_time'] else 'Flexible'
        end = f" to {r['end_time'].strftime('%H:%M')}" if r['end_time'] else ''
        schedule.append(f"- {r['title']} ({start}{end}) [ID: {r['id']}]")

    return "\n".join(schedule)
        

@tool
def request_clarification(question_text: str) -> str:
    """Ask Calvin a specific question when critical scheduling info is missing."""
    return f"CLARIFICATION_NEEDED: {question_text}"

tools = [manage_calendar, get_schedule, log_habit_progress, request_clarification]

# --- Agent Node & Extraction Chain ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

if GROQ_API_KEY:
    llm = ChatGroq(
        api_key=GROQ_API_KEY,
        model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        temperature=0,
    ).bind_tools(tools)

    # Setup for intent parser
    intent_extractor = llm.with_structured_output(SemanticIntent)
    extraction_prompt = PromptTemplate.from_template(
        """Analyze the user input. 
        If they explicitly command an action (e.g., 'Add a meeting'), category is 'direct_command'.
        If they mention a future event or obligation casually (e.g., 'I have an exam on Tuesday'), category is 'implicit_event' and requires_proactive_offer is True.
        If it is just conversation, category is 'general_chat'.
        
        User Input: {input}"""
    )
    extraction_chain = extraction_prompt | intent_extractor
else:
    llm = None
    extraction_chain = None

#---System Prompt for Agent ---
SYSTEM_PROMPT = """
You are Saidi, Calvin's personal AI task assistant.
Time: {current_time}

Help plan, prioritise, manage calendar, and track habits.
RULES:
1. To check what is currently on the schedule, ALWAYS use the `get_schedule` tool.
2. To modify the schedule, use `manage_calendar` (actions: add, update, remove). DO NOT use manage_calendar to search or read.
3. 3. Respond to queries using standard conversational text. DO NOT use the `request_clarification` tool to deliver answers, summarize schedules, or ask polite follow-ups. 
ONLY use `request_clarification` if a database action is completely blocked because you are missing required parameters.
4. NEVER output raw UUIDs or database IDs to the user. Keep them hidden in your internal thought process.
5. Always format dates and times naturally in your final response (e.g., "Today at 1:00 PM" instead of "2026-04-27 13:00").
6. After calling a tool, summarize what you did in natural language. 
7. NEVER just say "I've added it" if you haven't successfully called the tool and received a 'Success' response from the database.
8. If the user asks to add a task, your FIRST and ONLY response must be a tool call to `manage_calendar`.
9. 9. When calling tools, always calculate the correct date based on the current time. Provide start_time and end_time as strict ISO 8601 strings with timezone offsets (e.g., '2026-05-02T18:00:00+03:00'). DO NOT use simple HH:MM formats.

{intent_context}
"""

# --- Chat Endpoint Integration ---
async def call_model(state: AgentState, config: RunnableConfig):
    messages = state["messages"]

    if llm is None:
        return {
            "messages": AIMessage(
                content="Saidi is online, but GROQ_API_KEY is missing. Set it to enable AI chat responses."
            ),
            "clarification_requested": False,
        }
    
    # Extract the parsed intent from state and feed it into the prompt so the LLM acts on it
    intent_data = state.get("extracted_intent")
    intent_context_str = ""
    if intent_data:
        intent_context_str = f"Parsed Intent - Category: {intent_data.category}, Detected Subject: {intent_data.detected_subject}, Detected Time: {intent_data.detected_time}, Requires Proactive Offer: {intent_data.requires_proactive_offer}"
    else:
        intent_context_str = "No clear intent detected yet."

    # Force the system prompt to be the very first thing the model sees
    current_time = datetime.now(pytz.timezone("Africa/Nairobi")).strftime("%A, %d %B %Y – %H:%M EAT")
    sys_msg = SystemMessage(content=SYSTEM_PROMPT.format(
        current_time=current_time,
        intent_context=intent_context_str
    ))

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


def parse_intent_node(state: AgentState):
    user_message = state["messages"][-1].content

    if extraction_chain is None:
        return {"extracted_intent": None}
    
    intent_data = extraction_chain.invoke({"input": user_message})
    
    # Pass the structured data into the state for the next node to read
    return {"extracted_intent": intent_data}

# --- Graph Compilation ---
workflow = StateGraph(AgentState)
workflow.add_node("intent_parser", parse_intent_node)
workflow.add_node("agent", call_model)
workflow.add_node("tools", ToolNode(tools))

workflow.add_edge(START, "intent_parser")
workflow.add_edge("intent_parser", "agent")
workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
workflow.add_edge("tools", "agent")

graph = workflow.compile()