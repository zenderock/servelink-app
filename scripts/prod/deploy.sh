#!/bin/bash
set -e

if [ -f "$(dirname "$0")/../../devops/.env.devops" ]; then
    source "$(dirname "$0")/../../devops/.env.devops"
fi

if [ -z "$SERVER_IP" ]; then
    echo -e "\033[31mError: SERVER_IP not found in devops/.env.devops\033[0m"
    exit 1
fi


NO_CACHE=true
PRUNE=false
for a in "$@"; do
  [ "$a" = "--cache" ] && NO_CACHE=false
  [ "$a" = "--prune" ] && PRUNE=true
done

echo "Deploying the app on the server ($SERVER_IP) with Ansible"
echo ""

cd "$(dirname "$0")/../../devops/ansible"
ansible-playbook -i inventories/deploy.yml playbooks/deploy.yml \
  -e "server_ip=$SERVER_IP" \
  -e "github_repo=$GITHUB_REPO" \
  -e "docker_no_cache=$NO_CACHE" \
  -e "docker_prune=$PRUNE"

echo ""
echo -e "\033[1;32mDeployment complete!\033[0m"