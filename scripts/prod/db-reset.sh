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
Usage: db-reset.sh [--app-dir <path>] [--env-file <path>] [--force]

⚠️  DANGER: Drops and recreates the 'public' schema of the Postgres database.
This will DELETE ALL DATA in the database!

  --app-dir PATH    App directory (default: \$PWD)
  --env-file PATH   Path to .env (default: ./\.env)
  --force           Skip confirmation prompt
  -h, --help        Show this help
USG
  exit 0
}

app_dir="${APP_DIR:-$(pwd)}"; envf=".env"; force=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-dir) app_dir="$2"; shift 2 ;;
    --env-file) envf="$2"; shift 2 ;;
    --force) force=1; shift ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

cd "$app_dir" || { err "app dir not found: $app_dir"; exit 1; }

# Load environment variables
if [ -f "$envf" ]; then
  # shellcheck disable=SC1090
  source "$envf"
else
  err "Environment file not found: $envf"
  exit 1
fi

container=${DB_CONTAINER:-pgsql}
db_user=${POSTGRES_USER:-servelink-app}
db_name=${POSTGRES_DB:-servelink}

# Confirmation prompt
if ((force==0)); then
  warn "⚠️  DANGER ZONE ⚠️"
  warn "This will DROP and recreate schema 'public' in database '$db_name'."
  warn "ALL DATA WILL BE PERMANENTLY DELETED!"
  echo ""
  read -p "Type 'DELETE ALL DATA' to confirm: " -r
  echo
  if [[ "$REPLY" != "DELETE ALL DATA" ]]; then
    info "Reset cancelled."
    exit 0
  fi
  
  # Double confirmation
  read -p "Are you absolutely sure? [yes/NO]: " -n 3 -r
  echo
  if [[ ! $REPLY =~ ^yes$ ]]; then
    info "Reset cancelled."
    exit 0
  fi
fi

# Reset database schema
info "Resetting database schema..."
if docker compose -p servelink exec -T "$container" psql -U "$db_user" -d "$db_name" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" >/dev/null 2>&1; then
  ok "Database schema reset successfully."
  warn "You need to run migrations: scripts/prod/db-migrate.sh"
else
  err "Failed to reset database schema."
  exit 1
fi
