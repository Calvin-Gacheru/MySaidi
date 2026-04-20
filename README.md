# MySaidi

 ---
  To run locally, install deps first:

  # With uv (you already have it):
  uv add fastapi "uvicorn[standard]" groq python-dotenv

  # In .env set:
  # GROQ_API_KEY=gsk_your_key_here
  # GROQ_MODEL=llama-3.3-70b-versatile

  # Then start the server from the repo root:
  uvicorn backend.app.main:app --reload --port 8000
