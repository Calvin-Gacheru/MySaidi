# MySaidi

 ---
  To run locally, install deps first:

  # With uv (you already have it):
  uv add fastapi "uvicorn[standard]" anthropic python-dotenv

  # Then start the server from the repo root:
  uvicorn backend.app.main:app --reload --port 8000