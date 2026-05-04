# Stub Auth Service - Development JWT Token Generator

FROM python:3.13-slim

LABEL maintainer="RAG File Uploader Team"
LABEL description="Development-only JWT token generation service"
LABEL version="1.0.0"

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY __init__.py main.py models.py keys.py ./

# Create non-root user and set up keys directory
RUN adduser --system --no-create-home --group authstub && \
    mkdir -p /app/keys && \
    chown -R authstub:authstub /app

# Switch to non-root user
USER authstub

# Expose port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"

# Run uvicorn server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--log-level", "info"]
