#!/bin/bash

# Source the .env.devops file if it exists
if [ -f "$(dirname "$0")/../../.env.devops" ]; then
    source "$(dirname "$0")/../../.env.devops"
fi

# Check if SERVER_IP is set
if [ -z "$SERVER_IP" ]; then
    echo "Error: SERVER_IP is not set. Please define it in .env.devops."
    exit 1
fi

echo "Creating SSH tunnel to $SERVER_IP..."
ssh -N -L 15432:127.0.0.1:5432 "deploy@$SERVER_IP"