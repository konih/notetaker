#!/usr/bin/env bash
# Launch the Live Meeting Transcriber TUI with XDG config and dependency checks.
set -euo pipefail

APP_ID="live-meeting-transcriber"
XDG_CONFIG="${XDG_CONFIG_HOME:-${HOME}/.config}"
CONFIG_DIR="${XDG_CONFIG}/${APP_ID}"
OS="$(uname -s)"

mkdir -p "${CONFIG_DIR}"

missing=()
command -v ffmpeg >/dev/null 2>&1 || missing+=("ffmpeg")
if [[ "${OS}" != "Darwin" ]]; then
  command -v pactl >/dev/null 2>&1 || missing+=("pactl")
fi

if ((${#missing[@]} > 0)); then
  echo "Missing required tools: ${missing[*]}" >&2
  if [[ "${OS}" == "Darwin" ]]; then
    echo "Install on macOS: brew install ffmpeg" >&2
    echo "System audio capture needs a virtual loopback device (e.g. BlackHole or Microsoft Teams Audio)." >&2
  else
    echo "Install on Ubuntu/Debian: sudo apt install ffmpeg pulseaudio-utils" >&2
    echo "PipeWire users may also need: pipewire-pulse or wireplumber." >&2
  fi
  exit 1
fi

if [[ ! -f "${CONFIG_DIR}/.env" ]]; then
  echo "First run: create ${CONFIG_DIR}/.env (copy from .env.example in the repo)." >&2
  echo "At minimum set OPENAI_API_KEY when using OpenAI transcription/summaries." >&2
fi

exec live-transcriber
