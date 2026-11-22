#!/usr/bin/env bash
# Local run without Docker. Uses MongoDB on localhost if running, otherwise an in-memory DB.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

echo "Open http://localhost:8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
