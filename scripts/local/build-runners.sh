#!/bin/bash
set -e

echo "Building runner images..."

for dockerfile in Docker/runner/Dockerfile.*; do
  if [ -f "$dockerfile" ]; then
    name=$(basename "$dockerfile" | sed 's/Dockerfile\.//')
    echo "Building runner-$name from $dockerfile..."
    docker build -f "$dockerfile" -t "runner-$name" ./Docker/runner
  fi
done

echo "Runner images built successfully!"