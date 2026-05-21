# ─────────────────────────────────────────────
# Multi-stage Dockerfile for FastAPI (fore-form)
# Optimized for security, performance, and caching
# ─────────────────────────────────────────────

# ── Stage 1: Install dependencies and build ──
FROM python:3.12-slim AS builder

# Install system dependencies needed for compiling python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip and wheel for efficient package installation
RUN pip install --no-cache-dir --upgrade pip wheel

# Copy requirements first to leverage Docker layer caching
COPY requirements.txt .

# Install dependencies to a clean, isolated /install prefix
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Minimal Production Image ─────────
FROM python:3.12-slim AS runner

# Install system runtime dependencies and curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy built python packages from builder stage into system path
COPY --from=builder /install /usr/local

# Create a secure, restricted non-root system user and group
RUN groupadd -g 10001 appuser && \
    useradd -u 10000 -g appuser -m -s /sbin/nologin appuser

# Copy application source files and assign non-root owner
COPY --chown=appuser:appuser . .

# Ensure upload directory exists and is owned by appuser
RUN mkdir -p /app/uploads && chown -R appuser:appuser /app/uploads

# Expose FastAPI's default port
EXPOSE 8000

# Switch to the secure non-root user
USER appuser

# Configure secure Python runtime environments
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Health check utilizing curl and /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Run the app with Uvicorn in production mode
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
