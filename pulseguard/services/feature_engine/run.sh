#!/bin/sh
# Runs both the health-check FastAPI app (background) and the Faust worker
# (foreground, the container's actual live process) -- see DECISIONS.md,
# "Faust worker wired as the live process".
set -e
uvicorn app.main:app --host 0.0.0.0 --port 8002 &
exec faust -A app.streaming_app worker -l info
