mkdir -p ./data/{db,traefik,upload}
docker-compose build runner && \
docker-compose down -v && \
docker-compose up --build --force-recreate