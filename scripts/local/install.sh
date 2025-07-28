#!/bin/bash
set -e

echo "Checking Colima installation..."

# Check if colima is installed
if ! command -v colima &> /dev/null; then
    echo "Colima not found. Installing..."
    
    # Install colima using Homebrew
    if command -v brew &> /dev/null; then
        brew install colima
    else
        echo "Homebrew not found. Please install Homebrew first:"
        echo "https://brew.sh"
        exit 1
    fi
else
    echo "Colima is already installed."
fi

# Check if Loki driver is available
if colima list | grep -q "loki"; then
    echo "Loki driver is already configured."
else
    echo "Adding Loki driver..."
    
    # Stop any running colima instance
    colima stop 2>/dev/null || true
    
    # Start colima with Loki driver
    colima start --driver=loki --memory=4 --cpu=2 --disk=100
fi

echo "Colima setup complete!"