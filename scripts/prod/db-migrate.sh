#!/bin/bash
set -e

if [ -f "$(dirname "$0")/../../.env.devops" ]; then
    source "$(dirname "$0")/../../.env.devops"
fi

if [ -z "$SERVER_IP" ]; then
    echo -e "\033[31mError: SERVER_IP not found in devops/.env.devops\033[0m"
    exit 1
fi

echo "Running production database migrations on $SERVER_IP..."

# Check if containers are running
echo "Checking if app container is running..."
if ! ssh deploy@$SERVER_IP "docker compose -p devpush ps app | grep -q 'Up'"; then
    echo "Error: App container is not running on $SERVER_IP"
    exit 1
fi

# Check if database is ready
echo "Checking database connection..."
ssh deploy@$SERVER_IP "docker compose -p devpush exec pgsql pg_isready -U devpush-app"

echo "Database is ready. Running migrations..."
ssh deploy@$SERVER_IP "docker compose -p devpush exec app uv run alembic upgrade head"

echo "Migrations completed successfully!" 