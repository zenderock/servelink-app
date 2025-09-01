#!/bin/bash
set -e

usage(){
  cat <<USG
Usage: build-runners.sh [--cache] [-h|--help]

Build local runner images from Docker/runner/* Dockerfiles.

  --cache    Use build cache (default: no cache)
  -h, --help Show this help
USG
  exit 0
}
[ "$1" = "-h" ] || [ "$1" = "--help" ] && usage

echo "Building runner images..."

no_cache=1
for a in "$@"; do
  [ "$a" = "--cache" ] && no_cache=0
done

found=0
for dockerfile in Docker/runner/Dockerfile.*; do
  [ -f "$dockerfile" ] || continue
  found=1
  name=$(basename "$dockerfile" | sed 's/Dockerfile\.//')
  echo "Building runner-$name from $dockerfile..."
  if ((no_cache==1)); then
    docker build --no-cache -f "$dockerfile" -t "runner-$name" ./Docker/runner
  else
    docker build -f "$dockerfile" -t "runner-$name" ./Docker/runner
  fi
done

if ((found==0)); then
  echo "No runner Dockerfiles found under Docker/runner/."
else
  echo "Runner images built successfully!"
fi