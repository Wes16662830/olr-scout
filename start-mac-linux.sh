#!/usr/bin/env bash
# OLR Scout: run with ./start-mac-linux.sh and leave the window open while you use the app.
set -e
cd "$(dirname "$0")/backend"
if [ ! -d .venv ]; then
  echo "First run: setting up Python packages, this takes a few minutes..."
  python3 -m venv .venv
  . .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt
else
  . .venv/bin/activate
fi
if [ ! -f ../frontend/dist/index.html ]; then
  echo "Building the app screens..."
  (cd ../frontend && npm install && npm run build)
fi
echo
echo "OLR Scout is running. Open http://localhost:8000 in your browser. Press Ctrl+C to stop."
echo
python -m uvicorn olr_scout.main:app --host 127.0.0.1 --port 8000
