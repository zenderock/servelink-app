#!/bin/bash
set -e

if [ -f "$(dirname "$0")/../../.env.devops" ]; then
    source "$(dirname "$0")/../../.env.devops"
fi

if [ -z "$HETZNER_API_TOKEN" ]; then
    echo -e "\033[31mError: HETZNER_API_TOKEN not found in devops/.env.devops\033[0m"
    exit 1
fi

echo -e "\033[1mSelect server configuration:\033[0m"
echo ""

echo "Available regions:"
echo "  1) hil - Hillsboro (US West)"
echo "  2) ash - Ashburn (US East)"
echo "  3) nbg - Nuremberg (Germany)"
echo "  4) fsn - Falkenstein (Germany)"
echo "  5) hel - Helsinki (Finland)"
echo "  6) lhr - London (UK)"
echo "  7) sgp - Singapore"
echo "  8) syd - Sydney (Australia)"
echo ""

while true; do
    read -p "Select region (1-8, default: 1): " region_choice
    region_choice=${region_choice:-1}
    
    case $region_choice in
        1) region="hil"; break ;;
        2) region="ash"; break ;;
        3) region="nbg"; break ;;
        4) region="fsn"; break ;;
        5) region="hel"; break ;;
        6) region="lhr"; break ;;
        7) region="sgp"; break ;;
        8) region="syd"; break ;;
        *) echo "Invalid selection. Please choose 1-8." ;;
    esac
done

echo ""
echo "Available server types:"
echo "  1) cpx11 - 2 vCPU, 2GB RAM, 20GB SSD"
echo "  2) cpx21 - 3 vCPU, 4GB RAM, 40GB SSD"
echo "  3) cpx31 - 2 vCPU, 4GB RAM, 80GB SSD"
echo "  4) cpx41 - 4 vCPU, 8GB RAM, 160GB SSD"
echo "  5) cpx51 - 8 vCPU, 16GB RAM, 240GB SSD"
echo ""

while true; do
    read -p "Select server type (1-5, default: 3): " type_choice
    type_choice=${type_choice:-3}
    
    case $type_choice in
        1) server_type="cpx11"; break ;;
        2) server_type="cpx21"; break ;;
        3) server_type="cpx31"; break ;;
        4) server_type="cpx41"; break ;;
        5) server_type="cpx51"; break ;;
        *) echo "Invalid selection. Please choose 1-5." ;;
    esac
done

echo ""
echo -e "\033[1mSelected: $server_type in $region\033[0m"
echo ""
echo -e "\033[1mCreating the server with Terraform\033[0m"
echo ""

cd "$(dirname "$0")/../../devops/terraform"
terraform init
terraform apply -var="hcloud_token=$HETZNER_API_TOKEN" -var="region=$region" -var="server_type=$server_type"

echo ""
echo -e "\033[1;32mServer successfully created!\033[0m"
echo -e "\033[1mRemember to add the server IP to devops/.env: $(terraform output -raw server_ip)\033[0m"