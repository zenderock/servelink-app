# DevPush

A modern 

## Stack

- Docker & [Docker Compose](https://github.com/docker/compose)
- [Traefik](https://github.com/traefik/traefik)
- [Loki](https://github.com/grafana/loki)
- [PostreSQL](https://www.postgresql.org/)
- [FastAPI](https://fastapi.tiangolo.com/)
- [arq](https://arq-docs.helpmanual.io/)
- [HTMX](https://htmx.org)
- [Alpine.js](https://alpinejs.dev/)
- [Basecoat](https://basecoatui.com)
- [Ansible](https://github.com/ansible/ansible)
- [Terraform](https://github.com/hashicorp/terraform)

## Overview

- **App**: The app handles all of the user-facing logic (managing teams/projects, authenticating, searching logs...). It communicates with the workers via Redis/
- **Job queue/Worker**: When we create a new deployment, we queue a deploy job using arq/Redis. The workers (in the worker container) execute them and report back in real-time to the app via Redis Streams. These workers are also used to run certain batch jobs (e.g. deleting a team, cleaning up inactive deployments and their containers).
- **Logs**: build logs are streamed from the workers via Redis Streams, and served to the user via an SSE endpoint in the app. Runtime logs are all logged in Loki and made available per project through the app.
- **Runners**: User apps are deployed on one of the runner containers (e.g. `Docker/runner/Dockerfile.python-3`). They are created in the deploy job (`app/tasks/deploy.py`) and then run a series of commands based on the user configuration.
- **Reverse proxy**: We have Traefik sitting in front of both app and the deployed runner containers. All routing is done using Traefik labels, but we also maintain environment and branch aliases (e.g. `my-project-env-staging.devpush.app`) maintaing Traefik config files.

## File structure

- **`app/`**: The main FastAPI application (see Readme file).
- **`devops/`**: Ansible playbooks and Terraform for production setup.
- **`Docker/`**: Container definitions and entrypoint scripts. Includes local developement specific files (e.g. `Dockerfile.app.dev`, `entrypoint.worker.dev.sh`).
- **`scripts/`**: Helper scripts for local (macOS) and production environments
- **`docker-compose.yml`**: Container orchestration with [Docker Compose](https://docs.docker.com/compose/) with overrides for local development (`docker-compose.dev.yml`) and production (`docker-compose.dprod.yml`).

## Install & run

### Local development (MacOS)

1. **Install Colima with the Loki driver** with [Homebrew](https://brew.sh):
   ```bash
   ./scripts/local/intall.sh
   ```

2. **Set up environment variables**:
   ```bash
   cp .env.example .env
   ```

3. **Start your containers**:
   ```bash
   ./scripts/local/start.sh
   ```

4. **Initialize your database** once the containers are up:
   ```bash
   ./scripts/local/db-migrate.sh
   ```

5. **(Optional) Start ngrok**:
   ```bash
   ./scripts/local/ngrok.sh
   ```

Once installed, you can start the app with `./scripts/local/clean.sh`. You can clean up your local dev environment (files, Docker images/networks, ...) with `./scripts/local/clean.sh`.

You can also use `./scripts/local/db-reset.sh` if you want to drop the database and start fresh. You'll need to run `./scripts/local/db-migrate.sh` again afterwards.

### Production

1. **Add your [Hetzner](https://hetzner.com) API key**:
   ```bash
   cp .env.devops.example .env.devops
   ```

2. **Create the server on Hetzner** (CPX31 in Hillsboro):
   ```bash
   ./scripts/prod/create.sh
   ```

3. **Set up the IP address**. Just add the IP address you got from Hetzner to the `.env.devops` file (`SERVER_IP`).

4. **Set up the server**:
   ./scripts/prod/setup.sh
   ```

5. **(Optional) Set up the deploy key**. If you are using a private GitHub repository for the codebase, you should have gotten a key to add to your repo in the output of the previous step.

6. **Set up deploy environment variables**. Set teh GitHub repository (`GITHUB_REPO`) and [Let's Encrypt](https://letsencrypt.org/) email (`LE_EMAIL`) for the SSL setup.
   
7. **Deploy and start the app**:
   ```bash
   ./scripts/prod/deploy.sh
   ```

8. **Initialize your database** once the containers are up:
   ```bash
   ./scripts/prod/migrate.sh
   ```

You can use `./scripts/prod/ssh-tunnel.sh` to establish an SSH tunnel to access the PostgreSQL database locally (via `localhost:15432`).

## Update

### Local development

The app is mounted inside of its container, so any change will show up immediately. However,certain parts of the app are using SSE so changes may not appear until you closed the tabs with the app open (FastAPI won't reload until all active connections are closed).

The worker is also mounted but will usually require a restart: `docker-compose restart worker`.

### Production

Simple run `./scripts/prod/update.sh` and select whether you want to update the app or worker container.

This will run a blue-green update process with Ansible (no downtime). This may take a while for the worker as it waits for all active jobs to be finished before cleaning up the old container.