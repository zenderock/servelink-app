#!/bin/bash
set -e

if [ -f "$(dirname "$0")/../../devops/.env.devops" ]; then
    source "$(dirname "$0")/../../devops/.env.devops"
fi

if [ -z "$SERVER_IP" ]; then
    echo -e "\033[31mError: SERVER_IP not found in devops/.env.devops\033[0m"
    exit 1
fi

echo "\033[31mSetting up the server ($SERVER_IP) with Ansible\033[0m"
echo ""

cd "$(dirname "$0")/../../devops/ansible"
ansible-playbook -i inventories/setup.yml playbooks/setup.yml \
  -e "server_ip=$SERVER_IP"

echo ""
echo -e "\033[1;32mServer setup complete!\033[0m"
echo -e "\033[1mRemember to add the deploy key to your GitHub.\033[0m"