# MySaidi

Saidi is a FastAPI backend with a static frontend served by the same app.

## Project Structure

```
MySaidi/
├── backend/
│   ├── agents.py
│   ├── database.py
│   ├── requirements.txt
│   ├── schemas.py
│   ├── app/
│   │   ├── __init__.py
│   │   └── main.py
│   └── routers/
│       ├── chat.py
│       └── tasks.py
├── frontend/
│   ├── icons/
│   ├── index.html
│   ├── manifest.json
│   ├── script.js
│   └── style.css
├── LICENSE
├── Procfile
├── pyproject.toml
├── railway.json
├── README.md
├── requirements.txt
└── uv.lock
```

## Local Development

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create `.env` from `.env.example` and set your keys.
4. Run the server:

```bash
uvicorn backend.app.main:app --reload --port 8000
```

Open `http://localhost:8000`.

## Railway Deployment

This repo is now Railway-ready:

- `requirements.txt` at repo root for dependency install
- `Procfile` and `railway.json` for startup configuration
- `uvicorn` bound to `0.0.0.0:$PORT`

### Steps

1. Push this repository to GitHub.
2. In Railway, create a new project and select this repository.
3. Set environment variables in Railway:
	- `GROQ_API_KEY`
	- `GROQ_MODEL` (optional, defaults in code)
4. Deploy.

Railway will start your app with:

```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT
```
