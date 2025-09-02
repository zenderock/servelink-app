#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

source "$(dirname "$0")/lib.sh"

trap 's=$?; err "Update for worker-monitor failed (exit $s)"; exit $s' ERR

usage(){
  cat <<USG
Usage: worker-monitor.sh [--app-dir <path>]

In-place restart for the monitor worker (single-instance service).

  --app-dir PATH       App directory (default: $PWD)
  --timeout-seconds N  Health wait timeout seconds (default: 60)
  -h, --help           Show this help
USG
  exit 0
}

app_dir="${APP_DIR:-$(pwd)}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-dir) app_dir="$2"; shift 2 ;;
    --timeout-seconds) shift 2 ;; # deprecated
    -h|--help) usage ;;
    *) usage ;;
  esac
done

cd "$app_dir" || { err "app dir not found: $app_dir"; exit 1; }
scripts/prod/check-env.sh --env-file .env --quiet

info "Rebuilding worker-monitor (cached)..."
docker compose -p devpush build worker-monitor | cat
info "Recreating worker-monitor..."
docker compose -p devpush up -d --no-deps --force-recreate worker-monitor
ok "worker-monitor restarted"