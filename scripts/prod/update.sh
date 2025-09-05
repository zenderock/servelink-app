#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

RED="$(printf '\033[31m')"; GRN="$(printf '\033[32m')"; YEL="$(printf '\033[33m')"; BLD="$(printf '\033[1m')"; NC="$(printf '\033[0m')"
err(){ echo -e "${RED}ERR:${NC} $*" >&2; }
ok(){ echo -e "${GRN}$*${NC}"; }
info(){ echo -e "${BLD}$*${NC}"; }

trap 's=$?; echo -e "${RED}Update failed (exit $s)${NC}"; exit $s' ERR

usage(){
  cat <<USG
Usage: update.sh [--app-dir <path>] [--ref <tag>] [--include-prerelease] [--all | --components app,worker-arq,worker-monitor | --full] [--no-pull] [--no-migrate] [--yes|-y]

Update /dev/push by Git tag; supports blue-green app/worker updates or full restart.

  --app-dir PATH    App directory (default: $PWD)
  --ref TAG         Git tag to update to (default: latest tag)
  --include-prerelease  Allow beta/rc tags when selecting latest
  --all             Update app,worker-arq,worker-monitor
  --components CSV  Comma-separated list of services to update
  --full            Full stack update (down whole stack, then up). Causes downtime
  --no-pull         Skip docker compose pull
  --no-migrate      Do not run DB migrations after app update
  --yes, -y         Non-interactive yes to prompts
  -h, --help        Show this help
USG
  exit 0
}

app_dir="${APP_DIR:-$(pwd)}"; ref=""; comps=""; do_all=0; do_full=0; pull=1; migrate=1; include_pre=0; yes=0; skip_components=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-dir) app_dir="$2"; shift 2 ;;
    --ref) ref="$2"; shift 2 ;;
    --include-prerelease) include_pre=1; shift ;;
    --all) do_all=1; shift ;;
    --components) comps="$2"; shift 2 ;;
    --full) do_full=1; shift ;;
    --no-pull) pull=0; shift ;;
    --no-migrate) migrate=0; shift ;;
    --yes|-y) yes=1; shift ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

cd "$app_dir" || { err "app dir not found: $app_dir"; exit 1; }

# Validate environment variables
scripts/prod/check-env.sh --env-file .env --quiet

# Resolve latest tag from GitHub
info "Resolving latest tag..."
if [[ -z "$ref" ]]; then
  if ((include_pre==1)); then
    ref="$(git ls-remote --tags --refs origin | awk -F/ '{print $3}' | sort -V | tail -1)"
  else
    ref="$(git ls-remote --tags --refs origin | awk -F/ '{print $3}' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1)"
    [[ -n "$ref" ]] || ref="$(git ls-remote --tags --refs origin | awk -F/ '{print $3}' | sort -V | tail -1)"
  fi
  if [[ -z "$ref" ]]; then
    info "No tags found; falling back to 'main'"
    ref="main"
  fi
fi

# Get code from GitHub
info "Fetching and checking out: $ref"
# Try branch first, then tag; reset to FETCH_HEAD either way
git fetch --depth 1 origin "$ref" || git fetch --depth 1 origin "refs/tags/$ref"
git reset --hard FETCH_HEAD

# Skip work if commit unchanged (use system state file)
version_file="/var/lib/devpush/version.json"
prev_commit="$(jq -r '.git_commit' "$version_file" 2>/dev/null || echo "")"
current_commit="$(git rev-parse --verify HEAD)"
if [[ -n "$prev_commit" && "$prev_commit" == "$current_commit" ]]; then
  ok "Already up-to-date ($current_commit). Skipping component updates."
  exit 0
fi

# Update Docker images
args=(-p devpush)
if ((pull==1)); then
  info "Pulling images..."
  docker compose "${args[@]}" pull || true
fi

# Option1: Full update (with downtime)
if ((do_full==1)); then
  if ((do_all==1)) || [[ -n "$comps" ]]; then
    err "--full cannot be combined with --all or --components"
    exit 1
  fi
  if ((yes!=1)); then
    echo -e "${YEL}Warning:${NC} This will stop ALL services, update, and restart the whole stack. Downtime WILL occur."
    read -p "Proceed? [y/N]: " ans
    [[ "$ans" =~ ^[Yy]$ ]] || { info "Aborted."; exit 1; }
  fi
  info "Full stack update: taking stack down, then up"
  docker compose "${args[@]}" down --remove-orphans || true
  docker compose "${args[@]}" up -d --remove-orphans
  ok "Full stack updated"
  skip_components=1
fi

# Option2: Components update (no downtime for app and workers)
if ((do_all==1)); then
  comps="app,worker-arq,worker-monitor"
elif [[ -z "$comps" ]]; then
  echo "Select components to update (infra services not listed here):"
  echo "1) app + workers (app, worker-arq, worker-monitor)"
  echo "2) app"
  echo "3) worker-arq"
  echo "4) worker-monitor"
  echo
  echo "Tip: use --components traefik,redis,... to update infra; use --full for full stack restart (downtime)."
  read -r ch
  case "$ch" in
    1) comps="app,worker-arq,worker-monitor" ;;
    2) comps="app" ;;
    3) comps="worker-arq" ;;
    4) comps="worker-monitor" ;;
    *) err "invalid choice"; exit 1 ;;
  esac
fi

IFS=',' read -ra C <<< "$comps"

simple_restart(){
  local s="$1"
  info "Restarting: $s"
  docker compose "${args[@]}" up -d --no-deps --force-recreate "$s"
  ok "$s restarted"
}

if ((skip_components==0)); then
  for s in "${C[@]}"; do
    case "$s" in
      app)
        scripts/prod/update/app.sh --app-dir "$app_dir"
        ;;
      worker-arq)
        scripts/prod/update/worker-arq.sh --app-dir "$app_dir"
        ;;
      worker-monitor)
        scripts/prod/update/worker-monitor.sh --app-dir "$app_dir"
        ;;
      traefik|loki|redis|docker-proxy|pgsql)
        simple_restart "$s"
        ;;
      *) err "unknown component: $s"; exit 1 ;;
    esac
  done
fi

# Apply database migrations
if ((skip_components==0)) && [[ "$comps" == *"app"* ]] && ((migrate==1)); then
  info "Running migrations..."
  scripts/prod/db-migrate.sh --app-dir "$app_dir" --env-file .env
fi

# Update install metadata (version.json)
commit=$(git rev-parse --verify HEAD)
ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
install -d -m 0755 /var/lib/devpush
old_id="$(jq -r '.install_id' /var/lib/devpush/version.json 2>/dev/null || true)"
[[ -n "$old_id" && "$old_id" != "null" ]] || old_id=$(cat /proc/sys/kernel/random/uuid)
printf '{"install_id":"%s","git_ref":"%s","git_commit":"%s","updated_at":"%s"}\n' "$old_id" "$ref" "$commit" "$ts" > /var/lib/devpush/version.json

ok "Update complete to $ref"

# Send telemetry
payload=$(jq -c --arg ev "update" '. + {event: $ev}' /var/lib/devpush/version.json 2>/dev/null || echo "")
if [[ -n "$payload" ]]; then
  curl -fsSL -X POST -H 'Content-Type: application/json' -d "$payload" https://api.devpu.sh/v1/telemetry >/dev/null 2>&1 || true
fi