#!/usr/bin/env bash
# One command from a fresh clone to a running app: checks tools, installs what's missing, creates .env with
# fresh secrets, prepares the database, creates a demo login (demo mode), then runs the API and the web app.
# Safe to run again: each step only does work that's still needed.
#
#   make start            # or: ./scripts/start.sh
#
# Ports: API_PORT (default 8000), WEB_PORT (default 3000).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

say() { printf '\033[1m→ %s\033[0m\n' "$*"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# ── tools ────────────────────────────────────────────────────────────────
PYTHON=""
for cand in python3.13 python3.12 python3.11 python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
    PYTHON=$(command -v "$cand"); break
  fi
done
[ -n "$PYTHON" ] || fail "Python 3.11 or newer is needed (https://www.python.org/downloads/)."

[ -d /opt/homebrew/opt/node@24/bin ] && export PATH="/opt/homebrew/opt/node@24/bin:$PATH"
command -v node >/dev/null 2>&1 || fail "Node.js 20.9 or newer is needed (https://nodejs.org/)."
node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a>20||(a===20&&b>=9)?0:1)' \
  || fail "Node.js $(node -v) is too old; install 20.9 or newer (22 or 24 recommended)."

# ── dependencies ─────────────────────────────────────────────────────────
if [ ! -x backend/.venv/bin/python ]; then
  say "Creating the Python environment"
  "$PYTHON" -m venv backend/.venv
fi
if [ ! -f backend/.venv/.installed ] || [ backend/pyproject.toml -nt backend/.venv/.installed ]; then
  say "Installing backend dependencies"
  backend/.venv/bin/python -m pip install -q --upgrade pip
  backend/.venv/bin/python -m pip install -q -e "backend[dev]"
  touch backend/.venv/.installed
fi
if [ ! -d frontend/node_modules ] || [ frontend/package-lock.json -nt frontend/node_modules/.package-lock.json ]; then
  say "Installing frontend dependencies"
  (cd frontend && npm ci --no-audit --no-fund)
fi

# ── configuration and data ───────────────────────────────────────────────
mkdir -p data
if [ ! -f .env ]; then
  say "Creating .env with fresh secret keys (demo mode)"
  (cd backend && .venv/bin/python -m growthpilot init-env)
fi
mode=${APP_MODE:-$(grep -E '^APP_MODE=' .env | tail -1 | cut -d= -f2 | tr -d '"'"'"' ')}
mode=${mode:-demo}

say "Preparing the $mode database"
(cd backend && .venv/bin/python -m growthpilot migrate)

if [ "$mode" = "demo" ]; then
  if [ ! -f data/demo-login.txt ]; then
    say "Creating the demo login and loading the demo brand"
    (cd backend && .venv/bin/python -m growthpilot demo-setup)
  fi
  LOGIN_HINT="Log in with the email and password in $ROOT/data/demo-login.txt (or create an account at /register)."
else
  LOGIN_HINT="Live mode: log in with an account on this machine's live database, or create the first one at /register."
fi

# ── run ──────────────────────────────────────────────────────────────────
busy() { "$PYTHON" -c 'import socket,sys; s=socket.socket(); sys.exit(s.connect_ex(("127.0.0.1", int(sys.argv[1]))) != 0)' "$1"; }
for port in "${API_PORT:-8000}" "${WEB_PORT:-3000}"; do
  busy "$port" && fail "Port $port is already in use (another GrowthPilot or app?). Stop it, or pick other ports: API_PORT=8010 WEB_PORT=3010 make start"
done
say "Starting GrowthPilot"
echo "   $LOGIN_HINT"
exec ./scripts/dev.sh
