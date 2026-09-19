# API-only image: serves committed artifacts and exported parquet marts. No training, no database.
# Target: Hugging Face Spaces (Docker SDK, port 7860) or any container host.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    EV_CHARGING_DATA_UNIFIED_SCHEMA_ARTIFACTS_DIR=/app/artifacts

RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY requirements-api.txt pyproject.toml README.md ./
RUN pip install --no-cache-dir -r requirements-api.txt

COPY ev_charging_data_unified_schema ./ev_charging_data_unified_schema
RUN pip install --no-cache-dir --no-deps .

COPY artifacts ./artifacts

USER appuser
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health')"
CMD ["uvicorn", "ev_charging_data_unified_schema.serve.app:app", "--host", "0.0.0.0", "--port", "7860"]
