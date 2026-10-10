FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/srv

WORKDIR /srv

COPY common /srv/common
COPY services/ingestion/pyproject.toml /srv/services/ingestion/pyproject.toml

# Dependencies first (cached unless pyproject changes). The optional
# "extra_ca" build secret exists only for build machines behind a
# TLS-intercepting proxy (see docker-compose.ca.yml); normal builds skip it.
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install /srv/common[db] && \
    mkdir -p /srv/services/ingestion/app && touch /srv/services/ingestion/app/__init__.py && \
    pip install /srv/services/ingestion && pip uninstall -y pulseguard-ingestion

COPY services/ingestion /srv/services/ingestion
COPY data/demo /srv/data/demo

EXPOSE 8001
CMD ["uvicorn", "services.ingestion.app.main:app", "--host", "0.0.0.0", "--port", "8001", "--no-access-log"]
