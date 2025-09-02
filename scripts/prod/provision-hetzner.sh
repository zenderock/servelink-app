#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

RED="$(printf '\033[31m')"; GRN="$(printf '\033[32m')"; YEL="$(printf '\033[33m')"; BLD="$(printf '\033[1m')"; NC="$(printf '\033[0m')"
err(){ echo -e "${RED}ERR:${NC} $*" >&2; }
ok(){ echo -e "${GRN}$*${NC}"; }
info(){ echo -e "${BLD}$*${NC}"; }

usage(){
  cat <<USG
Usage: provision-hetzner.sh --token <token> [--user <login_user>]

Provision a Hetzner Cloud server and create an SSH-enabled sudo user.

  --token TOKEN   Hetzner API token (required)
  --user NAME     Login username to create (optional; defaults to current shell user; must not be 'root')

  -h, --help      Show this help
USG
  exit 1
}

# Parse arguments (require explicit token)
token=""; login_user_flag=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --token) token="$2"; shift 2 ;;
    --user) login_user_flag="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

[[ -n "$token" ]] || { err "Missing --token"; usage; }

command -v curl >/dev/null 2>&1 || { err "curl is required."; exit 1; }
command -v jq >/dev/null 2>&1 || { err "jq is required. Install with: brew install jq"; exit 1; }

api_get() {
    curl -sS -H "Authorization: Bearer $token" "https://api.hetzner.cloud/v1/$1"
}

api_post() {
    curl -sS -H "Authorization: Bearer $token" -H "Content-Type: application/json" -d "$2" "https://api.hetzner.cloud/v1/$1"
}

# Validate token early
info "Validating Hetzner API token..."
if ! api_get ssh_keys >/dev/null 2>&1; then
    err "Hetzner API token seems invalid or unauthorized. Visit https://console.hetzner.cloud/ to create a token."
    exit 1
fi

info "Select server configuration:"
echo ""

info "Fetching locations..."
locations_json=$(api_get locations)
loc_count=$(echo "$locations_json" | jq '.locations | length')
if [ "$loc_count" -eq 0 ]; then
    err "No locations returned by API."
    exit 1
fi

echo "Available regions:"
echo "$locations_json" | jq -r '.locations | to_entries[] | "  \(.key+1)) \(.value.name) - \(.value.description) (\(.value.city), \(.value.country))"'
echo ""

while true; do
    read -p "Select region (1-$loc_count, default: 1): " region_choice
    region_choice=${region_choice:-1}
    if [ "$region_choice" -ge 1 ] && [ "$region_choice" -le "$loc_count" ]; then
        idx=$((region_choice-1))
        region=$(echo "$locations_json" | jq -r ".locations[$idx].name")
        break
    else
        echo "Invalid selection. Please choose 1-$loc_count."
    fi
done

echo ""
types=("cpx11" "cpx21" "cpx31" "cpx41" "cpx51")
types_desc=(
  "2 vCPU, 2GB RAM, 20GB SSD"
  "3 vCPU, 4GB RAM, 40GB SSD"
  "2 vCPU, 4GB RAM, 80GB SSD"
  "4 vCPU, 8GB RAM, 160GB SSD"
  "8 vCPU, 16GB RAM, 240GB SSD"
)

echo "Available server types:"
for i in "${!types[@]}"; do
  printf "  %d) %s - %s\n" "$((i+1))" "${types[$i]}" "${types_desc[$i]}"
done
echo ""

while true; do
  read -p "Select server type (1-${#types[@]}, default: 3): " type_choice
  type_choice=${type_choice:-3}
  if [ "$type_choice" -ge 1 ] && [ "$type_choice" -le "${#types[@]}" ]; then
    idx=$((type_choice-1))
    server_type="${types[$idx]}"
    break
  else
    echo "Invalid selection. Please choose 1-${#types[@]}."
  fi
done

echo ""
info "Selected: $server_type in $region"
echo ""

default_name="devpush-$region"
read -p "Server name (default: $default_name): " server_name
server_name=${server_name:-$default_name}

# Determine login user (flag overrides default)
login_user="${login_user_flag:-${USER:-admin}}"
if [[ "$login_user" == "root" ]]; then
    err "Refusing to create 'root'. Choose a non-root username."
    exit 1
fi

info "Fetching SSH keys from Hetzner project..."
ssh_json=$(api_get ssh_keys)
ssh_count=$(echo "$ssh_json" | jq '.ssh_keys | length')
if [ "$ssh_count" -eq 0 ]; then
    err "No SSH keys found in your Hetzner project."
    echo "Add an SSH key in the Hetzner Cloud Console (Security → SSH Keys): https://console.hetzner.cloud/"
    echo "Then re-run this script."
    exit 1
fi
ssh_ids=$(echo "$ssh_json" | jq '[.ssh_keys[].id]')
ssh_pub_lines=$(echo "$ssh_json" | jq -r '.ssh_keys[].public_key' | sed 's/^/      - /')

user_data=$(cat <<EOF
#cloud-config
users:
  - name: $login_user
    groups: sudo
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
$ssh_pub_lines
ssh_pwauth: false
disable_root: true
package_update: true
package_upgrade: true
EOF
)

payload=$(jq -n \
    --arg name "$server_name" \
    --arg st "$server_type" \
    --arg img "ubuntu-24.04" \
    --arg loc "$region" \
    --arg user_data "$user_data" \
    --argjson ssh_keys "$ssh_ids" \
    '{name:$name, server_type:$st, image:$img, location:$loc, ssh_keys:$ssh_keys, user_data:$user_data, start_after_create:true}')

info "Creating server via Hetzner API..."
create_resp=$(api_post servers "$payload")
server_id=$(echo "$create_resp" | jq -r '.server.id // empty')
if [ -z "$server_id" ]; then
    err "Failed to create server. Response below:"
    echo "$create_resp"
    exit 1
fi

info "Waiting for server to be running..."
for i in $(seq 1 60); do
    status_json=$(api_get servers/$server_id)
    status=$(echo "$status_json" | jq -r '.server.status')
    if [ "$status" = "running" ]; then
        break
    fi
    sleep 2
done

server_json=$(api_get servers/$server_id)
server_ip=$(echo "$server_json" | jq -r '.server.public_net.ipv4.ip')
  
echo ""
ok "Server successfully created!"
info "Server name: $server_name"
info "Server IP: $server_ip"

echo ""
echo "Next steps:"
echo "- SSH in: ssh $login_user@$server_ip"
echo "- Install /dev/push: curl -fsSL https://raw.githubusercontent.com/hunvreus/devpush/main/scripts/prod/install.sh | sudo bash"
echo "- Optional: harden system: curl -fsSL https://raw.githubusercontent.com/hunvreus/devpush/main/scripts/prod/harden.sh | sudo bash"
