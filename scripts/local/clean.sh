#!/bin/bash

echo "Cleaning up local environment..."

docker stop $(docker ps -a -q) && \
docker rm $(docker ps -a -q) && \
docker rmi $(docker images -a -q) -f && \
docker network rm devpush_default || true && \
docker network rm devpush_internal || true && \
rm -rf ./data/traefik/* && \
mkdir -p ./data/{db,traefik,upload}