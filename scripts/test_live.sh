#!/usr/bin/env bash
# Start the local model services and require every live e2e test to run.
set -euo pipefail
cd "$(dirname "$0")/.."

# Use dedicated defaults so a developer's normal ./run.sh stack can remain up.
LLAMA_PORT="${LLAMA_PORT:-18080}"
WHISPER_PORT="${WHISPER_PORT:-18081}"
LLAMA_URL="http://127.0.0.1:$LLAMA_PORT"
WHISPER_URL="http://127.0.0.1:$WHISPER_PORT"

find_llama_server() {
  command -v llama-server 2>/dev/null && return 0
  local candidate
  for candidate in "$HOME/llama.cpp/build/bin/llama-server" /opt/llama.cpp/build/bin/llama-server; do
    [ -x "$candidate" ] && { echo "$candidate"; return 0; }
  done
  return 1
}

LLAMA_SERVER_BIN="$(find_llama_server)" || {
  echo "llama-server not found. Run ./scripts/setup.sh first."; exit 1
}
command -v whisper-server >/dev/null 2>&1 || {
  echo "whisper-server not found. Run ./scripts/setup.sh first."; exit 1
}

for model in \
  models/qwen3-4b-instruct-2507-q4_k_m.gguf \
  models/ggml-small.en.bin \
  models/kokoro-v1.0.onnx \
  models/voices-v1.0.bin; do
  [ -s "$model" ] || { echo "missing model: $model"; exit 1; }
done

mkdir -p logs
pids=()
cleanup() {
  kill "${pids[@]}" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

"$LLAMA_SERVER_BIN" -m models/qwen3-4b-instruct-2507-q4_k_m.gguf \
  --port "$LLAMA_PORT" -c 4096 -ngl 99 --jinja \
  --log-file logs/e2e-llama.log >/dev/null 2>&1 &
pids+=("$!")

whisper-server -m models/ggml-small.en.bin --port "$WHISPER_PORT" -t 4 \
  >logs/e2e-whisper.log 2>&1 &
pids+=("$!")

wait_up() {
  local name="$1" url="$2"
  for _ in $(seq 1 120); do
    curl -sf -o /dev/null "$url" && { echo "-- $name ready"; return 0; }
    sleep 0.5
  done
  echo "$name failed to start; inspect logs/e2e-${name}.log"
  return 1
}

wait_up llama "${LLAMA_URL}/health"
wait_up whisper "${WHISPER_URL}/"

GROUND_CONTROL_REQUIRE_E2E=1 LLAMA_URL="$LLAMA_URL" WHISPER_URL="$WHISPER_URL" \
  uv run pytest tests/e2e -q
