# GCE Instances

## Overview

| Instance | Zone | Machine Type | External IP | Purpose |
|----------|------|--------------|-------------|---------|
| poly-collector | us-central1-a | e2-micro | 35.224.204.208 | Polymarket data collection |
| binance-collector | asia-southeast1-b | e2-micro | 35.185.188.114 | Binance orderbook depth |

**Project:** `poly-collector`
**Bigtable Instance:** `poly-data`

---

## poly-collector (US)

Collects Polymarket prediction market snapshots for BTC and ETH.

| Property | Value |
|----------|-------|
| Zone | us-central1-a |
| IP | 35.224.204.208 |
| Service | systemd (`poly-collector.service`) |
| Script | `scripts/cloudrun_collector.py` |
| Interval | 5 seconds |

**Markets collected:**
- BTC: 15m, 1h, 4h, daily
- ETH: 15m, 1h, 4h

**Bigtable tables:**
- `btc_15m_snapshot`, `btc_1h_snapshot`, `btc_4h_snapshot`, `btc_d1_snapshot`
- `eth_15m_snapshot`, `eth_1h_snapshot`, `eth_4h_snapshot`

### Commands

```bash
# SSH
gcloud compute ssh poly-collector --zone=us-central1-a --project=poly-collector

# View logs
gcloud compute ssh poly-collector --zone=us-central1-a --project=poly-collector \
  --command='sudo journalctl -u poly-collector -n 50 --no-pager'

# Follow logs
gcloud compute ssh poly-collector --zone=us-central1-a --project=poly-collector \
  --command='sudo journalctl -u poly-collector -f'

# Restart service
gcloud compute ssh poly-collector --zone=us-central1-a --project=poly-collector \
  --command='sudo systemctl restart poly-collector'

# Check status
gcloud compute ssh poly-collector --zone=us-central1-a --project=poly-collector \
  --command='sudo systemctl status poly-collector'

# Health check
curl http://35.224.204.208:8080/health
```

### Deploy code

```bash
# Sync code
rsync -avz --exclude='*.pyc' --exclude='__pycache__' \
  -e "ssh -i ~/.ssh/google_compute_engine" \
  src/poly/ lialan@35.224.204.208:~/poly/src/poly/

scp -i ~/.ssh/google_compute_engine scripts/cloudrun_collector.py \
  lialan@35.224.204.208:~/poly/scripts/

# Restart
gcloud compute ssh poly-collector --zone=us-central1-a --project=poly-collector \
  --command='sudo systemctl restart poly-collector'
```

---

## binance-collector (Singapore)

Collects Binance orderbook depth for BTC and ETH. Located in Singapore to avoid Binance geo-blocking (HTTP 451 in US).

| Property | Value |
|----------|-------|
| Zone | asia-southeast1-b |
| IP | 35.185.188.114 |
| Service | Docker container (`binance-collector`) |
| Script | `scripts/binance_snapshot_ws.py` |
| Interval | 1 second |

**Collection parameters:**
- Symbols: BTCUSDT, ETHUSDT
- Min order size: $10,000 USDT (~90% liquidity)
- Format: `[price, usdt_value]`

**Bigtable tables:**
- `binance_btc_depth`
- `binance_eth_depth`

### Commands

```bash
# SSH
gcloud compute ssh binance-collector --zone=asia-southeast1-b --project=poly-collector

# View container logs
gcloud compute ssh binance-collector --zone=asia-southeast1-b --project=poly-collector \
  --command='docker logs binance-collector --tail 50'

# Follow logs
gcloud compute ssh binance-collector --zone=asia-southeast1-b --project=poly-collector \
  --command='docker logs binance-collector -f'

# Restart container
gcloud compute ssh binance-collector --zone=asia-southeast1-b --project=poly-collector \
  --command='cd ~/binance-collector && ./run-binance-collector.sh'

# Check container status
gcloud compute ssh binance-collector --zone=asia-southeast1-b --project=poly-collector \
  --command='docker ps'
```

### Deploy code

```bash
# Sync docker files
scp -i ~/.ssh/google_compute_engine -r docker/binance-collector/* \
  lialan@35.185.188.114:~/binance-collector/

# Sync source code
rsync -avz --exclude='*.pyc' --exclude='__pycache__' \
  -e "ssh -i ~/.ssh/google_compute_engine" \
  src/poly/ lialan@35.185.188.114:~/binance-collector/src/poly/

scp -i ~/.ssh/google_compute_engine scripts/binance_snapshot_ws.py \
  lialan@35.185.188.114:~/binance-collector/scripts/

# Rebuild and restart
gcloud compute ssh binance-collector --zone=asia-southeast1-b --project=poly-collector \
  --command='cd ~/binance-collector && docker build -t binance-collector:latest . && ./run-binance-collector.sh'
```

---

## Instance Management

```bash
# List all instances
gcloud compute instances list --project=poly-collector

# Stop instances
gcloud compute instances stop poly-collector --zone=us-central1-a --project=poly-collector
gcloud compute instances stop binance-collector --zone=asia-southeast1-b --project=poly-collector

# Start instances
gcloud compute instances start poly-collector --zone=us-central1-a --project=poly-collector
gcloud compute instances start binance-collector --zone=asia-southeast1-b --project=poly-collector

# Delete instances
gcloud compute instances delete poly-collector --zone=us-central1-a --project=poly-collector
gcloud compute instances delete binance-collector --zone=asia-southeast1-b --project=poly-collector
```

---

## Bigtable Console

View data at: https://console.cloud.google.com/bigtable/instances/poly-data/tables?project=poly-collector

Query locally:
```bash
PYTHONPATH=src python scripts/query_bigtable.py --count 10
```
