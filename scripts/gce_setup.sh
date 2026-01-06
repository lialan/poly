#!/bin/bash
# GCE setup script for poly-collector
# Run this on a fresh Debian/Ubuntu GCE instance

set -e

echo "=== Setting up poly-collector on GCE ==="

# Install system dependencies
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv git

# Clone repo (or copy files)
cd ~
if [ -d "poly" ]; then
    cd poly && git pull
else
    git clone https://github.com/YOUR_USERNAME/poly.git  # Update this
    cd poly
fi

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Set environment variables
export PYTHONPATH=src
export DB_BACKEND=bigtable
export BIGTABLE_PROJECT_ID=poly-collector
export BIGTABLE_INSTANCE_ID=poly-data
export COLLECT_INTERVAL=5

echo "=== Setup complete ==="
echo "Run the collector with:"
echo "  source .venv/bin/activate"
echo "  PYTHONPATH=src DB_BACKEND=bigtable BIGTABLE_PROJECT_ID=poly-collector BIGTABLE_INSTANCE_ID=poly-data python scripts/cloudrun_collector.py"
