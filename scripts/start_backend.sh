#!/usr/bin/env bash
# Start the backend on this Lightning studio and confirm its public URL answers.
set -euo pipefail
cd "$(dirname "$0")/.."

compose=(docker compose -f docker-compose.yml -f docker-compose.public.yml)

"${compose[@]}" up -d --build db api worker
until "${compose[@]}" exec -T db pg_isready -U bankrecon -d bankrecon >/dev/null 2>&1; do sleep 1; done
"${compose[@]}" run --rm api alembic upgrade head

for _ in $(seq 60); do
  curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS http://127.0.0.1:8000/healthz >/dev/null || {
  echo "API did not become healthy. Check: docker compose logs api"
  exit 1
}

public="https://3000-${LIGHTNING_CLOUDSPACE_HOST:?run this inside the Lightning studio}"
status=""
for _ in $(seq 15); do
  status=$(curl -s -o /dev/null -m 15 -w '%{http_code}' "$public/healthz" || true)
  [ "$status" = "200" ] && break
  sleep 2
done
echo "Backend healthy locally. Public URL: $public (healthz HTTP $status)"
if [ "$status" != "200" ]; then
  echo "The public URL is not answering; confirm port 3000 is exposed in the studio."
fi
