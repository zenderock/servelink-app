#!/bin/sh

set -e

export UV_PROJECT_ENVIRONMENT=.venv.worker
uv run alembic upgrade head
exec uv run arq --watch /app worker.WorkerSettings