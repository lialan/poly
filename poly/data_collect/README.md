# Binance Depth Collector

CCXT.pro based Binance orderbook depth collector that stores aggregated depth data to Google Cloud Bigtable.

## Overview

This collector uses ccxt.pro WebSocket to stream BTC/USDT orderbook data from Binance and aggregates it into log-delta buckets for efficient storage and analysis.

### Features

- Real-time orderbook collection via WebSocket (ccxt.pro)
- Log-delta bucket aggregation (configurable step size and count)
- Epoch timestamp aligned to 1-second boundaries
- Stores to Google Cloud Bigtable
- Docker containerized for easy deployment

### Collection Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--step` | 0.00002 | Log-delta step size (0.002%) |
| `--steps` | 40 | Number of buckets (total depth: 0.08%) |
| `--interval` | 1 | Collection interval in seconds |

### Data Format

Each snapshot contains:
- `epoch`: Unix timestamp (1-second aligned)
- `best_bid`, `best_ask`: Current best prices
- `bid_buckets`: Array of 40 USDT values (liquidity per bucket)
- `ask_buckets`: Array of 40 USDT values (liquidity per bucket)
- `step_pct`, `num_steps`: Aggregation parameters

## Local Development

### Prerequisites

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Run Locally (Dry Run)

```bash
# From project root
PYTHONPATH=src:. python poly/data_collect/ccxt_depth_collector.py --dry-run
```

### Run Locally with Bigtable

```bash
export DB_BACKEND=bigtable
export BIGTABLE_PROJECT_ID=poly-collector
export BIGTABLE_INSTANCE_ID=poly-data

PYTHONPATH=src:. python poly/data_collect/ccxt_depth_collector.py \
    --step 0.00002 \
    --steps 40 \
    --interval 1
```

## Docker Deployment

### Build Image

```bash
# From project root
docker build -f poly/data_collect/Dockerfile -t binance-collector:latest .
```

### Run Container

```bash
docker run -d \
    --name binance-collector \
    --restart=unless-stopped \
    -e DB_BACKEND=bigtable \
    -e BIGTABLE_PROJECT_ID=poly-collector \
    -e BIGTABLE_INSTANCE_ID=poly-data \
    binance-collector:latest \
    python poly/data_collect/ccxt_depth_collector.py \
        --step 0.00002 \
        --steps 40 \
        --interval 1
```

### Using the Run Script

```bash
# Default parameters
./poly/data_collect/run.sh

# Custom parameters
./poly/data_collect/run.sh --step 0.00002 --steps 40 --interval 1
```

## Google Cloud Deployment

### Prerequisites

1. GCP project with Bigtable enabled
2. GCE instance with Docker installed
3. Service account with Bigtable access

### GCE Instance Setup

```bash
# Create instance (e2-micro is sufficient)
gcloud compute instances create binance-collector \
    --zone=asia-southeast1-b \
    --machine-type=e2-micro \
    --image-family=debian-11 \
    --image-project=debian-cloud \
    --scopes=https://www.googleapis.com/auth/bigtable.data

# SSH into instance
gcloud compute ssh binance-collector --zone=asia-southeast1-b

# Install Docker
sudo apt-get update
sudo apt-get install -y docker.io
sudo usermod -aG docker $USER
newgrp docker
```

### Deploy to GCE

```bash
# From local machine - sync files to GCE
gcloud compute scp --recurse \
    poly/data_collect/ \
    src/poly/ \
    binance-collector:~/binance-collector/ \
    --zone=asia-southeast1-b

# SSH and build
gcloud compute ssh binance-collector --zone=asia-southeast1-b --command='
    cd ~/binance-collector
    docker build -t binance-collector:latest .
    ./run.sh --step 0.00002 --steps 40 --interval 1
'
```

### Alternative: Using rsync

```bash
# Sync source code
rsync -avz --exclude='*.pyc' --exclude='__pycache__' \
    -e "gcloud compute ssh binance-collector --zone=asia-southeast1-b --" \
    src/poly/ :~/binance-collector/src/poly/

rsync -avz --exclude='*.pyc' --exclude='__pycache__' \
    -e "gcloud compute ssh binance-collector --zone=asia-southeast1-b --" \
    poly/data_collect/ :~/binance-collector/poly/data_collect/
```

### Monitor Logs

```bash
# View recent logs
gcloud compute ssh binance-collector --zone=asia-southeast1-b \
    --command='docker logs binance-collector --tail 30'

# Follow logs
gcloud compute ssh binance-collector --zone=asia-southeast1-b \
    --command='docker logs binance-collector -f'
```

### Restart Collector

```bash
gcloud compute ssh binance-collector --zone=asia-southeast1-b \
    --command='cd ~/binance-collector && ./run.sh'
```

## AWS Deployment

### EC2 Setup

```bash
# Launch EC2 instance (t3.micro is sufficient)
aws ec2 run-instances \
    --image-id ami-0abcdef1234567890 \
    --instance-type t3.micro \
    --key-name your-key \
    --security-groups docker-sg

# SSH and install Docker
ssh -i your-key.pem ec2-user@<instance-ip>
sudo yum update -y
sudo yum install -y docker
sudo service docker start
sudo usermod -aG docker ec2-user
```

### Deploy to EC2

```bash
# Sync files
scp -r -i your-key.pem \
    poly/data_collect/ src/poly/ \
    ec2-user@<instance-ip>:~/binance-collector/

# Build and run
ssh -i your-key.pem ec2-user@<instance-ip> '
    cd ~/binance-collector
    docker build -t binance-collector:latest .
    ./run.sh
'
```

## Bigtable Configuration

### Table Name

The collector writes to: `binance_btc_depth`

### Row Key Format

```
{inverted_timestamp}#{symbol}
```

Example: `8231946041#BTCUSDT`

### Column Family: `data`

| Column | Type | Description |
|--------|------|-------------|
| `price` | float | Mid price |
| `orderbook` | JSON | Aggregated depth data |
| `timestamp` | float | Collection timestamp |

### Create Table (if needed)

```bash
cbt -project=poly-collector -instance=poly-data createtable binance_btc_depth
cbt -project=poly-collector -instance=poly-data createfamily binance_btc_depth data
```

## Troubleshooting

### Check Container Status

```bash
docker ps -a
docker logs binance-collector --tail 50
```

### Common Issues

1. **ModuleNotFoundError**: Ensure PYTHONPATH includes both `src` and project root
2. **Bigtable permission denied**: Check service account has Bigtable Data User role
3. **WebSocket disconnects**: The collector auto-reconnects, check for rate limiting

### Health Check

```bash
# Check if collecting (should see epoch incrementing)
docker logs binance-collector --tail 5

# Expected output:
# [14:12:45] (0.25s) | BTC/USDT $90,538.46/$90,538.47 | spread: 0.0bps | bids: $8.5M | asks: $6.0M | epoch: 1768054365
```

## Current Deployments

| Location | Instance | IP | Status |
|----------|----------|-----|--------|
| Singapore (asia-southeast1-b) | binance-collector | 35.185.188.114 | Active |

## Files

```
poly/data_collect/
├── __init__.py              # Package exports
├── ccxt_depth_collector.py  # Main collector script
├── Dockerfile               # Docker build file
├── requirements.txt         # Python dependencies
├── run.sh                   # Container runner script
└── README.md                # This file
```
