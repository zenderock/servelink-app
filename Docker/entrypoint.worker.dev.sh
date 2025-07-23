#!/bin/sh
set -e

exec uv run arq --watch /app worker.WorkerSettings