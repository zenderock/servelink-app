#!/bin/bash
set -e

if [ -f "$(dirname "$0")/../../.env" ]; then
    source "$(dirname "$0")/../../.env"
fi

if [ -z "$NGROK_CUSTOM_DOMAIN" ]; then
    echo -e "\033[31mError: NGROK_CUSTOM_DOMAIN not found in .env\033[0m"
    exit 1
fi

ngrok http 80 --domain=$NGROK_CUSTOM_DOMAIN --host-header=localhost