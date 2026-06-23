# Invisible Mechanics Backend

FastAPI backend for classes, cohorts, payments, auth sessions, and Cloudflare Stream playback.

## Local Development

```powershell
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8001
```

If your host does not use `uv`, install from `requirements.txt` and run:

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

The backend reads `.env` from this directory. `APP_JWT_SECRET` must match the frontend `APP_JWT_SECRET`.

## Deployment

Use this folder as the container service root. The included `Dockerfile` starts:

```text
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Set `WEB_ORIGIN` to the deployed frontend URL so CORS accepts browser requests.

## Required Production Env

Copy `.env.example` into your deployment provider and fill the same values from local `.env`.

The frontend must use the deployed backend URL as `NEXT_PUBLIC_API_URL`, and both apps must share the same `APP_JWT_SECRET`.
