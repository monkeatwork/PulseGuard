FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/srv

WORKDIR /srv

COPY common /srv/common
COPY services/mitigation/pyproject.toml /srv/services/mitigation/pyproject.toml

# Dependencies first (cached unless pyproject changes). The optional
# "extra_ca" build secret exists only for build machines behind a
# TLS-intercepting proxy (see docker-compose.ca.yml); normal builds skip it.
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install /srv/common[db] && \
    mkdir -p /srv/services/mitigation/app && touch /srv/services/mitigation/app/__init__.py && \
    pip install /srv/services/mitigation && pip uninstall -y pulseguard-mitigation

COPY services/mitigation /srv/services/mitigation


EXPOSE 8004
CMD ["uvicorn", "services.mitigation.app.main:app", "--host", "0.0.0.0", "--port", "8004", "--no-access-log"]
