#!/usr/bin/env bash
# Download meeting speech + presentation media for e2e/integration tests.
# English/German spoken audio; presentation videos with slides (synthetic + real).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

bash scripts/install_video_prereqs.sh

CACHE="${ROOT}/tests/fixtures/.cache"
WAV_DIR="${ROOT}/tests/fixtures/wav"
VIDEO_DIR="${ROOT}/tests/fixtures/video"
mkdir -p "$CACHE" "$WAV_DIR" "$VIDEO_DIR"

# --- Sources (see tests/fixtures/README.md) ---
AMI_MEETING_URL="${FIXTURE_AMI_MEETING_URL:-https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/ES2002a/audio/ES2002a.Mix-Headset.wav}"
AMI_OFFSET_SEC="${FIXTURE_AMI_OFFSET_SECONDS:-600}"

# CCC 36C3 talk (German primary, slides on screen) — CC BY 4.0
CCC_PRESENTATION_URL="${FIXTURE_CCC_PRESENTATION_URL:-https://cdn.media.ccc.de/congress/2019/h264-sd/36c3-10571-deu-eng-Nutzung_oeffentlicher_Klimadaten_sd.mp4}"
CCC_OFFSET_SEC="${FIXTURE_CCC_OFFSET_SECONDS:-120}"

# English tech presentation with slides (default: user Kafka migration talk)
PRESENTATION_EN_URL="${FIXTURE_PRESENTATION_EN_URL:-https://www.youtube.com/watch?v=DZL-ExKPjnc}"
PRESENTATION_EN_CACHE="${CACHE}/presentation_en_source.mp4"

MEETING_EN_WAV="${WAV_DIR}/meeting_en_10s_16k_mono.wav"
MEETING_EN_LONG_WAV="${WAV_DIR}/meeting_en_120s_16k_mono.wav"
MEETING_DE_WAV="${WAV_DIR}/meeting_de_10s_16k_mono.wav"
MEETING_DE_LONG_WAV="${WAV_DIR}/meeting_de_120s_16k_mono.wav"
PRESENTATION_EN_MP4="${VIDEO_DIR}/presentation_en_15s_360p.mp4"
PRESENTATION_EN_LONG_MP4="${VIDEO_DIR}/presentation_en_120s_360p.mp4"
PRESENTATION_DE_MP4="${VIDEO_DIR}/presentation_de_15s_360p.mp4"
PRESENTATION_DE_LONG_MP4="${VIDEO_DIR}/presentation_de_120s_360p.mp4"
PRESENTATION_SYNTH="${ROOT}/tests/fixtures/sample_presentation.mp4"
PRESENTATION_SYNTH_LONG="${ROOT}/tests/fixtures/sample_presentation_120s.mp4"

MEETING_SEC="${FIXTURE_MEETING_SECONDS:-10}"
MEETING_LONG_SEC="${FIXTURE_MEETING_LONG_SECONDS:-120}"
PRESENTATION_SEC="${FIXTURE_PRESENTATION_SECONDS:-15}"
PRESENTATION_LONG_SEC="${FIXTURE_PRESENTATION_LONG_SECONDS:-120}"
SLIDE_SEC="${FIXTURE_SLIDE_SECONDS:-15}"
PRESENTATION_EN_OFFSET="${FIXTURE_PRESENTATION_EN_OFFSET_SECONDS:-30}"

extract_meeting_wav() {
  local url="$1"
  local offset="$2"
  local dest="$3"
  local seconds="$4"
  ffmpeg -hide_banner -loglevel error -y \
    -ss "$offset" -t "$seconds" -i "$url" \
    -vn -ac 1 -ar 16000 -acodec pcm_s16le \
    "$dest"
}

truncate_presentation_video() {
  local src="$1"
  local dest="$2"
  local offset="$3"
  local seconds="$4"
  ffmpeg -hide_banner -loglevel error -y \
    -ss "$offset" -t "$seconds" -i "$src" \
    -vf "scale=-2:360" \
    -c:v libx264 -pix_fmt yuv420p -preset veryfast -crf 28 \
    -c:a aac -ar 16000 -ac 1 \
    "$dest"
}

stream_presentation_video() {
  local url="$1"
  local dest="$2"
  local offset="$3"
  local seconds="$4"
  truncate_presentation_video "$url" "$dest" "$offset" "$seconds"
}

