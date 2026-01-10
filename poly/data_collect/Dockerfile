FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/poly/ ./src/poly/
COPY poly/data_collect/ ./poly/data_collect/

# Set environment variables
ENV PYTHONPATH=/app/src:/app
ENV PYTHONUNBUFFERED=1

# Default to bigtable backend
ENV DB_BACKEND=bigtable
ENV BIGTABLE_PROJECT_ID=poly-collector
ENV BIGTABLE_INSTANCE_ID=poly-data

# Run the ccxt.pro collector
# Default: 0.002% step, 40 steps, 1s interval
CMD ["python", "poly/data_collect/ccxt_depth_collector.py", "--step", "0.00002", "--steps", "40", "--interval", "1"]
