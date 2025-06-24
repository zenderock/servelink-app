#!/bin/bash

echo "Starting local environment..."

mkdir -p ./data/{db,traefik,upload}

NO_CACHE=true
PRUNE=false
for a in "$@"; do
  [ "$a" = "--cache" ] && NO_CACHE=false
  [ "$a" = "--prune" ] && PRUNE=true
done

CACHE_FLAG=""
[ "$NO_CACHE" = true ] && CACHE_FLAG="--no-cache"

[ "$PRUNE" = true ] && docker image prune -f

docker-compose build $CACHE_FLAG runner && \
docker-compose down -v && \
docker-compose up --build --force-recreate