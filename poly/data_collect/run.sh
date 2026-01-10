#!/bin/bash
# CCXT.pro Binance Depth Collector Runner
# Usage: ./run.sh [--step 0.00002] [--steps 40] [--interval 1]

STEP=${STEP:-0.00002}
STEPS=${STEPS:-40}
INTERVAL=${INTERVAL:-1}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --step) STEP="$2"; shift 2 ;;
        --steps) STEPS="$2"; shift 2 ;;
        --interval) INTERVAL="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

CONTAINER_NAME="binance-collector"
IMAGE_NAME="binance-collector:latest"

echo "=============================================="
echo "CCXT.pro Binance Depth Collector"
echo "=============================================="
echo "Step:     $STEP (0.002%)"
echo "Steps:    $STEPS"
echo "Interval: ${INTERVAL}s"
echo "=============================================="

# Stop existing container
docker stop $CONTAINER_NAME 2>/dev/null
docker rm $CONTAINER_NAME 2>/dev/null

# Start new container
docker run -d \
    --name $CONTAINER_NAME \
    --restart=unless-stopped \
    -e DB_BACKEND=bigtable \
    -e BIGTABLE_PROJECT_ID=poly-collector \
    -e BIGTABLE_INSTANCE_ID=poly-data \
    $IMAGE_NAME \
    python poly/data_collect/ccxt_depth_collector.py \
        --step $STEP \
        --steps $STEPS \
        --interval $INTERVAL

echo ""
echo "Container started. Waiting for logs..."
sleep 5
docker logs $CONTAINER_NAME --tail 20
