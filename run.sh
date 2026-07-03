#!/usr/bin/env bash
# Start llama-server (ATC brain), whisper-server (STT), and the game server.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p logs

LLAMA_PORT="${LLAMA_PORT:-8080}"
WHISPER_PORT="${WHISPER_PORT:-8081}"
APP_PORT="${APP_PORT:-8000}"

pids=()
cleanup() { echo; echo "shutting down"; kill "${pids[@]}" 2>/dev/null || true; wait 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "-- starting llama-server :$LLAMA_PORT"
llama-server -m models/qwen3-4b-instruct-2507-q4_k_m.gguf \
  --port "$LLAMA_PORT" -c 4096 -ngl 99 --jinja --log-file logs/llama.log >/dev/null 2>&1 &
pids+=($!)

echo "-- starting whisper-server :$WHISPER_PORT"
whisper-server -m models/ggml-small.en.bin --port "$WHISPER_PORT" -t 4 \
  >logs/whisper.log 2>&1 &
pids+=($!)

wait_up() { # wait_up <name> <url>
  for _ in $(seq 1 120); do
    curl -sf -o /dev/null "$2" && { echo "-- $1 ready"; return 0; }
    sleep 0.5
  done
  echo "$1 failed to start"; exit 1
}
wait_up llama-server  "http://127.0.0.1:$LLAMA_PORT/health"
wait_up whisper-server "http://127.0.0.1:$WHISPER_PORT/"

echo "-- starting ground control :$APP_PORT"
LLAMA_URL="http://127.0.0.1:$LLAMA_PORT" WHISPER_URL="http://127.0.0.1:$WHISPER_PORT" \
  uv run uvicorn server.main:app --port "$APP_PORT" --log-level warning &
pids+=($!)
wait_up "ground control" "http://127.0.0.1:$APP_PORT/api/health"

echo
echo "=========================================="
echo "  Ground Control: http://localhost:$APP_PORT"
echo "  Ctrl-C to stop everything"
echo "=========================================="
command -v open >/dev/null && open "http://localhost:$APP_PORT"
wait
