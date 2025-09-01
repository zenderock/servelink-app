#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

source "$(dirname "$0")/lib.sh"

trap 's=$?; err "Update for worker-arq failed (exit $s)"; exit $s' ERR

usage(){
  cat <<USG
Usage: worker-arq.sh [--app-dir <path>] [--timeout-seconds <n>]

Drain-aware blue-green update for the ARQ worker service.

  --app-dir PATH       App directory (default: $PWD)
  --timeout-seconds N  Health wait timeout seconds (default: 600)
  -h, --help           Show this help
USG
  exit 0
}

app_dir="${APP_DIR:-$(pwd)}"; timeout_s=600
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

blue_green_update "worker-arq" "$timeout_s"