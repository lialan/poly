#!/bin/bash
# CCXT.pro Binance Depth Collector - Startup Script
# Location: Singapore (asia-southeast1-b)

set -e

# Configuration
CONTAINER_NAME="binance-collector"
IMAGE_NAME="binance-collector:latest"

# Collector parameters (0.002% step, 40 steps = 0.08% total depth)
STEP=0.00002
STEPS=40
INTERVAL=1

# Bigtable configuration
DB_BACKEND="bigtable"
BIGTABLE_PROJECT_ID="poly-collector"
BIGTABLE_INSTANCE_ID="poly-data"

echo "=============================================="
echo "CCXT.pro Binance Depth Collector"
echo "=============================================="
echo "Step:         ${STEP} (0.002%)"
echo "Steps:        ${STEPS}"
echo "Total depth:  0.08%"
echo "Interval:     ${INTERVAL}s"
echo "Backend:      ${DB_BACKEND}"
echo "Project:      ${BIGTABLE_PROJECT_ID}"
echo "Instance:     ${BIGTABLE_INSTANCE_ID}"
echo "=============================================="

# Stop and remove existing container if running
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Stopping existing container..."
    docker stop ${CONTAINER_NAME} 2>/dev/null || true
    docker rm ${CONTAINER_NAME} 2>/dev/null || true
fi

# Start new container
echo "Starting container..."
docker run -d \
    --name ${CONTAINER_NAME} \
    --restart=unless-stopped \
    -e DB_BACKEND=${DB_BACKEND} \
    -e BIGTABLE_PROJECT_ID=${BIGTABLE_PROJECT_ID} \
    -e BIGTABLE_INSTANCE_ID=${BIGTABLE_INSTANCE_ID} \
    ${IMAGE_NAME} \
    python poly/data_collect/ccxt_depth_collector.py \
        --step ${STEP} \
        --steps ${STEPS} \
        --interval ${INTERVAL}

echo ""
echo "Container started. Checking logs..."
sleep 3
docker logs ${CONTAINER_NAME} --tail 15
