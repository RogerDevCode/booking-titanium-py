# ============================================================================
# Dockerfile — Production container for Titanium Booking Engine (Python 3.13)
# ============================================================================

FROM python:3.13-slim

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1
ENV PYTHONUNBUFFERED=1

# Copy project configuration
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-install-project

# Set PATH to use the virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# Copy source code
COPY app/ ./app/
COPY f/ ./f/
# NOTE: .env is NOT copied into the image — secrets are injected at runtime
# via `env_file` in docker-compose.yml

# Create a non-root user for security
RUN groupadd -r appgroup && useradd -r -g appgroup appuser
RUN chown -R appuser:appgroup /app
USER appuser

# Default port for FastAPI
EXPOSE 8000

# Entrypoint
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
