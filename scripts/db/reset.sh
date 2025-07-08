#!/usr/bin/env sh
# Drop and recreate the public schema of the Postgres DB defined in .env

set -e

DB_CONTAINER=${DB_CONTAINER:-pgsql}
DB_USER=${POSTGRES_USER:-devpush}
DB_NAME=${POSTGRES_DB:-devpush}

echo "Dropping and recreating the public schema of the Postgres DB defined in .env"

docker-compose exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"