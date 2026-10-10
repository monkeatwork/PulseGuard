FROM python:3.12-slim

WORKDIR /srv

COPY common /srv/common
COPY services/detection_engine /srv/services/detection_engine

RUN pip install --no-cache-dir /srv/common && \
    pip install --no-cache-dir -e /srv/services/detection_engine

WORKDIR /srv/services/detection_engine

# live_scorer.py and its own app modules import themselves via the
# absolute path `services.detection_engine.app.X` -- that only resolves
# with /srv on the path, which WORKDIR alone does not provide.
ENV PYTHONPATH=/srv

EXPOSE 8003

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
