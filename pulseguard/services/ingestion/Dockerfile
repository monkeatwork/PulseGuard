FROM python:3.12-slim

WORKDIR /srv

COPY common /srv/common
COPY services/ingestion /srv/services/ingestion

RUN pip install --no-cache-dir /srv/common && \
    pip install --no-cache-dir -e /srv/services/ingestion

WORKDIR /srv/services/ingestion

# main.py imports its own replay adapter via the absolute path
# `services.ingestion.app.adapters.replay` -- that only resolves with
# /srv on the path, which WORKDIR alone does not provide.
ENV PYTHONPATH=/srv

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
