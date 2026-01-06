# Polymarket Trading Platform
# Multi-stage build for smaller image size

# Build stage
FROM python:3.12-slim-bookworm AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt


# Production stage
FROM python:3.12-slim-bookworm AS production

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl3 \
    libffi8 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash appuser

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code and set ownership
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser scripts/ ./scripts/

# Set Python path
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from poly import Config; print('OK')" || exit 1

# Default command
CMD ["python", "scripts/run.py"]


# Cloud Run collector stage
FROM production AS cloudrun

# Cloud Run configuration
ENV PORT=8080
ENV COLLECT_INTERVAL=5
ENV DB_BACKEND=bigtable

# Expose port for health checks
EXPOSE 8080

# Run the Cloud Run collector
CMD ["python", "scripts/cloudrun_collector.py"]


# Development stage
FROM production AS development

USER root

# Install development dependencies
RUN pip install --no-cache-dir \
    pytest \
    pytest-asyncio \
    pytest-cov \
    black \
    ruff \
    mypy

# Copy tests
COPY tests/ ./tests/

USER appuser

# Override command for development
CMD ["pytest", "tests/", "-v"]
