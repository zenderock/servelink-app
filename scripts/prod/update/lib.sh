#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

RED="$(printf '\033[31m')"; GRN="$(printf '\033[32m')"; YEL="$(printf '\033[33m')"; BLD="$(printf '\033[1m')"; NC="$(printf '\033[0m')"
err(){ echo -e "${RED}ERR:${NC} $*" >&2; }
ok(){ echo -e "${GRN}$*${NC}"; }
info(){ echo -e "${BLD}$*${NC}"; }

# Generic blue-green update for a Docker Compose service
# Usage: blue_green_update <service_name> [timeout_seconds]
blue_green_update() {
  local service="$1"
  local timeout_s="${2:-300}"
  
  info "Executing blue-green update for '$service'..."
  
  local args=(-p devpush)

  # Build new image if Dockerfile has changed
  docker compose build "$service" || true

  local old_ids
  old_ids=$(docker ps --filter "name=devpush-$service" --format '{{.ID}}' || true)

  local cur_cnt
  cur_cnt=$(echo "$old_ids" | wc -w | tr -d ' ' || echo 0)
  
  local target=$((cur_cnt+1)); [[ $target -lt 1 ]] && target=1
  info "Scaling up to $target container(s)..."
  docker compose "${args[@]}" up -d --scale "$service=$target" --no-recreate

  local new_id=""
  info "Waiting for new container to appear..."
  for _ in $(seq 1 60); do
    local cur_ids
    cur_ids=$(docker ps --filter "name=devpush-$service" --format '{{.ID}}' | tr ' ' '\n' | sort)
    new_id=$(comm -13 <(echo "$old_ids" | tr ' ' '\n' | sort) <(echo "$cur_ids"))
    [[ -n "$new_id" ]] && break
    sleep 2
  done
  [[ -n "$new_id" ]] || { err "Failed to detect new container for '$service'"; return 1; }
  ok "New container detected: $new_id"

  info "Waiting for new container to be healthy (timeout: ${timeout_s}s)..."
  local deadline=$(( $(date +%s) + timeout_s ))
  while :; do
    local st
    # For services without a healthcheck, we just check for 'running'
    if docker inspect "$new_id" --format '{{.State.Health}}' >/dev/null 2>&1; then
      st=$(docker inspect "$new_id" --format '{{.State.Health.Status}}' 2>/dev/null || echo "starting")
      if [[ "$st" == "healthy" ]]; then
        ok "New container is healthy."
        break
      fi
    else
      st=$(docker inspect "$new_id" --format '{{.State.Status}}' 2>/dev/null || echo "starting")
      if [[ "$st" == "running" ]]; then
        ok "New container is running (no healthcheck)."
        break
      fi
    fi
    if [[ $(date +%s) -ge $deadline ]]; then
      err "New container for '$service' not ready within ${timeout_s}s. Status: $st"
      docker logs "$new_id"
      return 1
    fi
    sleep 5
  done
  
  if [[ -n "$old_ids" ]]; then
    info "Retiring old container(s): $old_ids"
    for id in $old_ids; do
      # For workers, this allows graceful shutdown via stop_grace_period
      docker stop "$id" || true
      docker rm "$id" || true
    done
  fi

  info "Scaling back to 1 container..."
  docker compose "${args[@]}" up -d --scale "$service=1" --no-recreate
  ok "Blue-green update for '$service' complete."
}
