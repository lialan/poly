# GCE Deployment Guide

This guide covers deploying the Polymarket data collector to Google Compute Engine (GCE) with Bigtable storage.

## Prerequisites

1. **Google Cloud SDK** installed and configured
2. **GCP Project** with billing enabled
3. **Bigtable instance** (see [Bigtable Setup](#bigtable-setup))

## Current Production Setup

| Resource | Value |
|----------|-------|
| Instance | `poly-collector` |
| Type | e2-micro (free tier eligible) |
| Zone | us-central1-a |
| External IP | 35.224.204.208 |
| Project | poly-collector |
| Bigtable Instance | poly-data |

## Quick Deploy (Code Updates)

```bash
# Sync code to GCE
rsync -avz --exclude='*.pyc' --exclude='__pycache__' \
  -e "ssh -i ~/.ssh/google_compute_engine" \
  src/poly/ lialan@35.224.204.208:~/poly/src/poly/

scp -i ~/.ssh/google_compute_engine scripts/cloudrun_collector.py \
  lialan@35.224.204.208:~/poly/scripts/

# Restart service
gcloud compute ssh poly-collector --zone=us-central1-a --project=poly-collector \
  --command='sudo systemctl restart poly-collector'
```

## First-Time Setup

### 1. Enable Required APIs

```bash
gcloud services enable compute.googleapis.com
gcloud services enable bigtable.googleapis.com
gcloud services enable bigtableadmin.googleapis.com
```

### 2. Create Bigtable Instance

```bash
# Development instance (free tier eligible, no SLA)
gcloud bigtable instances create poly-data \
    --display-name="Polymarket Data" \
    --cluster-config=id=poly-cluster,zone=us-central1-a \
    --instance-type=DEVELOPMENT

# OR Production instance (~$0.65/hour per node)
gcloud bigtable instances create poly-data \
    --display-name="Polymarket Data" \
    --cluster-config=id=poly-cluster,zone=us-central1-a,nodes=1
```

### 3. Create GCE Instance

```bash
gcloud compute instances create poly-collector \
  --project=poly-collector \
  --zone=us-central1-a \
  --machine-type=e2-micro \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --boot-disk-size=10GB \
  --scopes=cloud-platform \
  --tags=http-server
```

### 4. Setup Instance

```bash
# SSH into instance
gcloud compute ssh poly-collector --zone=us-central1-a --project=poly-collector

# Install dependencies
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv rsync

# Create project directory
mkdir -p ~/poly
```

### 5. Copy Project Files

```bash
# From local machine - copy essential files
rsync -avz --exclude='*.pyc' --exclude='__pycache__' --exclude='.venv' \
  -e "ssh -i ~/.ssh/google_compute_engine" \
  src/ scripts/cloudrun_collector.py requirements.txt \
  lialan@35.224.204.208:~/poly/
```

### 6. Setup Python Environment on GCE

```bash
# SSH into instance
gcloud compute ssh poly-collector --zone=us-central1-a --project=poly-collector

# Setup venv
cd ~/poly
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 7. Create Systemd Service

```bash
# On GCE instance
sudo tee /etc/systemd/system/poly-collector.service << 'EOF'
[Unit]
Description=Polymarket Data Collector
After=network.target

[Service]
Type=simple
User=lialan
WorkingDirectory=/home/lialan/poly
Environment="PYTHONPATH=/home/lialan/poly/src"
Environment="DB_BACKEND=bigtable"
Environment="BIGTABLE_PROJECT_ID=poly-collector"
Environment="BIGTABLE_INSTANCE_ID=poly-data"
Environment="COLLECT_INTERVAL=5"
ExecStart=/home/lialan/poly/.venv/bin/python scripts/cloudrun_collector.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable poly-collector
sudo systemctl start poly-collector
```

## Operations

### Check Service Status

```bash
gcloud compute ssh poly-collector --zone=us-central1-a --project=poly-collector \
  --command='sudo systemctl status poly-collector'
```

### View Logs

```bash
# Recent logs
gcloud compute ssh poly-collector --zone=us-central1-a --project=poly-collector \
  --command='sudo journalctl -u poly-collector -n 50 --no-pager'

# Follow logs
gcloud compute ssh poly-collector --zone=us-central1-a --project=poly-collector \
  --command='sudo journalctl -u poly-collector -f'
```

### Restart Service

```bash
gcloud compute ssh poly-collector --zone=us-central1-a --project=poly-collector \
  --command='sudo systemctl restart poly-collector'
```

### Stop/Start Instance

```bash
# Stop (to save costs)
gcloud compute instances stop poly-collector --zone=us-central1-a --project=poly-collector

# Start
gcloud compute instances start poly-collector --zone=us-central1-a --project=poly-collector
```

## Monitoring

### View Bigtable Data

```bash
# From local machine
PYTHONPATH=src python scripts/query_bigtable.py --count 10

# Or use the Cloud Console
# https://console.cloud.google.com/bigtable/instances/poly-data/tables?project=poly-collector
```

### Health Check

```bash
# Check health endpoint (from local)
curl http://35.224.204.208:8080/health
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PYTHONPATH` | Python module path | /home/lialan/poly/src |
| `COLLECT_INTERVAL` | Seconds between snapshots | 5 |
| `DB_BACKEND` | Storage backend | bigtable |
| `BIGTABLE_PROJECT_ID` | GCP project ID | poly-collector |
| `BIGTABLE_INSTANCE_ID` | Bigtable instance | poly-data |

## Troubleshooting

### Service Won't Start

```bash
# Check logs for errors
sudo journalctl -u poly-collector -n 100 --no-pager

# Check if Python path is correct
ls -la /home/lialan/poly/.venv/bin/python
```

### Bigtable Connection Issues

```bash
# Verify instance has cloud-platform scope
gcloud compute instances describe poly-collector \
  --zone=us-central1-a --project=poly-collector \
  --format='get(serviceAccounts[0].scopes)'
```

### Network Issues

Note: Binance WebSocket (`wss://stream.binance.com`) returns HTTP 451 on GCP.
The collector uses REST API (`https://data-api.binance.vision`) which works fine.

## Cost Estimates

| Resource | Cost |
|----------|------|
| GCE e2-micro | Free tier (1 instance/month) |
| Bigtable (development) | Free tier eligible |
| Bigtable (1 node, production) | ~$0.65/hour (~$470/month) |
| Network egress | Minimal |

**Tip**: Use a development Bigtable instance for testing (free vs ~$470/month).

## Cleanup

```bash
# Stop the service
gcloud compute ssh poly-collector --zone=us-central1-a --project=poly-collector \
  --command='sudo systemctl stop poly-collector'

# Delete GCE instance
gcloud compute instances delete poly-collector --zone=us-central1-a --project=poly-collector

# Delete Bigtable instance (careful - deletes all data!)
gcloud bigtable instances delete poly-data --project=poly-collector
```
