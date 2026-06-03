#!/usr/bin/env bash
# Install launch script, desktop entry, and uv tool for local desktop use.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_BIN="${INSTALL_PREFIX:-${HOME}/.local}/bin"
DESKTOP_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/applications"
CONFIG_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/live-meeting-transcriber"

mkdir -p "${INSTALL_BIN}" "${DESKTOP_DIR}" "${CONFIG_DIR}"

install -m 755 "${ROOT}/packaging/bin/notetaker-launch.sh" "${INSTALL_BIN}/notetaker-launch"

sed "s|@EXEC@|${INSTALL_BIN}/notetaker-launch|g" \
  "${ROOT}/packaging/desktop/live-meeting-transcriber.desktop" \
  >"${DESKTOP_DIR}/live-meeting-transcriber.desktop"

chmod 644 "${DESKTOP_DIR}/live-meeting-transcriber.desktop"

echo "Installed launch script: ${INSTALL_BIN}/notetaker-launch"
echo "Installed desktop entry: ${DESKTOP_DIR}/live-meeting-transcriber.desktop"
echo "Config directory: ${CONFIG_DIR} (place .env here)"

uv tool install --editable "${ROOT}"

echo "Installed CLI: live-transcriber (uv tool)"
echo "Run from the app menu or: ${INSTALL_BIN}/notetaker-launch"
