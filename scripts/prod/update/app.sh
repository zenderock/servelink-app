#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

source "$(dirname "$0")/lib.sh"

trap 's=$?; err "Update for app failed (exit $s)"; exit $s' ERR

usage(){
  cat <<USG
Usage: app.sh [--app-dir <path>] [--timeout-seconds <n>]

Blue-green update for the app service (zero-downtime).

  --app-dir PATH       App directory (default: $PWD)
  --timeout-seconds N  Health wait timeout seconds (default: 300)
  -h, --help           Show this help
USG
  exit 0
}

app_dir="${APP_DIR:-$(pwd)}"; timeout_s=300
while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-dir) app_dir="$2"; shift 2 ;;
    --timeout-seconds) timeout_s="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

cd "$app_dir" || { err "app dir not found: $app_dir"; exit 1; }
scripts/prod/check-env.sh --env-file .env --quiet

blue_green_update "app" "$timeout_s"