#!/bin/bash
set -e

if [ -f "$(dirname "$0")/../../devops/.env.devops" ]; then
    source "$(dirname "$0")/../../devops/.env.devops"
fi

if [ -z "$HETZNER_API_TOKEN" ]; then
    echo -e "\033[31mError: HETZNER_API_TOKEN not found in devops/.env.devops\033[0m"
    exit 1
fi

echo "\033[31mCreating the server with Terraform\033[0m"
echo ""

cd "$(dirname "$0")/../../devops/terraform"
terraform init
terraform apply -var="hcloud_token=$HETZNER_API_TOKEN"

echo ""
echo -e "\033[1;32mServer successfully created!\033[0m"
echo -e "\033[1mRemember to add the server IP to devops/.env: $(terraform output -raw server_ip)\033[0m"