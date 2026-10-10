FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/srv

WORKDIR /srv

COPY common /srv/common
COPY services/feature_engine/pyproject.toml /srv/services/feature_engine/pyproject.toml

# Dependencies first (cached unless pyproject changes). The optional
# "extra_ca" build secret exists only for build machines behind a
# TLS-intercepting proxy (see docker-compose.ca.yml); normal builds skip it.
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install /srv/common[db] && \
    mkdir -p /srv/services/feature_engine/app && touch /srv/services/feature_engine/app/__init__.py && \
    pip install /srv/services/feature_engine && pip uninstall -y pulseguard-feature-engine

COPY services/feature_engine /srv/services/feature_engine


EXPOSE 8002
CMD ["./services/feature_engine/run.sh"]
