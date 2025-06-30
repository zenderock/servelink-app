docker-compose exec api alembic init migrations
docker-compose exec api alembic revision --autogenerate -m "Description of changes"
docker-compose exec api alembic upgrade head