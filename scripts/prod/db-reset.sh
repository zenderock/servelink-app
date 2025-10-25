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
Usage: db-reset.sh [--app-dir <path>] [--force]

⚠️  DANGER: Drops and recreates the 'public' schema of the Postgres database.
This will DELETE ALL DATA in the database!

  --app-dir PATH    App directory (default: \$PWD)
  --force           Skip all prompts (USE WITH CAUTION)
  -h, --help        Show this help

The script will ask for database configuration interactively.
USG
  exit 0
}

app_dir="${APP_DIR:-$(pwd)}"; force=0
container="pgsql"; db_user="servelink-app"; db_name="servelink"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-dir) app_dir="$2"; shift 2 ;;
    --force) force=1; shift ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

cd "$app_dir" || { err "app dir not found: $app_dir"; exit 1; }

# Ask for database configuration (unless --force is used)
if ((force==0)); then
  info "Database Configuration"
  echo ""

  read -p "Docker container name [pgsql]: " input_container
  container=${input_container:-$container}

  read -p "Postgres user [servelink-app]: " input_user
  db_user=${input_user:-$db_user}

  read -p "Postgres database [servelink]: " input_db
  db_name=${input_db:-$db_name}

  echo ""
fi

info "Using configuration:"
info "  Container: $container"
info "  User: $db_user"
info "  Database: $db_name"
echo ""

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
