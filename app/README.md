docker-compose exec app alembic init migrations
docker-compose exec app alembic revision --autogenerate -m "Description of changes"
docker-compose exec app alembic upgrade head