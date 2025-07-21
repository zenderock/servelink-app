#!/bin/bash
set -e

if [ -f "$(dirname "$0")/../../.env.devops" ]; then
    source "$(dirname "$0")/../../.env.devops"
fi

if [ -z "$SERVER_IP" ]; then
    echo -e "\033[31mError: SERVER_IP not found in .env.devops\033[0m"
    exit 1
fi

if [ -z "$GITHUB_REPO" ]; then
    echo -e "\033[31mError: GITHUB_REPO not found in .env.devops\033[0m"
    exit 1
fi

COMPONENT=${1:-}

if [ -z "$COMPONENT" ]; then
    echo "Which component would you like to update?"
    echo "1) App containers (zero-downtime)"
    echo "2) Worker containers (graceful shutdown)"
    echo ""
    read -p "Select option (1-2): " choice
    
    case $choice in
        1) COMPONENT="app" ;;
        2) COMPONENT="worker" ;;
        *) echo "Invalid choice"; exit 1 ;;
    esac
fi

case $COMPONENT in
    app)
        echo "Updating app containers on the server ($SERVER_IP) with Ansible"
        PLAYBOOK="update-app.yml"
        ;;
    worker)
        echo "Updating worker containers on the server ($SERVER_IP) with Ansible"
        PLAYBOOK="update-worker.yml"
        ;;
    *)
        echo -e "\033[31mError: Invalid component '$COMPONENT'\033[0m"
        echo "Usage: $0 [app|worker]"
        exit 1
        ;;
esac

echo ""

cd "$(dirname "$0")/../../devops/ansible"
ansible-playbook -i inventories/deploy.yml playbooks/$PLAYBOOK \
  -e "server_ip=$SERVER_IP" \
  -e "github_repo=$GITHUB_REPO"

echo ""
echo -e "\033[1;32m${COMPONENT^} update complete!\033[0m" 