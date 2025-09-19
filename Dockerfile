# Multi-stage Dockerfile for Telegram Stream Bot with FFmpeg
FROM python:3.11-alpine AS builder

# Install build dependencies
RUN apk add --no-cache \
    gcc \
    musl-dev \
    libffi-dev \
    python3-dev

# Set work directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.11-alpine

# Install FFmpeg and runtime dependencies
RUN apk add --no-cache \
    ffmpeg \
    ca-certificates \
    && rm -rf /var/cache/apk/*

# Create non-root user for security
RUN adduser -D -s /bin/sh botuser

# Set work directory
WORKDIR /app

# Copy Python packages from builder stage
COPY --from=builder /root/.local /home/botuser/.local

# Copy application files
COPY telegram_stream_bot.py .

# Create necessary directories and set permissions
RUN mkdir -p /app/logs && \
    chown -R botuser:botuser /app

# Switch to non-root user
USER botuser

# Add local Python packages to PATH
ENV PATH=/home/botuser/.local/bin:$PATH

# Expose port for web interface
EXPOSE 8080

# Health check to monitor bot status
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8080/ || exit 1

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Run the bot
CMD ["python", "telegram_stream_bot.py"]
