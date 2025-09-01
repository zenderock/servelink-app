> **⚠️ Warning**: THIS IS STILL UNDER DEVELOPMENT. I'm very close to making the first beta release, working mostly on simplifying the deployment process (removing the dependency on Terraform and Ansible) and adding more documentation/tutorials for those who want to self-host. A few things may still change.

# /dev/push

An open-source and self-hostable alternative to Vercel, Render, Netlify and the likes. It allows you to build and deploy any app (Python, Node.js, PHP, ...) with zero-downtime updates, real-time logs, team management, customizable environments and domains, etc.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://devpu.sh/assets/images/screenshot-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="https://devpu.sh/assets/images/screenshot-light.png">
  <img alt="A screenshot of a deployment in /dev/push." src="https://devpu.sh/assets/images/screenshot-dark.png">
</picture>

## Key features

- **Git-based deployments**: Push to deploy from GitHub with zero-downtime rollouts and instant rollback.
- **Multi-language support**: Python, Node.js, PHP... basically anything that can run on Docker.
- **Environment management**: Multiple environments with branch mapping and encrypted environment variables.
- **Real-time monitoring**: Live and searchable build and runtime logs.
- **Team collaboration**: Role-based access control with team invitations and permissions.
- **Custom domains**: Support for custom domain and automatic Let's Encrypt SSL certificates.
- **Self-hosted and open source**: Run on your own servers, MIT licensed.

## Documentation

