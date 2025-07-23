#!/bin/sh

set -e

export UV_PROJECT_ENVIRONMENT=.venv.app
uv run alembic upgrade head
exec uv run uvicorn main:app --host 0.0.0.0 --port 8000 --loop uvloop --reload