#!/bin/bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example and fill in your values."
  exit 1
fi

echo "==================================="
echo "  Job Hunter PA – Starting up"
echo "==================================="

# Start FastAPI backend
echo "[1/2] Starting backend on :8000"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Wait for backend to be ready
echo "Waiting for backend..."
for i in {1..10}; do
  if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✅ Backend is ready"
    break
  fi
  sleep 1
done

# Start Telegram bot
echo "[2/2] Starting Telegram bot"
python -m bot.telegram_bot

# Cleanup
kill $BACKEND_PID 2>/dev/null || true
