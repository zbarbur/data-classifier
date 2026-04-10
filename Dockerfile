FROM python:3.11-slim AS base

WORKDIR /app

# Install dependencies first (layer caching)
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code
COPY data_classifier/ data_classifier/

# Runtime
FROM base AS runtime
EXPOSE 8000
CMD ["uvicorn", "data_classifier.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
