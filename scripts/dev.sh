#!/usr/bin/env bash
# Run the API (port 8000) and the web app (port 3000) together. Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/opt/node@24/bin:$PATH"

if [ ! -x backend/.venv/bin/python ]; then
  echo "Backend not set up. Run: make setup" >&2
  exit 1
fi
if [ ! -d frontend/node_modules ]; then
  echo "Frontend not set up. Run: make setup" >&2
  exit 1
fi

(cd backend && exec .venv/bin/python -m growthpilot serve --port "${API_PORT:-8000}") &
API_PID=$!
(cd frontend && BACKEND_URL="http://127.0.0.1:${API_PORT:-8000}" exec npx next dev --port "${WEB_PORT:-3000}") &
WEB_PID=$!

trap 'kill $API_PID $WEB_PID 2>/dev/null || true' INT TERM EXIT
echo "GrowthPilot: web http://localhost:${WEB_PORT:-3000}  ·  API http://127.0.0.1:${API_PORT:-8000}/api/health"
wait
