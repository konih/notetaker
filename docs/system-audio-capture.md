# Capturing system audio (Teams / Zoom / Meet) alongside your microphone

By default the recorder captures **only your microphone**. Remote participants (the
audio your Mac *plays back* through the speakers) are **not** captured, because macOS
does not let an audio *input* stream read another app's *output* for privacy reasons.
To transcribe both sides of a call you need to route system output back in as an input,
then capture the microphone and that loopback as two channels.

This is why "I could transcribe my own voice but Teams wasn't captured": there was no
loopback device, so only the mic leg had signal.

- [macOS 14.4+ — native Core Audio tap (no BlackHole)](#macos-144--native-core-audio-tap-no-blackhole)
- [macOS — BlackHole loopback](#macos--blackhole-loopback)
- [Linux — PipeWire/PulseAudio monitor](#linux--pipewirepulseaudio-monitor)
- [Verify with a YouTube video](#verify-with-a-youtube-video)
- [Troubleshooting](#troubleshooting)

---

## macOS 14.4+ — native Core Audio tap (no BlackHole)

On **macOS 14.4 or newer** the recommended path needs **no third-party driver**. The app uses
**Core Audio process taps** to capture system output directly, via a tiny bundled Swift helper
(`native/macos/systemaudiotap.swift`). This is the default (`AUDIO_MACOS_SYSTEM_CAPTURE=auto`).

You still hear the meeting normally while it is captured (`muteBehavior = .unmuted`), and the
prompt is the **audio-only** "System Audio Recording Only" grant — not the screen-recording
prompt that ScreenCaptureKit-based tools require.

### Setup

1. Install the Xcode command line tools once (provides `swiftc`/`codesign`):
   ```bash
   xcode-select --install
   ```
2. Keep `AUDIO_MACOS_SYSTEM_CAPTURE=auto` (default). The helper is compiled and ad-hoc signed on
   first use into `~/.cache/live-meeting-transcriber/`.
3. `live-transcriber devices` shows **"System Audio (Core Audio tap — no BlackHole needed)"** as
   the default monitor source.
4. Start recording. The **first** capture triggers a one-time macOS prompt — click **Allow**.
   (Manage later under *System Settings ▸ Privacy & Security ▸ Audio Recording*.)

Your microphone is still captured and mixed in exactly as before, so both sides of a call are
transcribed. To force the old driver path instead, set `AUDIO_MACOS_SYSTEM_CAPTURE=avfoundation`
(see below). More detail: [`native/macos/README.md`](../native/macos/README.md).

> **Requirements:** macOS 14.4+, Xcode command line tools, and `ffmpeg` on `PATH`. On macOS 13
> or without `swiftc`, use the BlackHole path below.

---

## macOS — BlackHole loopback

> Only needed on **macOS 13 or older**, or if you set `AUDIO_MACOS_SYSTEM_CAPTURE=avfoundation`.
> On macOS 14.4+ prefer the [native Core Audio tap](#macos-144--native-core-audio-tap-no-blackhole)
> above — it needs no driver.

macOS has no built-in system-audio capture usable by ffmpeg. The supported path is a
free virtual loopback driver, **BlackHole**, combined with a **Multi-Output Device** so
you still *hear* the call while it is also fed to the recorder.

```
                       ┌──► Built-in / headphone output   (you hear the call)
Teams/Zoom output ──►  Multi-Output Device
                       └──► BlackHole 2ch                 (recorder captures as --source)

Microphone ───────────────────────────────────────────►  recorder captures as --microphone-source
```

### 1. Install BlackHole

```bash
brew install blackhole-2ch
```

(2 channels is enough — one system-audio stream. `blackhole-16ch` also works.)
After install, `BlackHole 2ch` appears in *System Settings ▸ Sound* and in
`live-transcriber devices`.

### 2. Create a Multi-Output Device (so you can still hear the call)

1. Open **Audio MIDI Setup** (`/Applications/Utilities/Audio MIDI Setup.app`).
2. Click **+** (bottom-left) ▸ **Create Multi-Output Device**.
3. Tick both **your normal output** (MacBook Pro Speakers or your headphones) **and
   BlackHole 2ch**. Put your real output **first** and enable **Drift Correction** on
   BlackHole.
4. Rename it something like `Meeting + BlackHole`.
5. In *System Settings ▸ Sound ▸ Output*, select this Multi-Output Device as the system
   output **during meetings** (Teams follows the system output unless overridden in
   Teams' own audio settings).

> Keep your **microphone** on your real mic (built-in / headset) — do **not** route the
> mic through BlackHole.

### 3. Run with explicit sources

Auto-detection is deliberately **not** relied on here. Your Mac also exposes a
"Microsoft Teams Audio Device", whose name matches the `teams audio` hint but only
carries audio when Teams is actively routing system sound — a misleading pick. The
recorder now prefers a real BlackHole/Loopback device over it, but the robust approach
is to name the source explicitly.

Find the device indices:

```bash
live-transcriber devices        # lists AVFoundation sources; note BlackHole and your mic
```

Then record with mic + system as two channels, transcribed separately:

```bash
AUDIO_CHANNELS=2 \
AUDIO_STEREO_MODE=dual_path \
TRANSCRIPTION_PROVIDER=faster_whisper \
live-transcriber record \
  --source ':<blackhole-index>' \
  --microphone-source ':<mic-index>'
```

- `--source` = the **BlackHole** index → becomes the **right** channel → labeled `REMOTE`.
- `--microphone-source` = your **mic** index → becomes the **left** channel → labeled `YOU`.
- `AUDIO_STEREO_MODE=dual_path` transcribes the two channels independently so speaker
  attribution is deterministic (mic = you, system = remote). This mode is
  **faster-whisper only** — the OpenAI provider does not do dual-path.
- Prefer `dual_path` over `mixdown`: `mixdown` sums both legs into one mono stream, after
  which you cannot tell your voice from the remote side.

You can persist the source choices via the TUI **Audio sources** menu (stored in
`~/.config/live-meeting-transcriber/device_prefs.json`) instead of passing flags each run.

### Which loopback driver?

| Driver | Cost | Notes |
|--------|------|-------|
| **BlackHole** (`brew install blackhole-2ch`) | Free | Recommended; recognized out of the box. |
| **Loopback** (Rogue Amoeba) | Paid | Nicer UI, easy per-app routing. Recognized (`loopback` hint). |
| **SoundFlower** | Free | Unmaintained; avoid on modern macOS. |

---

## Linux — PipeWire/PulseAudio monitor

On Linux **no extra driver is needed** — every output sink exposes a `.monitor` source
that carries what the sink plays. The recorder auto-detects it.

### Requirements

- **PipeWire** (with `pipewire-pulse`) or **PulseAudio**, plus the `pactl` CLI
  (`pulseaudio-utils` / `pipewire-pulse` package).
- **ffmpeg** with the `pulse` input (`ffmpeg -f pulse` — standard in distro builds).
- Your desktop must actually play the meeting audio through the default sink (the usual
  case). Verify: `pactl info | grep 'Default Sink'`.

### Run

Auto-detection resolves `--source` to `<default-sink>.monitor` and `--microphone-source`
to the default input, so often you just need:

```bash
AUDIO_CHANNELS=2 AUDIO_STEREO_MODE=dual_path TRANSCRIPTION_PROVIDER=faster_whisper \
live-transcriber record
```

To pin them explicitly (see names with `live-transcriber devices` or `pactl list short sources`):

```bash
AUDIO_CHANNELS=2 AUDIO_STEREO_MODE=dual_path TRANSCRIPTION_PROVIDER=faster_whisper \
live-transcriber record \
  --source 'alsa_output.pci-0000_00_1f.3.analog-stereo.monitor' \
  --microphone-source 'alsa_input.pci-0000_00_1f.3.analog-stereo'
```

> If the meeting app grabs an **exclusive** device or routes to a non-default sink,
> point `--source` at that sink's `.monitor` instead.

---

## Verify with a YouTube video

A quick end-to-end check that does not need a real call:

1. Set the system output to your Multi-Output Device (macOS) or ensure audio plays on the
   default sink (Linux).
2. Start `live-transcriber record` with the two-channel command above.
3. Play a talking-head YouTube video (clear speech, not music).
4. Also say a few words into your mic.
5. Stop, and inspect the transcript: the video's speech should appear as `REMOTE`, your
   words as `YOU`.

This proves **general** system capture works. Close the loop with a **real Teams call**
eventually — Teams' own audio routing can differ from browser/system playback.

---

## Troubleshooting

- **Only my voice is transcribed / `REMOTE` is empty.** System output is not reaching the
  loopback. macOS: confirm the **Multi-Output Device** is the selected system output *and*
  includes BlackHole; confirm Teams isn't pinned to a different output in its own settings.
  Linux: confirm the app plays on the default sink (`pactl info`).
- **I can't hear the call anymore.** The Multi-Output Device must include your real
  speakers/headphones *and* BlackHole. A plain BlackHole output (no speakers) is silent to
  you.
- **`Could not auto-detect default monitor source`.** No loopback device is installed
  (macOS) — install BlackHole. Or pass `--source` explicitly.
- **Auto-detect picked the wrong device.** Pass `--source ':<index>'` explicitly. The
  "Microsoft Teams Audio Device" is intentionally ranked last, but explicit is safest.
- **No speaker split (`YOU`/`REMOTE`).** You must use `TRANSCRIPTION_PROVIDER=faster_whisper`
  with `AUDIO_STEREO_MODE=dual_path` and two **different** devices on the two channels.
  If both legs are the same device the channels aren't separable.

See also: [configuration.md](configuration.md) for the full env-var reference, and
[roadmap.md](roadmap.md) for the planned native (ScreenCaptureKit) capture and YAML config.
