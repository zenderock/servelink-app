# DevPush Application

FastAPI-based deployment platform with real-time log streaming and container management.

## File structure

- **Project Management** - GitHub integration, environment configuration
- **Deployment Engine** - Docker-based deployments with zero-downtime updates
- **Real-time Logging** - Loki integration with live log streaming
- **Team Collaboration** - Multi-user teams with role-based access
- **Environment Management** - Staging, production, and custom environments

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy, Redis, PostgreSQL
- **Frontend**: HTMX, Alpine.js, Tailwind CSS
- **Infrastructure**: Docker, Loki, Prometheus
- **Deployment**: Ansible, Terraform

## Local Development

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- Redis
- PostgreSQL

### Setup

1. **Install Dependencies**
   ```bash
   cd app
   pip install -r requirements.txt
   ```

2. **Database Setup**
   ```bash
   alembic upgrade head
   ```

3. **Environment Variables**
   ```bash
   cp .env.example .env
   # Configure your settings
   ```

4. **Start Development Server**
   ```bash
   uvicorn main:app --reload
   ```

## API Documentation

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

## Key Components

### Models
- `Project` - Deployment projects with GitHub integration
- `Deployment` - Individual deployments with status tracking
- `Team` - Multi-user collaboration
- `User` - Authentication and permissions

### Services
- `DeploymentService` - Container orchestration
- `GitHubService` - Repository integration
- `LokiService` - Log aggregation and querying

### Templates
- HTMX-based UI with Alpine.js for interactivity
- Real-time updates via Server-Sent Events
- Responsive design with Tailwind CSS

## Deployment

See root [README.md](../README.md) for production deployment instructions.


docker-compose exec app alembic init migrations
docker-compose exec app alembic revision --autogenerate -m "Description of changes"
docker-compose exec app alembic upgrade head