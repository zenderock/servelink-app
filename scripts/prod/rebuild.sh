#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

RED="$(printf '\033[31m')"; GRN="$(printf '\033[32m')"; YEL="$(printf '\033[33m')"; BLD="$(printf '\033[1m')"; NC="$(printf '\033[0m')"
err(){ echo -e "${RED}ERR:${NC} $*" >&2; }
ok(){ echo -e "${GRN}$*${NC}"; }
info(){ echo -e "${BLD}$*${NC}"; }
warn(){ echo -e "${YEL}WARN:${NC} $*"; }

usage(){
  cat <<USG
Usage: rebuild.sh [--app-dir <path>] [--env-file <path>] [--no-cache] [--migrate] [--force]

Rebuild production Docker images and restart services.

  --app-dir PATH    App directory (default: \$PWD)
  --env-file PATH   Path to .env (default: ./\.env)
  --no-cache        Build without using Docker cache
  --migrate         Run DB migrations after rebuild
  --force           Force rebuild even if no changes detected
  -h, --help        Show this help
USG
  exit 0
}

app_dir="${APP_DIR:-$(pwd)}"; envf=".env"; no_cache=0; do_migrate=0; force=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-dir) app_dir="$2"; shift 2 ;;
    --env-file) envf="$2"; shift 2 ;;
    --no-cache) no_cache=1; shift ;;
    --migrate) do_migrate=1; shift ;;
    --force) force=1; shift ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

cd "$app_dir" || { err "app dir not found: $app_dir"; exit 1; }

# Validate environment variables
info "Validating environment..."
scripts/prod/check-env.sh --env-file "$envf"

# Check if there are any changes (unless forced)
if ((force==0)); then
  info "Checking for changes..."
  if git diff --quiet HEAD~1 HEAD -- .; then
    warn "No changes detected in the last commit. Use --force to rebuild anyway."
    read -p "Continue anyway? [y/N]: " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
      info "Rebuild cancelled."
      exit 0
    fi
  fi
fi

# Stop services
info "Stopping services..."
scripts/prod/stop.sh --app-dir "$app_dir" --down
ok "Services stopped."

# Clean up old images and containers
info "Cleaning up old images and containers..."
docker system prune -f --volumes || true
docker image prune -f || true

# Build images
info "Building Docker images..."
args=(-p servelink)
if ((no_cache==1)); then
  info "Building without cache..."
  docker compose "${args[@]}" build --no-cache --pull
else
  info "Building with cache..."
  docker compose "${args[@]}" build --pull
fi
ok "Images built successfully."

# Start services
info "Starting services..."
docker compose "${args[@]}" up -d --remove-orphans
ok "Services started."

# Wait for services to be healthy
info "Waiting for services to be healthy..."
sleep 10

# Check service health
info "Checking service health..."
if docker compose "${args[@]}" ps | grep -q "unhealthy"; then
  warn "Some services are unhealthy. Check logs with: docker compose logs"
else
  ok "All services are healthy."
fi

# Apply database migrations
if ((do_migrate==1)); then
  info "Applying migrations..."
  scripts/prod/db-migrate.sh --app-dir "$app_dir" --env-file "$envf"
fi

# Show final status
info "Final status:"
docker compose "${args[@]}" ps

ok "Rebuild completed successfully!"
info "You can view logs with: docker compose logs -f"
