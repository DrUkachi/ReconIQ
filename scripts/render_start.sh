#!/usr/bin/env bash
# Render's free tier runs a single service, so the API and the job worker share this
# container. If either process exits, stop the other and exit so Render restarts it.
set -uo pipefail

alembic upgrade head || exit 1

python -m app.worker &
worker_pid=$!

uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
api_pid=$!

trap 'kill -TERM "$api_pid" "$worker_pid" 2>/dev/null' TERM INT

wait -n "$api_pid" "$worker_pid"
status=$?
kill -TERM "$api_pid" "$worker_pid" 2>/dev/null
wait
exit "$status"
