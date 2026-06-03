#!/usr/bin/env bash
# Download the default English presentation sample (cached, gitignored).
# For full fixture set (EN/DE meeting WAV + presentations), use scripts/fetch_test_fixtures.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

bash scripts/install_video_prereqs.sh

CACHE_DIR="${ROOT}/tests/fixtures/.cache"
mkdir -p "$CACHE_DIR"

URL="${SAMPLE_VIDEO_URL:-${FIXTURE_PRESENTATION_EN_URL:-https://www.youtube.com/watch?v=DZL-ExKPjnc}}"
OUT="${CACHE_DIR}/presentation_en_source.mp4"

if [[ -f "$OUT" && "${FORCE_SAMPLE_DOWNLOAD:-0}" != "1" ]]; then
  echo "Using cached sample: $OUT"
  echo "$OUT"
  exit 0
fi

echo "Downloading presentation sample to $OUT ..."
yt-dlp \
  --no-playlist \
  -f "best[height<=360][ext=mp4]/best[ext=mp4]/best" \
  -o "$OUT" \
  "$URL"

echo "$OUT"
