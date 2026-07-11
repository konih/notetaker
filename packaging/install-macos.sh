#!/usr/bin/env bash
# macOS installer for Live Meeting Transcriber (F5).
#
# Goal: a working `live-transcriber tui` + passing `doctor` on a fresh Mac,
# without developer tooling knowledge. Installs system deps via Homebrew,
# the CLI via `uv tool install`, and points the user at the config location
# (fresh installs: ~/Library/Application Support/live-meeting-transcriber).
#
# Usage: bash packaging/install-macos.sh [--offline] [--dry-run]
#   --offline   also install the offline finalize stack (whisperx + diarization
#               extras; the mlx extra rides along and is a no-op off Apple Silicon)
#   --dry-run   print every action without executing anything
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash packaging/install-macos.sh [--offline] [--dry-run]

  --offline   Also install offline finalize extras (whisperx, diarization, mlx).
              Large download (PyTorch stack); needs Python <= 3.13 (handled here).
  --dry-run   Show what would be done without changing anything.
  -h, --help  This help.
USAGE
}

DRY_RUN=0
OFFLINE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --offline) OFFLINE=1 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "error: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OS="$(uname -s)"

if [[ "${OS}" != "Darwin" ]]; then
  echo "error: this installer targets macOS only (detected: ${OS})." >&2
  echo "On Linux use: task install:desktop (packaging/install-desktop.sh)." >&2
  exit 1
fi

run() {
  if (( DRY_RUN )); then
    echo "DRY-RUN: would run: $*"
  else
    echo "+ $*"
    "$@"
  fi
}

# --- 1. Homebrew (required to install ffmpeg/uv; we do not curl-pipe installers) ---
if ! command -v brew >/dev/null 2>&1; then
  echo "error: Homebrew is required to install system dependencies (ffmpeg, uv)." >&2
  echo "Install it from https://brew.sh first, then re-run this script." >&2
  exit 1
fi
echo "ok: Homebrew"

# --- 2. System dependencies ---
if command -v ffmpeg >/dev/null 2>&1; then
  echo "ok: ffmpeg"
else
  run brew install ffmpeg
fi

if command -v uv >/dev/null 2>&1; then
  echo "ok: uv"
else
  run brew install uv
fi

# --- 3. Xcode command line tools (Core Audio tap helper compiles on first capture) ---
if xcode-select -p >/dev/null 2>&1; then
  echo "ok: Xcode command line tools"
else
  echo "note: Xcode command line tools not found. System-audio capture (macOS 14.4+"
  echo "      Core Audio process tap) compiles a small Swift helper on first use."
  echo "      Install them with: xcode-select --install"
fi

# --- 4. Install the CLI globally (uv tool) ---
# PyTorch-based extras publish wheels only up to CPython 3.13 (early 2026), so the
# tool environment is pinned to 3.13 for a deterministic install either way.
SPEC="live-meeting-transcriber @ ${ROOT}"
if (( OFFLINE )); then
  # mlx is marker-guarded to Darwin/arm64 in pyproject.toml — a no-op elsewhere.
  SPEC="live-meeting-transcriber[whisperx,diarization,mlx] @ ${ROOT}"
fi
run uv tool install --force --python 3.13 "${SPEC}"

# --- 5. PATH + config location + doctor ---
if (( DRY_RUN )); then
  echo "DRY-RUN: would verify 'live-transcriber' is on PATH (fix: uv tool update-shell)"
  echo "DRY-RUN: would create the config dir reported by: live-transcriber paths --config-dir"
  echo "DRY-RUN: would run: live-transcriber doctor"
  echo "DRY-RUN: done."
  exit 0
fi

if ! command -v live-transcriber >/dev/null 2>&1; then
  echo "note: 'live-transcriber' is not on PATH yet. Run: uv tool update-shell"
  echo "      then open a new terminal and re-run: live-transcriber doctor"
  exit 0
fi

CONFIG_DIR="$(live-transcriber paths --config-dir)"
mkdir -p "${CONFIG_DIR}"
echo "Config directory: ${CONFIG_DIR}"
if [[ ! -f "${CONFIG_DIR}/.env" ]]; then
  echo "note: no ${CONFIG_DIR}/.env yet. For OpenAI transcription/summaries set at"
  echo "      least OPENAI_API_KEY there, or configure via the TUI Settings tab."
fi

echo ""
echo "Running post-install diagnostics (live-transcriber doctor)..."
live-transcriber doctor || echo "note: doctor reported missing prerequisites above — fix and re-run it."

echo ""
echo "Done. Start the app with: live-transcriber tui"
