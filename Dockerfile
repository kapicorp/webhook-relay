FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on

# Create app directory
WORKDIR /app

# Install dependencies
COPY README.md ./
COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install build && \
    pip install --no-deps ".[all]"

# Copy the source code
COPY src /app/src

# Build the package to ensure any build-time steps are completed
RUN pip install -e .

# Create a non-root user to run the application
RUN addgroup --system webhook && \
    adduser --system --ingroup webhook webhookuser

# Switch to the non-root user
USER webhookuser

# Set up volume for configuration
VOLUME /config

# Expose ports
EXPOSE 8000 9090 9091

# Set the entrypoint
ENTRYPOINT ["python", "-m"]

# Default command (can be overridden)
CMD ["webhook_relay.collector.app", "serve", "--config", "/config/collector_config.yaml"]