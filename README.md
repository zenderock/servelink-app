# /dev/push

A modern deployment platform that automates container deployments with real-time logging, GitHub integration, and zero-downtime updates. Built for teams who want simple, fast deployments without the complexity of traditional CI/CD pipelines.

## Stack

- Docker & [Docker Compose](https://github.com/docker/compose)
- [Traefik](https://github.com/traefik/traefik)
- [Loki](https://github.com/grafana/loki)
- [PostgreSQL](https://www.postgresql.org/)
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
- **Reverse proxy**: We have Traefik sitting in front of both app and the deployed runner containers. All routing is done using Traefik labels, but we also maintain environment and branch aliases (e.g. `my-project-env-staging.devpush.app`) maintaining Traefik config files.

## File structure

- **`app/`**: The main FastAPI application (see Readme file).
- **`devops/`**: Ansible playbooks and Terraform for production setup.
- **`Docker/`**: Container definitions and entrypoint scripts. Includes local development specific files (e.g. `Dockerfile.app.dev`, `entrypoint.worker.dev.sh`).
- **`scripts/`**: Helper scripts for local (macOS) and production environments
- **`docker-compose.yml`**: Container orchestration with [Docker Compose](https://docs.docker.com/compose/) with overrides for local development (`docker-compose.override.dev.yml`) and production (`docker-compose.override.prod.yml`).

## Install & run

### Local development (MacOS)

1. **Install Colima with the Loki driver** with [Homebrew](https://brew.sh):
   ```bash
   ./scripts/local/install.sh
   ```

2. **Set up environment variables** (see [Environment variables](#environment-variables)):
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

Start the app with `./scripts/local/start.sh`. You can clean up your local dev environment (files, Docker images/networks, ...) with `./scripts/local/clean.sh`.

You can also use:

- `./scripts/local/db-reset.sh` to drop the database and start fresh.
- `./scripts/local/db-generate.sh` to generate a new migration file if you've made changes to the models.

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
   ```bash
   ./scripts/prod/setup.sh
   ```

5. **(Optional) Set up the deploy key**. If you are using a private GitHub repository for the codebase, you should have gotten a key to add to your repo in the output of the previous step.

6. **Set up environment variables** (see [Environment variables](#environment-variables)). Do not forget to set the GitHub repository (`GITHUB_REPO`) and [Let's Encrypt](https://letsencrypt.org/) email (`LE_EMAIL`) for the SSL setup:
   ```bash
   cp .env.prod.example .env.prod
   ```
   
7. **Deploy and start the app**:
   ```bash
   ./scripts/prod/deploy.sh
   ```

8. **Initialize your database** once the containers are up:
   ```bash
   ./scripts/prod/db-migrate.sh
   ```

You can use `./scripts/prod/ssh-tunnel.sh` to establish an SSH tunnel to access the PostgreSQL database locally (via `localhost:15432`).

## Update

### Local development

The app is mounted inside of its container, so any change will show up immediately. However, certain parts of the app are using SSE so changes may not appear until you closed the tabs with the app open (FastAPI won't reload until all active connections are closed).

The worker is also mounted but will usually require a restart: `docker-compose restart worker`.

### Production

Run `./scripts/prod/update.sh` and select whether you want to update the app or worker container.

This will run a blue-green update process with Ansible (no downtime). This may take a while for the worker as it waits for all active jobs to be finished before cleaning up the old container.

### Environment variables

Variable | Comments | Default
--- | --- | ---
`APP_NAME` | App name. | `/dev/push`
`APP_DESCRIPTION` | App description. | `Deploy your Python app without touching a server.`
`URL_SCHEME` | `http` (development) or `https` (production). | `http`
`LE_EMAIL` | Email used to register the Let's Encrypt (ACME) account in Traefik; receives certificate issuance/renewal/expiry notifications. | `dev@devpu.sh`
`HOSTNAME` | Hostname for the app (e.g. `app.devpu.sh`). | `localhost`
`DEPLOY_DOMAIN` | Domain used for deployments (e.g. `devpush.app` if you want your deployments available at `*.devpush.app`). | `localhost`
`SERVER_UP` | Public IP of the server | `127.0.0.1`
`SECRET_KEY` | Secret key for JWT tokens, sessions, and CSRF protection. | `secret-key`
`ENCRYPTION_KEY` | Encryption key for sensitive data (e.g. GitHub tokens). | `encryption-key`
`EMAIL_LOGO` | URL for email logo image. Only helpful for testing, as the app will use `app/logo-email.png` if left empty. | `""`
`EMAIL_SENDER_NAME` | Name displayed as email sender for invites/login. | `""`
`EMAIL_SENDER_ADDRESS` | Email sender used for invites/login. | `""`
`RESEND_API_KEY` | API key for [Resend](https://resend.com). | `""`
`GITHUB_APP_ID` | GitHub App ID. | `""`
`GITHUB_APP_NAME` | GitHub App name. | `""`
`GITHUB_APP_PRIVATE_KEY` | GitHub App private key (PEM format). | `""`
`GITHUB_APP_WEBHOOK_SECRET` | GitHub webhook secret for verifying webhook payloads. | `""`
`GITHUB_APP_CLIENT_ID` | GitHub OAuth app client ID. | `""`
`GITHUB_APP_CLIENT_SECRET` | GitHub OAuth app client secret. | `""`
`GOOGLE_CLIENT_ID` | Google OAuth client ID. | `""`
`GOOGLE_CLIENT_SECRET` | Google OAuth client secret. | `""`
`POSTGRES_HOST` | PostgreSQL host address. | `pgsql`
`POSTGRES_DB` | PostgreSQL database name. | `devpush`
`POSTGRES_USER` | PostgreSQL username. | `devpush-app`
`POSTGRES_PASSWORD` | PostgreSQL password. | `devpush`
`REDIS_URL` | Redis connection URL. | `redis://redis:6379`
`DOCKER_HOST` | Docker daemon host address. | `tcp://docker-proxy:2375`
`UPLOAD_DIR` | Directory for file uploads. | `/upload`
`TRAEFIK_CONFIG_DIR` | Traefik configuration directory. | `/data/traefik`
`DEFAULT_CPU_QUOTA` | Default CPU quota for containers (microseconds). | `100000`
`DEFAULT_MEMORY_MB` | Default memory limit for containers (MB). | `4096`
`JOB_TIMEOUT` | Job timeout in seconds. | `320`
`JOB_COMPLETION_WAIT` | Job completion wait time in seconds. | `300`
`DEPLOYMENT_TIMEOUT` | Deployment timeout in seconds. | `300`
`LOG_LEVEL` | Logging level. | `WARNING`
`DB_ECHO` | Enable SQL query logging. | `false`
`ENV` | Environment (development/production). | `development`
`ACCESS_EMAIL_DENIED_MESSAGE` | Message shown to users who are denied access based on  [sign-in access control](#sign-in-access-control). | `Sign-in not allowed for this email.`
`ACCESS_EMAIL_DENIED_WEBHOOK_URL` | Optional webhook to receive denied events (read more about [Sign-in access control](#sign-in-access-control)). | `""`
`NGROK_CUSTOM_DOMAIN` | **Local development only**. Used by `scripts/local/ngrok.sh` to start the [ngrok](https://ngrok.com/) http tunnel. | 

### GitHub App

You will need to configure a GitHub App with the following settings:

- **Identifying and authorizing users**:
  - **Callback URL**: add two callback URLs with your domain:
   - https://example.com/api/github/authorize/callback
   - https://example.com/auth/github/callback
  - **Expire user authorization tokens**: No
- **Post installation**:
  - **Setup URL**: https://example.com/api/github/install/callback
  - **Redirect on update**: Yes
- **Webhook**:
  - **Active**: Yes
  - **Webhook URL**: https://example.com/api/github/webhook
- **Permissions**:
  - **Repository permissions**
    - **Administration**: Read and write
    - **Checks**: Read and write
    - **Commit statuses**: Read and write
    - **Contents**: Read and write
    - **Deployments**: Read and write
    - **Issues**: Read and write
    - **Metadata**: Read-only
    - **Pull requests**: Read and write
    - **Webhook**: Read and write
  - **Account permissions**:
    - **Email addresses**: Read-only
- **Subscribe to events**:
  - Installation target
  - Push
  - Repository

## Sign-in access control

You can restrict who can sign up/sign in by adding an access rules file:

```bash
cp access.example.json access.json
```

The file can contain a list of emails, a list of allowed email domains, globs and regexes:

```json
{
  "emails": ["alice@example.com"],
  "domains": ["example.com"],
  "globs": ["*@corp.local", "*.dept.example.com"],
  "regex": ["^[^@]+@(eng|research)\\.example\\.com$"]
}
```

Globs use shell-style wildcards, regex are Python patterns. If the rules file is missing or empty, all valid emails are allowed.

Additionally, if you set the `ACCESS_EMAIL_DENIED_WEBHOOK_URL` [environment variable](#environment-variables), denied sign-in attempts will be posted to the provided URL with the following payload:

```json
{
  "email": "user@example.com",
  "provider": "google",
  "ip": "203.0.113.10",
  "user_agent": "Mozilla/5.0"
}
```

## License

[MIT](/LICENSE.md)