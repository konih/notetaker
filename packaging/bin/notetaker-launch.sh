#!/usr/bin/env bash
# Launch the Live Meeting Transcriber TUI with XDG config and dependency checks.
set -euo pipefail

APP_ID="live-meeting-transcriber"
XDG_CONFIG="${XDG_CONFIG_HOME:-${HOME}/.config}"
OS="$(uname -s)"

# Ask the app where config lives (macOS may resolve to ~/Library/Application Support);
# fall back to the XDG default when the CLI is not installed yet.
if command -v live-transcriber >/dev/null 2>&1 \
  && CONFIG_DIR="$(live-transcriber paths --config-dir 2>/dev/null)" \
  && [[ -n "${CONFIG_DIR}" ]]; then
  :
else
  CONFIG_DIR="${XDG_CONFIG}/${APP_ID}"
fi

mkdir -p "${CONFIG_DIR}"

missing=()
command -v ffmpeg >/dev/null 2>&1 || missing+=("ffmpeg")
if [[ "${OS}" != "Darwin" ]]; then
  command -v pactl >/dev/null 2>&1 || missing+=("pactl")
fi

if ((${#missing[@]} > 0)); then
  echo "Missing required tools: ${missing[*]}" >&2
  if [[ "${OS}" == "Darwin" ]]; then
    echo "Install on macOS: brew install ffmpeg (or run packaging/install-macos.sh)" >&2
    echo "System audio is captured via a driver-free Core Audio process tap on macOS 14.4+ (no BlackHole needed)." >&2
  else
    echo "Install on Ubuntu/Debian: sudo apt install ffmpeg pulseaudio-utils" >&2
    echo "PipeWire users may also need: pipewire-pulse or wireplumber." >&2
  fi
  exit 1
fi

if [[ ! -f "${CONFIG_DIR}/.env" ]]; then
  echo "First run: create ${CONFIG_DIR}/.env (see docs/configuration.md) or use the TUI Settings screen." >&2
  echo "At minimum set OPENAI_API_KEY when using OpenAI transcription/summaries." >&2
fi

exec live-transcriber
