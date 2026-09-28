#!/usr/bin/env bash
# Install Thesis Radar's CLI and server dependencies.
#
# The agent core, the Sectors client and the store are standard-library Python;
# only the HTTP server needs packages. The dashboard's built output is committed,
# so Node is only required to rebuild it.
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null; then
  echo "python3 is required" >&2
  exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(f"Python 3.11+ is required, found {sys.version.split()[0]}")
PY

python3 -m venv .venv 2>/dev/null || true
if [ -x .venv/bin/pip ]; then
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
  echo "installed into .venv — run: .venv/bin/python -m thesisradar doctor"
else
  python3 -m pip install --quiet -r requirements.txt
  echo "installed into the system interpreter — run: python3 -m thesisradar doctor"
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo
  echo "created .env — add your SECTORS_API_KEY to it before running a check"
fi
