#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

RED="$(printf '\033[31m')"; GRN="$(printf '\033[32m')"; YEL="$(printf '\033[33m')"; BLD="$(printf '\033[1m')"; NC="$(printf '\033[0m')"
err(){ echo -e "${RED}ERR:${NC} $*" >&2; }
ok(){ echo -e "${GRN}$*${NC}"; }

usage(){
  cat <<USG
Usage: check-env.sh [--env-file <path>] [--quiet]

Validate that all required environment variables are present and non-empty in .env file.

  --env-file PATH   Path to .env (default: ./.env)
  --quiet           Print only errors
USG
  exit 1
}

envf=".env"; quiet=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) envf="$2"; shift 2 ;;
    --quiet) quiet=1; shift ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

[[ -f "$envf" ]] || { err "Not found: $envf"; exit 1; }

# Required keys
req=(
  LE_EMAIL APP_HOSTNAME DEPLOY_DOMAIN EMAIL_SENDER_ADDRESS RESEND_API_KEY
  GITHUB_APP_ID GITHUB_APP_NAME GITHUB_APP_PRIVATE_KEY GITHUB_APP_WEBHOOK_SECRET
  GITHUB_APP_CLIENT_ID GITHUB_APP_CLIENT_SECRET
  SECRET_KEY ENCRYPTION_KEY POSTGRES_PASSWORD SERVER_IP
)

missing=()
for k in "${req[@]}"; do
  v="$(awk -F= -v k="$k" '$1==k{sub(/^[^=]*=/,""); print}' "$envf" | sed 's/^"\|"$//g')"
  [[ -n "$v" ]] || missing+=("$k")
done

if ((${#missing[@]})); then
  err "Missing values in $envf: ${missing[*]}"
  exit 1
fi

((quiet==1)) || ok "$envf valid"