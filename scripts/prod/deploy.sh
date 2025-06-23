#!/bin/bash
set -e

if [ -f "$(dirname "$0")/../../devops/.env.devops" ]; then
    source "$(dirname "$0")/../../devops/.env.devops"
fi

if [ -z "$SERVER_IP" ]; then
    echo -e "\033[31mError: SERVER_IP not found in devops/.env.devops\033[0m"
    exit 1
fi

echo "Deploying the app on the server ($SERVER_IP) with Ansible"
echo ""

cd "$(dirname "$0")/../../devops/ansible"
ansible-playbook -i inventories/deploy.yml playbooks/deploy.yml \
  -e "server_ip=$SERVER_IP" \
  -e "github_repo=$GITHUB_REPO"

echo ""
echo -e "\033[1;32mDeployment complete!\033[0m"