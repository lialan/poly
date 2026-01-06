# Google Cloud Setup

## Table of Contents
- [Cloud Run Deployment](#cloud-run-deployment)
- [Bigtable Setup](#bigtable-setup)
- [Authentication](#authentication)

---

## Cloud Run Deployment

### Build and Push Container

```bash
# Set your project
export PROJECT_ID=your-project-id

# Enable required APIs
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable artifactregistry.googleapis.com

# Create Artifact Registry repository (first time only)
gcloud artifacts repositories create poly-repo \
    --repository-format=docker \
    --location=us-central1

# Build and push using Cloud Build
gcloud builds submit \
    --tag us-central1-docker.pkg.dev/$PROJECT_ID/poly-repo/poly-collector:latest \
    --target cloudrun
```

### Deploy to Cloud Run

```bash
# Deploy the collector
gcloud run deploy poly-collector \
    --image us-central1-docker.pkg.dev/$PROJECT_ID/poly-repo/poly-collector:latest \
    --platform managed \
    --region us-central1 \
    --allow-unauthenticated \
    --min-instances 1 \
    --max-instances 1 \
    --memory 512Mi \
    --cpu 1 \
    --timeout 3600 \
    --set-env-vars "BIGTABLE_PROJECT_ID=$PROJECT_ID,BIGTABLE_INSTANCE_ID=poly-data,COLLECT_INTERVAL=5"
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PORT` | Health check port (set by Cloud Run) | 8080 |
| `COLLECT_INTERVAL` | Seconds between snapshots | 5 |
| `DB_BACKEND` | Storage backend | bigtable |
| `BIGTABLE_PROJECT_ID` | GCP project ID | - |
| `BIGTABLE_INSTANCE_ID` | Bigtable instance | - |

### View Logs

```bash
gcloud run services logs read poly-collector --region us-central1 --limit 100
```

### Update Deployment

```bash
# Rebuild and redeploy
gcloud builds submit \
    --tag us-central1-docker.pkg.dev/$PROJECT_ID/poly-repo/poly-collector:latest \
    --target cloudrun

gcloud run services update poly-collector \
    --image us-central1-docker.pkg.dev/$PROJECT_ID/poly-repo/poly-collector:latest \
    --region us-central1
```

### Delete Deployment

```bash
gcloud run services delete poly-collector --region us-central1
```

---

# Bigtable Setup

This guide covers setting up Google Cloud Bigtable for the Polymarket data collector.

## Authentication

### Option 1: Service Account (Recommended for production)

```bash
# 1. Create a service account in GCP Console:
#    IAM & Admin → Service Accounts → Create Service Account
#    Grant role: "Bigtable User" (or "Bigtable Admin" if creating tables)

# 2. Download the JSON key file

# 3. Set environment variable
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"

# 4. Run the collector
python scripts/collect_snapshots.py --backend bigtable \
    --project your-project-id \
    --instance your-instance-id
```

### Option 2: gcloud CLI (Recommended for development)

```bash
# 1. Install gcloud CLI (if not installed)
# Mac:
brew install google-cloud-sdk

# Ubuntu:
curl https://sdk.cloud.google.com | bash

# 2. Login
gcloud auth application-default login

# 3. Set project
gcloud config set project your-project-id

# 4. Run the collector
python scripts/collect_snapshots.py --backend bigtable \
    --project your-project-id \
    --instance your-instance-id
```

## Create Bigtable Instance

```bash
# Enable the API
gcloud services enable bigtable.googleapis.com

# Create instance (SSD, 1 node - ~$0.65/hour)
gcloud bigtable instances create poly-data \
    --display-name="Polymarket Data" \
    --cluster-config=id=poly-cluster,zone=us-central1-a,nodes=1

# Or create a development instance (free tier eligible, no SLA)
gcloud bigtable instances create poly-data \
    --display-name="Polymarket Data" \
    --cluster-config=id=poly-cluster,zone=us-central1-a \
    --instance-type=DEVELOPMENT
```

## Environment Variables

Add to `.env` or export:

```bash
export BIGTABLE_PROJECT_ID=your-project-id
export BIGTABLE_INSTANCE_ID=poly-data
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json  # if using service account
```

## Usage

```bash
# Using command line arguments
python scripts/collect_snapshots.py --backend bigtable \
    --project your-project-id \
    --instance poly-data

# Using environment variables
export BIGTABLE_PROJECT_ID=your-project-id
export BIGTABLE_INSTANCE_ID=poly-data
python scripts/collect_snapshots.py --backend bigtable
```

## Tables

The following tables are created automatically:

| Table | Row Key | Description |
|-------|---------|-------------|
| `market_snapshots` | `{inv_ts}#{market_id}` | Orderbook snapshots |
| `opportunities` | `{inv_ts}#{market_15m_id}` | Trading opportunities |
| `simulated_trades` | `{inv_ts}#{uuid}` | Simulated trade results |
| `equity_curve` | `{inv_ts}` | Portfolio equity over time |

All tables use inverted timestamps for reverse chronological ordering (newest first).

## Costs

- **Development instance**: Free (1 node, no SLA)
- **Production instance**: ~$0.65/hour per node + storage ($0.17/GB/month)
- **Network**: Egress charges apply for cross-region access

## Useful Commands

```bash
# List instances
gcloud bigtable instances list

# List tables
cbt -project your-project-id -instance poly-data ls

# Read rows from a table
cbt -project your-project-id -instance poly-data read market_snapshots count=5

# Delete instance (careful!)
gcloud bigtable instances delete poly-data
```

## Install cbt (Bigtable CLI)

```bash
gcloud components install cbt

# Create cbtrc config
echo "project = your-project-id" > ~/.cbtrc
echo "instance = poly-data" >> ~/.cbtrc
```
