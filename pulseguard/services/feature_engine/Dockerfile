FROM python:3.12-slim

WORKDIR /srv

COPY common /srv/common
COPY services/feature_engine /srv/services/feature_engine

RUN pip install --no-cache-dir /srv/common && \
    pip install --no-cache-dir -e /srv/services/feature_engine

WORKDIR /srv/services/feature_engine

# streaming_app.py and its own app modules import themselves via the
# absolute path `services.feature_engine.app.X` -- that only resolves
# with /srv on the path, which WORKDIR alone does not provide. This is
# what caused the very first live-process run to fail with
# ModuleNotFoundError: No module named 'services' (see DECISIONS.md).
ENV PYTHONPATH=/srv

RUN chmod +x run.sh

EXPOSE 8002

CMD ["./run.sh"]
