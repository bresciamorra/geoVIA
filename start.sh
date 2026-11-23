#!/bin/bash
cd "$(dirname "$0")"

export OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-hermes3:8b}"

if [ ! -d "venv" ]; then
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
else
  source venv/bin/activate
fi

echo "🌍 geoVIA starting on http://localhost:8002"
uvicorn backend.main:app --host 0.0.0.0 --port 8002 --reload
