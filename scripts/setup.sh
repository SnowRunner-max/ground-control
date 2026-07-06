#!/usr/bin/env bash
# One-time setup: system deps, Python env, local models, map image.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Ground Control setup =="

OS="$(uname -s)"

# 1. whisper.cpp (STT) — llama.cpp is assumed already installed:
#    macOS: brew install llama.cpp
#    Arch:  sudo pacman -S llama-cpp-vulkan (or llama-cpp-rocm for AMD/ROCm)
if ! command -v whisper-server >/dev/null 2>&1; then
  case "$OS" in
    Darwin)
      echo "-- installing whisper-cpp via Homebrew"
      brew install whisper-cpp
      ;;
    Linux)
      if command -v pacman >/dev/null 2>&1; then
        echo "-- installing whisper-cpp via pacman (whisper-cpp-vulkan)"
        sudo pacman -S --needed whisper-cpp-vulkan
      else
        echo "whisper-server not found and pacman is unavailable."
        echo "Install whisper.cpp manually: https://github.com/ggml-org/whisper.cpp"
        exit 1
      fi
      ;;
    *)
      echo "Unsupported OS: $OS"
      exit 1
      ;;
  esac
fi
find_llama_server() {
  command -v llama-server 2>/dev/null && return 0
  local candidate
  for candidate in "$HOME/llama.cpp/build/bin/llama-server" /opt/llama.cpp/build/bin/llama-server; do
    [ -x "$candidate" ] && { echo "$candidate"; return 0; }
  done
  return 1
}
LLAMA_SERVER_BIN="$(find_llama_server)" || {
  case "$OS" in
    Darwin) echo "llama-server not found: brew install llama.cpp" ;;
    Linux)  echo "llama-server not found: sudo pacman -S llama-cpp-vulkan (or llama-cpp-rocm for AMD/ROCm), or build from source: https://github.com/ggml-org/llama.cpp" ;;
    *)      echo "llama-server not found: https://github.com/ggml-org/llama.cpp" ;;
  esac
  exit 1
}
echo "-- found llama-server at $LLAMA_SERVER_BIN"

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
