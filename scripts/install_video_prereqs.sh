#!/usr/bin/env bash
# Install system tools for ``live-transcriber transcribe-video`` (ffmpeg + yt-dlp).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

missing=()

require_cmd() {
  local name="$1"
  if command -v "$name" >/dev/null 2>&1; then
    echo "ok: $name ($("$name" --version 2>/dev/null | head -n1 || true))"
    return 0
  fi
  missing+=("$name")
  return 1
}

require_cmd ffmpeg || true
require_cmd ffprobe || true

if ! command -v yt-dlp >/dev/null 2>&1; then
  echo "Installing yt-dlp via uv tool ..."
  if ! command -v uv >/dev/null 2>&1; then
    echo "error: uv is required to install yt-dlp (https://docs.astral.sh/uv/)" >&2
    exit 1
  fi
  uv tool install yt-dlp
  export PATH="${HOME}/.local/bin:${PATH}"
fi

require_cmd yt-dlp || true

if ((${#missing[@]} > 0)); then
  echo ""
  echo "Missing required commands: ${missing[*]}" >&2
  if [[ "$(uname -s)" == "Darwin" ]]; then
    if command -v brew >/dev/null 2>&1; then
      echo "Try: brew install ffmpeg" >&2
    else
      echo "Install ffmpeg with Homebrew or from https://ffmpeg.org/download.html" >&2
    fi
  elif command -v apt-get >/dev/null 2>&1; then
    echo "Try: sudo apt-get update && sudo apt-get install -y ffmpeg" >&2
  else
    echo "Install ffmpeg/ffprobe with your system package manager." >&2
  fi
  exit 1
fi

echo ""
echo "Video import prerequisites are ready."
