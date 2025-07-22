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
echo "The tunnel is now active in this terminal. Press Ctrl+C to close it."
ssh -N -L 15432:127.0.0.1:5432 "deploy@$SERVER_IP"

# Give the SSH connection a moment to fail
sleep 2

# Check if the process is still running
if pgrep -f "ssh -f -N -L 15432:127.0.0.1:5432 deploy@$SERVER_IP" > /dev/null; then
    echo "✅ SSH tunnel established successfully and is running in the background."
    echo "   You can now connect to localhost:15432 in TablePlus."
else
    echo "❌ Failed to establish SSH tunnel. Check your connection or run in verbose mode:"
    echo "   ssh -v -N -L 15432:127.0.0.1:5432 deploy@$SERVER_IP"
fi