Read the documentation online: [devpu.sh/docs](https://devpu.sh/docs)

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

## Overview

- **App**: The app handles all of the user-facing logic (managing teams/projects, authenticating, searching logs...). It communicates with the workers via Redis/
- **Workers**: When we create a new deployment, we queue a deploy job using arq. It will start a container, then delegate monitoring to a separate backrgound worker (`app/workers/arq.py`), before wrapping things back with yet another job. These workers are also used to run certain batch jobs (e.g. deleting a team, cleaning up inactive deployments and their containers).
- **Logs**: build and runtime logs are streamed from Loki and served to the user via an SSE endpoint in the app.
- **Runners**: User apps are deployed on one of the runner containers (e.g. `Docker/runner/Dockerfile.python-3`). They are created in the deploy job (`app/tasks/deploy.py`) and then run a series of commands based on the user configuration.
- **Reverse proxy**: We have Traefik sitting in front of both app and the deployed runner containers. All routing is done using Traefik labels, but we also maintain environment and branch aliases (e.g. `my-project-env-staging.devpush.app`) maintaining Traefik config files.

## File structure

- `app/`: The main FastAPI application (see Readme file).
- `app/workers`: The workers (`arq` and `monitor`)
- `Docker/`: Container definitions and entrypoint scripts. Includes local development specific files (e.g. `Dockerfile.app.dev`, `entrypoint.worker-arq.dev.sh`).
- `scripts/`: Helper scripts for local (macOS) and production environments
- `docker-compose.yml`: Container orchestration with [Docker Compose](https://docs.docker.com/compose/) with overrides for local development (`docker-compose.override.dev.yml`).

## Install & run

### Local development (macOS)

1. Install Colima and the Loki Docker plugin:
   ```bash
   scripts/dev/install.sh
   ```

2. Set up environment variables (see [Environment variables](#environment-variables)):
   ```bash
   cp .env.example .env
   ```

3. Start your containers (streams logs):
   ```bash
   scripts/dev/start.sh
   ```
   - Add `--prune` to prune dangling images before build
   - Add `--cache` to use the build cache (default is no cache)

4. Initialize your database once the containers are up:
   ```bash
   scripts/dev/db-migrate.sh
   ```

Optional:
- `scripts/dev/db-generate.sh` to create a migration (prompts for message)
- `scripts/dev/db-reset.sh` to drop and recreate the `public` schema
- `scripts/dev/clean.sh` to stop the stack and clean dev data (`--hard` for global cleanup)

### Production

Install from a tagged release (recommended):
```bash
curl -fsSL https://raw.githubusercontent.com/hunvreus/devpush/0.1.0-beta.1/scripts/prod/install.sh | sudo bash
```
-or latest main (bleeding-edge):
```bash
curl -fsSL https://raw.githubusercontent.com/hunvreus/devpush/main/scripts/prod/install.sh | sudo bash
```

After install:
1. Edit `.env` as needed (created from `.env.example`).
2. Start services:
   ```bash
   scripts/prod/start.sh --migrate
   ```
3. Update later:
   ```bash
   scripts/prod/update.sh --all          # app + workers (zero-downtime)
   scripts/prod/update.sh --full -y      # full stack restart (downtime)
   scripts/prod/update.sh --components app,worker-arq
   ```

## Scripts

| Area | Script | What it does |
|---|---|---|
| Dev | `scripts/dev/install.sh` | Setup Colima and install Loki Docker plugin |
| Dev | `scripts/dev/start.sh` | Start stack with logs (foreground); supports `--prune`, `--cache` |
| Dev | `scripts/dev/build-runners.sh` | Build runner images (default no cache; `--cache` to enable) |
| Dev | `scripts/dev/db-generate.sh` | Generate Alembic migration (prompts for message) |
| Dev | `scripts/dev/db-migrate.sh` | Apply Alembic migrations |
| Dev | `scripts/dev/db-reset.sh` | Drop and recreate `public` schema in DB |
| Dev | `scripts/dev/clean.sh` | Stop stack and clean dev data (`--hard` for global) |
| Prod | `scripts/prod/install.sh` | Server setup: Docker, Loki plugin, user, clone repo, create `.env` |
| Prod | `scripts/prod/start.sh` | Start services; optional `--migrate` |
| Prod | `scripts/prod/stop.sh` | Stop services (`--down` for hard stop) |
| Prod | `scripts/prod/restart.sh` | Restart services; optional `--migrate` |
| Prod | `scripts/prod/update.sh` | Update by tag; `--all` (app+workers), `--full` (downtime), or `--components` |
| Prod | `scripts/prod/db-migrate.sh` | Apply DB migrations in production |

## Update

### Local development

The app is mounted inside of its container, so code changes reflect immediately. Some SSE endpoints may require closing browser tabs to trigger a reload.

### Production

Run `scripts/prod/update.sh` and choose:
- `--all` for app + workers zero‑downtime updates
- `--components app,worker-arq` to target components
- `--full -y` for a full stack restart (downtime)

## Environment variables

Variable | Comments | Default
--- | --- | ---
`APP_NAME` | App name. | `/dev/push`
`APP_DESCRIPTION` | App description. | `Deploy your Python app without touching a server.`
`URL_SCHEME` | `http` (development) or `https` (production). | `https`
`LE_EMAIL` | Email used to register the Let's Encrypt (ACME) account in Traefik; receives certificate issuance/renewal/expiry notifications. | `""`
`APP_HOSTNAME` | Domain for the app (e.g. `app.devpu.sh`). | `""`
`STATIC_HOSTNAME` | Domain for serving the static assets (e.g. CSS, JS libraries, images). Useful for caching. No trailing slahe | `APP_HOSTNAME`
`DEPLOY_DOMAIN` | Domain used for deployments (e.g. `devpush.app` if you want your deployments available at `*.devpush.app`). | `APP_HOSTNAME`
`SERVER_IP` | Public IP of the server | `""`
`SECRET_KEY` | Secret key for JWT tokens, sessions, and CSRF protection. | `""`
`ENCRYPTION_KEY` | Encryption key for sensitive data (e.g. GitHub tokens). | `""`
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
`UPLOAD_DIR` | Directory for file uploads. | `/app/upload`
`TRAEFIK_CONFIG_DIR` | Traefik configuration directory. | `/data/traefik`
`DEFAULT_CPU_QUOTA` | Default CPU quota for containers (microseconds). | `100000`
`DEFAULT_MEMORY_MB` | Default memory limit for containers (MB). | `4096`
`JOB_TIMEOUT` | Job timeout in seconds. | `320`
`JOB_COMPLETION_WAIT` | Job completion wait time in seconds. | `300`
`DEPLOYMENT_TIMEOUT` | Deployment timeout in seconds. | `300`
`LOG_LEVEL` | Logging level. | `WARNING`
`DB_ECHO` | Enable SQL query logging. | `false`
`ENV` | Environment (development/production). | `development`
`ACCESS_DENIED_MESSAGE` | Message shown to users who are denied access based on  [sign-in access control](#sign-in-access-control). | `Sign-in not allowed for this email.`
`ACCESS_DENIED_WEBHOOK` | Optional webhook to receive denied events (read more about [Sign-in access control](#sign-in-access-control)). | `""`
`LOGIN_ALERT_TITLE` | Title for a callout banner displayed on the login screen. Will be displayed only if either `LOGIN_ALERT_TITLE` or `LOGIN_ALERT_DESCRIPTION` is not empty. | `""`
`LOGIN_ALERT_DESCRIPTION` | Description for a callout banner displayed on the login screen. Will be displayed only if either `LOGIN_ALERT_TITLE` or `LOGIN_ALERT_DESCRIPTION` is not empty. | `""`

## GitHub App

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