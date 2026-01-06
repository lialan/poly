# Cloud Run Deployment Guide

This guide covers deploying the Polymarket data collector to Google Cloud Run with Bigtable storage.

## Prerequisites

1. **Google Cloud SDK** installed and configured
2. **GCP Project** with billing enabled
3. **Bigtable instance** (see [Bigtable Setup](#bigtable-setup))

## Quick Deploy

```bash
# Set your project
export PROJECT_ID=poly-collector

# Build and push container
gcloud builds submit --config cloudbuild.yaml --project $PROJECT_ID

# Deploy to Cloud Run
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

## First-Time Setup

### 1. Enable Required APIs

```bash
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable artifactregistry.googleapis.com
gcloud services enable bigtable.googleapis.com
gcloud services enable bigtableadmin.googleapis.com
```

### 2. Create Artifact Registry Repository

```bash
gcloud artifacts repositories create poly-repo \
    --repository-format=docker \
    --location=us-central1
```

### 3. Create Bigtable Instance

```bash
# Production instance (~$0.65/hour per node)
gcloud bigtable instances create poly-data \
    --display-name="Polymarket Data" \
    --cluster-config=id=poly-cluster,zone=us-central1-a,nodes=1

# OR Development instance (free tier eligible, no SLA)
gcloud bigtable instances create poly-data \
    --display-name="Polymarket Data" \
    --cluster-config=id=poly-cluster,zone=us-central1-a \
    --instance-type=DEVELOPMENT
```

### 4. Grant IAM Permissions

Cloud Run uses the default compute service account. Grant Bigtable access:

```bash
# Get the service account email
SA_EMAIL=$(gcloud iam service-accounts list \
    --filter="email ~ compute@developer.gserviceaccount.com" \
    --format="value(email)")

# Grant Bigtable User role
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/bigtable.user"
```

## Build and Deploy

### Build Container

```bash
# Using Cloud Build (recommended)
gcloud builds submit --config cloudbuild.yaml --project $PROJECT_ID

# Or build locally and push
docker build --target cloudrun -t us-central1-docker.pkg.dev/$PROJECT_ID/poly-repo/poly-collector:latest .
docker push us-central1-docker.pkg.dev/$PROJECT_ID/poly-repo/poly-collector:latest
```

### Deploy to Cloud Run

```bash
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

### Update Existing Deployment

```bash
# Rebuild
gcloud builds submit --config cloudbuild.yaml --project $PROJECT_ID

# Update service
gcloud run services update poly-collector \
    --image us-central1-docker.pkg.dev/$PROJECT_ID/poly-repo/poly-collector:latest \
    --region us-central1
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PORT` | Health check port (set by Cloud Run) | 8080 |
| `COLLECT_INTERVAL` | Seconds between snapshots | 5 |
| `DB_BACKEND` | Storage backend | bigtable |
| `BIGTABLE_PROJECT_ID` | GCP project ID | - |
| `BIGTABLE_INSTANCE_ID` | Bigtable instance | - |

## Monitoring

### View Logs

```bash
# Recent logs
gcloud run services logs read poly-collector --region us-central1 --limit 50

# Stream logs
gcloud run services logs tail poly-collector --region us-central1
```

### Check Service Status

```bash
gcloud run services describe poly-collector --region us-central1
```

### View Bigtable Data

```bash
# Install cbt CLI
gcloud components install cbt

# Read recent snapshots
cbt -project $PROJECT_ID -instance poly-data read market_snapshots count=10
```

Or use the Cloud Console:
- https://console.cloud.google.com/bigtable/instances/poly-data/tables?project=poly-collector

## Troubleshooting

### Container Won't Start

Check logs for startup errors:
```bash
gcloud run services logs read poly-collector --region us-central1 --limit 100
```

### Bigtable Connection Issues

Verify IAM permissions:
```bash
gcloud projects get-iam-policy $PROJECT_ID \
    --flatten="bindings[].members" \
    --filter="bindings.role:roles/bigtable"
```

### Health Check Failures

The collector exposes a health endpoint at `/health`. If it returns 503:
- Check if collector is receiving data
- Verify Polymarket API is accessible
- Check Chainlink RPC connectivity

## Cost Estimates

| Resource | Cost |
|----------|------|
| Cloud Run (min 1 instance) | ~$0.024/hour |
| Bigtable (1 node, production) | ~$0.65/hour |
| Bigtable (development) | Free tier eligible |
| Artifact Registry | ~$0.10/GB/month |

**Tip**: Use a development Bigtable instance for testing (~$0/month vs ~$470/month).

## Cleanup

```bash
# Delete Cloud Run service
gcloud run services delete poly-collector --region us-central1

# Delete Bigtable instance (careful - deletes all data!)
gcloud bigtable instances delete poly-data

# Delete Artifact Registry images
gcloud artifacts docker images delete \
    us-central1-docker.pkg.dev/$PROJECT_ID/poly-repo/poly-collector
```
