#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

RED="$(printf '\033[31m')"; GRN="$(printf '\033[32m')"; YEL="$(printf '\033[33m')"; BLD="$(printf '\033[1m')"; NC="$(printf '\033[0m')"
err(){ echo -e "${RED}ERR:${NC} $*" >&2; }
ok(){ echo -e "${GRN}$*${NC}"; }
info(){ echo -e "${BLD}$*${NC}"; }

usage(){
  cat <<USG
Usage: stop.sh [--app-dir <path>] [--down]

Stop production services. Use --down for a hard stop with removal of orphans.

  --app-dir PATH    App directory (default: \$PWD)
  --down            Use 'docker compose down --remove-orphans' (hard stop)
  -h, --help        Show this help
USG
  exit 0
}

app_dir="${APP_DIR:-$(pwd)}"; hard=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-dir) app_dir="$2"; shift 2 ;;
    --down) hard=1; shift ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

cd "$app_dir" || { err "app dir not found: $app_dir"; exit 1; }

info "Stopping services..."
args=(-p devpush)
if ((hard==1)); then
  docker compose "${args[@]}" down --remove-orphans
else
  docker compose "${args[@]}" stop
fi
ok "Stopped."