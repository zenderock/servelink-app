#!/bin/bash

echo "Starting local environment..."

mkdir -p ./data/{traefik,upload}

NO_CACHE=true
PRUNE=false
for a in "$@"; do
  [ "$a" = "--cache" ] && NO_CACHE=false
  [ "$a" = "--prune" ] && PRUNE=true
done

CACHE_FLAG=""
[ "$NO_CACHE" = true ] && CACHE_FLAG="--no-cache"

[ "$PRUNE" = true ] && docker image prune -f

docker-compose -p devpush -f docker-compose.yml -f docker-compose.override.dev.yml build $CACHE_FLAG runner && \
docker-compose -p devpush -f docker-compose.yml -f docker-compose.override.dev.yml down && \
docker-compose -p devpush -f docker-compose.yml -f docker-compose.override.dev.yml up --build --force-recreate