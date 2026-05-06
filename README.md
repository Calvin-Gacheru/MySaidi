# MySaidi

**MySaidi** is a personal AI productivity assistant — a full-stack web app combining a FastAPI backend with a vanilla-JS frontend served by the same process. Saidi (Swahili for *helper*) is an AI chat agent powered by Groq's LLM that helps you plan your day, manage tasks and events, and track habits — all through natural conversation.

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Architecture Overview](#architecture-overview)
- [Getting Started (Local Development)](#getting-started-local-development)
- [Environment Variables](#environment-variables)
- [API Reference](#api-reference)
- [Database Schema](#database-schema)
- [AI Agent](#ai-agent)
- [Frontend](#frontend)
- [Deployment (Railway)](#deployment-railway)
- [License](#license)

---

## Features

| Feature | Description |
|---|---|
| 💬 **AI Chat Assistant** | Converse with Saidi to add, update, remove, or review tasks and events |
| 📋 **Task Management** | Create tasks with optional start/end times; mark done; filter by All / Active / Done |
| 🗓️ **Calendar View** | Month-grid overview with drilldown to an hourly day view |
| 🔄 **Habit Tracker** | Track daily habits (Tracker type) or bad habits you want to break (Breaker type) |
| 🔒 **Authentication** | Email/password register & login; JWT-protected API endpoints |
| 📱 **Progressive Web App** | Installable on mobile and desktop; mobile-optimised with a slide-up chat drawer |
| 🌙 **Appearance Settings** | Light/dark mode toggle; choice of Normal, Cursive, or System font |

---

## Tech Stack

### Backend
| Layer | Technology |
|---|---|
| Web framework | [FastAPI](https://fastapi.tiangolo.com/) |
| ASGI server | [Uvicorn](https://www.uvicorn.org/) |
| Database driver | [asyncpg](https://magicstack.github.io/asyncpg/) (async PostgreSQL) |
| AI / LLM | [Groq](https://groq.com/) (`llama-3.3-70b-versatile` by default) |
| Agent framework | [LangGraph](https://langchain-ai.github.io/langgraph/) + [LangChain-Groq](https://python.langchain.com/docs/integrations/chat/groq/) |
| Auth | [PyJWT](https://pyjwt.readthedocs.io/) + [bcrypt](https://pypi.org/project/bcrypt/) |
| Config | [python-dotenv](https://pypi.org/project/python-dotenv/) |

### Frontend
| Layer | Technology |
|---|---|
| UI | Vanilla HTML5 / CSS3 / JavaScript (no framework) |
| PWA | Web App Manifest + service worker |
| Fonts | Outfit, DM Sans, Caveat (Google Fonts) |

---

## Project Structure

```
MySaidi/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   └── main.py          # FastAPI application, lifespan, DB schema init, auth routes
│   ├── routers/
│   │   ├── chat.py          # POST /chat — AI agent endpoint
│   │   └── tasks.py         # CRUD + sync routes for /api/tasks
│   ├── agents.py            # LangGraph agent, tools, system prompt
│   ├── auth.py              # JWT creation/verification, password hashing
│   ├── database.py          # DB connection helper
│   ├── schemas.py           # Pydantic models
│   └── requirements.txt     # Python dependencies (pinned)
├── frontend/
│   ├── icons/               # App icons / logo
│   ├── index.html           # Single-page application shell
│   ├── manifest.json        # PWA manifest
│   ├── script.js            # All client-side logic
│   └── style.css            # Styles (dark-first, responsive)
├── .env.example             # Example environment variables
├── .gitignore
├── LICENSE
├── Procfile                 # Heroku / Railway process definition
├── railway.json             # Railway deployment config
├── README.md
└── requirements.txt         # Root requirements (points to backend/requirements.txt)
```

---

## Architecture Overview

```
Browser (PWA)
    │
    │  HTTP/REST
    ▼
FastAPI app  (backend/app/main.py)
    ├─ POST /register  ──► Users table (PostgreSQL)
    ├─ POST /login     ──► JWT token
    ├─ POST /chat      ──► LangGraph Agent
    │                          ├─ Intent Parser  (Groq structured output)
    │                          ├─ Agent Node     (Groq LLM + tool binding)
    │                          └─ Tool Node
    │                               ├─ manage_calendar  (INSERT/UPDATE/DELETE Tasks)
    │                               ├─ get_schedule     (SELECT Tasks)
    │                               ├─ log_habit_progress (INSERT HabitLogs)
    │                               └─ request_clarification
    ├─ GET/POST/PATCH/DELETE /api/tasks  ──► Tasks table
    └─ Static files /  ──► frontend/
```

---

## Getting Started (Local Development)

### Prerequisites

- Python 3.11+
- A running PostgreSQL instance (or a managed cloud DB)
- A [Groq API key](https://console.groq.com/)

### Steps

1. **Clone the repository**

   ```bash
   git clone https://github.com/Calvin-Gacheru/MySaidi.git
   cd MySaidi
   ```

2. **Create and activate a virtual environment**

   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**

   ```bash
   cp .env.example .env
   # Edit .env with your values (see Environment Variables section below)
   ```

5. **Start the server**

   ```bash
   uvicorn backend.app.main:app --reload --port 8000
   ```

6. **Open the app**

   Navigate to `http://localhost:8000` in your browser.

> **Note:** The database tables (`Users`, `Tasks`, `HabitLogs`) are created automatically on first startup if `DATABASE_URL` is set.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the values:

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | ✅ | Your Groq API key (get one at [console.groq.com](https://console.groq.com/)) |
| `GROQ_MODEL` | ❌ | Groq model name (default: `llama-3.3-70b-versatile`) |
| `DATABASE_URL` | ✅ | PostgreSQL connection string, e.g. `postgresql://user:password@host:5432/saidi` |
| `JWT_SECRET_KEY` | ✅ | Secret key used to sign JWT tokens (use a long random string) |
| `ALGORITHM` | ❌ | JWT signing algorithm (default: `HS256`) |

Without `DATABASE_URL`, the app starts but registration, login, and task management are disabled. Without `GROQ_API_KEY`, Saidi will respond with a placeholder message instead of AI-generated replies.

---

## API Reference

All task and chat endpoints require a valid JWT `Authorization: Bearer <token>` header obtained from `/login`.

### Authentication

| Method | Path | Body | Description |
|---|---|---|---|
| `POST` | `/register` | `{ "email": "…", "password": "…" }` | Create a new account |
| `POST` | `/login` | `{ "email": "…", "password": "…" }` | Returns `{ "access_token": "…", "token_type": "bearer" }` |

### Chat

| Method | Path | Body | Description |
|---|---|---|---|
| `POST` | `/chat` | `{ "message": "…", "history": […], "active_tasks": […] }` | Send a message to Saidi; returns AI reply and updated task list |

**Response:**
```json
{
  "reply": "I've added 'Team standup' on Monday at 9:00 AM.",
  "clarification_requested": false,
  "actions": [],
  "updated_tasks": [ … ]
}
```

### Tasks (`/api/tasks`)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/tasks` | List all tasks for the authenticated user |
| `POST` | `/api/tasks` | Create a new task |
| `PATCH` | `/api/tasks/{task_id}` | Update a specific task (partial update) |
| `DELETE` | `/api/tasks/{task_id}` | Delete a specific task |
| `POST` | `/api/tasks/sync` | Bulk upsert tasks (optionally replace existing) |

**Task object:**
```json
{
  "id": "uuid",
  "title": "Buy groceries",
  "start_time": "2026-05-06T10:00:00+03:00",
  "end_time": "2026-05-06T11:00:00+03:00",
  "is_flexible": false,
  "done": false,
  "createdAt": 1746518400000
}
```

---

## Database Schema

Three tables are auto-created on startup:

```sql
-- Users
CREATE TABLE IF NOT EXISTS Users (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email        TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Tasks / Calendar Events
CREATE TABLE IF NOT EXISTS Tasks (
    id          UUID PRIMARY KEY,
    title       TEXT NOT NULL,
    start_time  TIMESTAMPTZ,
    end_time    TIMESTAMPTZ,
    is_flexible BOOLEAN DEFAULT FALSE,
    done        BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id     UUID NOT NULL
);

-- Habit Logs
CREATE TABLE IF NOT EXISTS HabitLogs (
    id          UUID PRIMARY KEY,
    habit_id    UUID NOT NULL,
    date        DATE NOT NULL,
    completions INTEGER DEFAULT 0,
    user_id     UUID NOT NULL
);
```

---

## AI Agent

The agent is built with **LangGraph** and runs as a directed graph:

```
START → intent_parser → agent ⇄ tools → END
```

### Nodes

| Node | Role |
|---|---|
| `intent_parser` | Classifies the user's message as `direct_command`, `implicit_event`, or `general_chat` using Groq structured output. Sets `requires_proactive_offer` when Saidi should volunteer to add something to the calendar. |
| `agent` | Calls the Groq LLM (bound with tools). Reads the parsed intent and current time from state and constructs the final response or issues tool calls. |
| `tools` | Executes any tool calls made by the agent. |

### Tools

| Tool | Description |
|---|---|
| `manage_calendar` | `add` / `update` / `remove` events in the `Tasks` table |
| `get_schedule` | Reads all incomplete tasks for the current user |
| `log_habit_progress` | Inserts a `HabitLogs` record for today |
| `request_clarification` | Signals that Saidi needs more information before acting |

The agent receives the authenticated user's `db_pool` and `user_id` through LangGraph's `RunnableConfig`, ensuring data isolation between users.

---

## Frontend

The frontend is a **single-page application** served as static files from FastAPI's `StaticFiles` mount.

### Views

| View | Description |
|---|---|
| **Dashboard** | Task list with add-task form and All / Active / Done filter tabs |
| **Calendar** | Month grid; click a day to see an hourly timeline of scheduled tasks |
| **Habits** | Add / track / delete habits with per-day completion logging |
| **Private** | Placeholder for private notes (coming soon) |
| **Settings** | Light mode toggle, font style selector, and logout |

### Mobile Experience

On small screens the chat panel becomes a **slide-up drawer** triggered by a floating action button (FAB). A backdrop overlay and drag handle are included for a native-app feel.

### PWA

The app ships a `manifest.json` and supports installation on Android, iOS, and desktop via the browser's "Add to Home Screen" / "Install" prompt.

---

## Deployment (Railway)

The repo is pre-configured for [Railway](https://railway.app/):

- `requirements.txt` at the repo root includes all backend dependencies
- `Procfile` defines the web process
- `railway.json` sets the build (Nixpacks) and start command

### Steps

1. Push this repository to GitHub.
2. In Railway, click **New Project → Deploy from GitHub repo** and select this repo.
3. Add a **PostgreSQL** plugin (Railway provisions the `DATABASE_URL` automatically).
4. Set the following environment variables in Railway:

   | Variable | Value |
   |---|---|
   | `GROQ_API_KEY` | Your Groq API key |
   | `JWT_SECRET_KEY` | A long random secret string |
   | `GROQ_MODEL` | *(optional)* e.g. `llama-3.3-70b-versatile` |

5. Click **Deploy**.

Railway starts the app with:

```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT
```

---

## License

This project is licensed under the terms of the [LICENSE](LICENSE) file included in this repository.
