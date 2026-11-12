#!/usr/bin/env bash
# Start the centrality lab. Uses the .venv in the project folder if it exists.
cd "$(dirname "$0")/.."
if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
fi
exec python -m streamlit run app.py "$@"
