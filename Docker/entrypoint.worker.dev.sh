#!/bin/sh

set -e

uv run alembic upgrade head
exec uv run arq --watch /app worker.WorkerSettings