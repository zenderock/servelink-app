#!/bin/bash
set -e

usage(){
  cat <<USG
Usage: start.sh [--cache] [--prune] [-h|--help]

Start the local development stack (streams logs).

  --cache    Use build cache (default: no cache)
  --prune    Prune dangling images before build
  -h, --help Show this help
USG
  exit 0
}
[ "$1" = "-h" ] || [ "$1" = "--help" ] && usage

command -v docker-compose >/dev/null 2>&1 || { echo "docker-compose not found"; exit 1; }

echo "Starting local environment..."

mkdir -p ./data/{traefik,upload}

no_cache=1
prune=0
for a in "$@"; do
  [ "$a" = "--cache" ] && no_cache=0
  [ "$a" = "--prune" ] && prune=1
done

((prune==1)) && { echo "Pruning dangling images..."; docker image prune -f; }

# Build runner images
./scripts/dev/build-runners.sh

# Optional no-cache build for services
args=(-p devpush -f docker-compose.yml -f docker-compose.override.dev.yml)
if ((no_cache==1)); then
  echo "Building services with --no-cache..."
  docker-compose "${args[@]}" build --no-cache
fi

echo "Stopping any running stack..."
docker-compose "${args[@]}" down || true

echo "Starting stack with logs (Ctrl+C to stop foreground)..."
docker-compose "${args[@]}" up --build --force-recreate