download_presentation_en() {
  if [[ -f "$PRESENTATION_EN_CACHE" && "${FORCE_FIXTURE_DOWNLOAD:-0}" != "1" ]]; then
    echo "cached: $PRESENTATION_EN_CACHE"
    return 0
  fi
  echo "download: $PRESENTATION_EN_URL"
  yt-dlp \
    --no-playlist \
    -f "best[height<=360][ext=mp4]/best[ext=mp4]/best" \
    --merge-output-format mp4 \
    -o "$PRESENTATION_EN_CACHE" \
    "$PRESENTATION_EN_URL"
}

echo "==> English meeting speech (AMI corpus, CC BY 4.0)"
extract_meeting_wav "$AMI_MEETING_URL" "$AMI_OFFSET_SEC" "$MEETING_EN_WAV" "$MEETING_SEC"
echo "==> English multi-speaker meeting (${MEETING_LONG_SEC}s, AMI ES2002a Mix-Headset)"
extract_meeting_wav "$AMI_MEETING_URL" "$AMI_OFFSET_SEC" "$MEETING_EN_LONG_WAV" "$MEETING_LONG_SEC"

echo "==> German spoken audio (CCC conference talk, CC BY 4.0)"
extract_meeting_wav "$CCC_PRESENTATION_URL" "$CCC_OFFSET_SEC" "$MEETING_DE_WAV" "$MEETING_SEC"
echo "==> German spoken audio (${MEETING_LONG_SEC}s)"
extract_meeting_wav "$CCC_PRESENTATION_URL" "$CCC_OFFSET_SEC" "$MEETING_DE_LONG_WAV" "$MEETING_LONG_SEC"

echo "==> English presentation video"
download_presentation_en
truncate_presentation_video "$PRESENTATION_EN_CACHE" "$PRESENTATION_EN_MP4" "$PRESENTATION_EN_OFFSET" "$PRESENTATION_SEC"
echo "==> English presentation video (${PRESENTATION_LONG_SEC}s)"
truncate_presentation_video "$PRESENTATION_EN_CACHE" "$PRESENTATION_EN_LONG_MP4" "$PRESENTATION_EN_OFFSET" "$PRESENTATION_LONG_SEC"

echo "==> German presentation video (CCC, streamed + truncated)"
stream_presentation_video "$CCC_PRESENTATION_URL" "$PRESENTATION_DE_MP4" "$CCC_OFFSET_SEC" "$PRESENTATION_SEC"
echo "==> German presentation video (${PRESENTATION_LONG_SEC}s)"
stream_presentation_video "$CCC_PRESENTATION_URL" "$PRESENTATION_DE_LONG_MP4" "$CCC_OFFSET_SEC" "$PRESENTATION_LONG_SEC"

echo "==> Synthetic slide deck (3 slides, for deterministic slide detection)"
uv run python scripts/generate_sample_video.py \
  -o "$PRESENTATION_SYNTH" \
  --slide-seconds "$SLIDE_SEC" \
  --slide-count 3

echo "==> Synthetic slide deck (${PRESENTATION_LONG_SEC}s, 8 slides)"
SLIDE_COUNT=$((PRESENTATION_LONG_SEC / SLIDE_SEC))
uv run python scripts/generate_sample_video.py \
  -o "$PRESENTATION_SYNTH_LONG" \
  --slide-seconds "$SLIDE_SEC" \
  --slide-count "$SLIDE_COUNT"

# Drop legacy / irrelevant fixtures from earlier iterations.
rm -f \
  "$WAV_DIR"/speech_5s_16k_mono.wav \
  "$WAV_DIR"/music_5s_16k_mono.wav \
  "$VIDEO_DIR"/talk_5s_360p.mp4 \
  "$VIDEO_DIR"/talk_12s_360p.mp4 \
  "$CACHE"/iamahsan_sample.wav \
  "$CACHE"/iamahsan_sample.mp3 \
  "$CACHE"/iamahsan_sample.mp4 \
  "$CACHE"/sample_download.mp4

echo ""
echo "Fixtures ready:"
ls -lh \
  "$MEETING_EN_WAV" "$MEETING_EN_LONG_WAV" \
  "$MEETING_DE_WAV" "$MEETING_DE_LONG_WAV" \
  "$PRESENTATION_EN_MP4" "$PRESENTATION_EN_LONG_MP4" \
  "$PRESENTATION_DE_MP4" "$PRESENTATION_DE_LONG_MP4" \
  "$PRESENTATION_SYNTH" "$PRESENTATION_SYNTH_LONG"
