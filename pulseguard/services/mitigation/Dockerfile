FROM python:3.12-slim

WORKDIR /srv

COPY common /srv/common
COPY services/mitigation /srv/services/mitigation

RUN pip install --no-cache-dir /srv/common && \
    pip install --no-cache-dir -e /srv/services/mitigation

WORKDIR /srv/services/mitigation

# main.py imports its own live_worker via the absolute path
# `services.mitigation.app.live_worker` (consistent with how every other
# service's code refers to itself across the repo) -- that only resolves
# with /srv on the path, which WORKDIR alone does not provide.
ENV PYTHONPATH=/srv

EXPOSE 8004

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
