FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/srv

WORKDIR /srv

COPY common /srv/common
COPY services/detection_engine/pyproject.toml /srv/services/detection_engine/pyproject.toml

# Dependencies first (cached unless pyproject changes). The optional
# "extra_ca" build secret exists only for build machines behind a
# TLS-intercepting proxy (see docker-compose.ca.yml); normal builds skip it.
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install /srv/common[db] && \
    mkdir -p /srv/services/detection_engine/app && touch /srv/services/detection_engine/app/__init__.py && \
    pip install /srv/services/detection_engine && pip uninstall -y pulseguard-detection-engine

COPY services/detection_engine /srv/services/detection_engine
COPY eval/results /srv/eval/results

EXPOSE 8003
CMD ["uvicorn", "services.detection_engine.app.main:app", "--host", "0.0.0.0", "--port", "8003", "--no-access-log"]
