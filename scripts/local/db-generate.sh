#!/bin/bash
set -e

echo "Creating database migrations..."

# Check if containers are running
if ! docker-compose ps app | grep -q "Up"; then
    echo "Error: App container is not running. Start the environment first with ./scripts/local/start.sh"
    exit 1
fi

# Check if database is ready
echo "Checking database connection..."
until docker-compose exec pgsql pg_isready -U devpush-app; do
    echo "Database not ready yet..."
    sleep 2
done

echo "Database is ready. Creating migrations..."

# Prompt user for migration message
read -p "Migration message: " message

# Check if message was provided
if [ -z "$message" ]; then
    echo "Error: Migration message is required"
    exit 1
fi

# Generate the migration
docker-compose exec app uv run alembic revision --autogenerate -m "$message"

echo "Migrations created successfully!" 