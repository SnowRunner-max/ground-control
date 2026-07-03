#!/usr/bin/env bash
# One-time setup: system deps, Python env, local models, map image.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Ground Control setup =="

# 1. whisper.cpp (STT) — llama.cpp is assumed installed (brew install llama.cpp)
if ! command -v whisper-server >/dev/null 2>&1; then
  echo "-- installing whisper-cpp via Homebrew"
  brew install whisper-cpp
fi
command -v llama-server >/dev/null 2>&1 || { echo "llama-server not found: brew install llama.cpp"; exit 1; }

# 2. Python environment
command -v uv >/dev/null 2>&1 || { echo "uv not found: https://docs.astral.sh/uv/"; exit 1; }
uv sync

# 3. Models (~3.5 GB total)
mkdir -p models
dl() { # dl <path> <url> [fallback-url]
  local path="$1" url="$2" fallback="${3:-}"
  if [ -s "$path" ]; then echo "-- $path already present"; return 0; fi
  echo "-- downloading $path"
  curl -sfL -o "$path" "$url" || { [ -n "$fallback" ] && curl -sfL -o "$path" "$fallback"; }
  [ -s "$path" ] || { echo "download failed: $url"; exit 1; }
}
dl models/ggml-small.en.bin \
  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin"
dl models/kokoro-v1.0.onnx \
  "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
dl models/voices-v1.0.bin \
  "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
dl models/qwen3-4b-instruct-2507-q4_k_m.gguf \
  "https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf" \
  "https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf"

# 4. Map image from the FAA diagram PDF
uv run python scripts/prep_map.py

echo "== setup complete — start the sim with ./run.sh =="
