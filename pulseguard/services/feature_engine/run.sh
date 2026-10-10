#!/bin/sh
# Two processes in one container: the read-only baseline API (background)
# and the Faust stream worker (foreground -- the container's real job).
set -e
uvicorn services.feature_engine.app.main:app --host 0.0.0.0 --port 8002 --no-access-log &
exec faust -A services.feature_engine.app.streaming_app worker -l warn
