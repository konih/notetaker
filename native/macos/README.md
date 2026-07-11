# `systemaudiotap` — macOS system-audio helper (BlackHole alternative)

`systemaudiotap.swift` captures macOS **system/output** audio without any third-party virtual
driver, using **Core Audio process taps** (macOS 14.4+). It is the native backend behind
`AUDIO_MACOS_SYSTEM_CAPTURE=auto|coreaudio_tap` — see
[`docs/system-audio-capture.md`](../../docs/system-audio-capture.md) and
[`docs/configuration.md`](../../docs/configuration.md).

## How it works

1. A global system tap (`CATapDescription(stereoGlobalTapButExcludeProcesses: [])`,
   `muteBehavior = .unmuted`, so you still hear the meeting) is created with
   `AudioHardwareCreateProcessTap`.
2. The tap is wrapped in a **private aggregate device** (`AudioHardwareCreateAggregateDevice`)
   that auto-starts it.
3. An IO-proc block copies the delivered PCM to `--out`; the tap's native format
   (`rate=<hz> ch=<n> float=<0|1>`) is printed to stderr. During pure silence the tap delivers
   no buffers, so the file may be empty — the Python adapter pads those chunks with silence.

The Python adapter (`live_meeting_transcriber/audio/coreaudio_tap.py`) then hands the raw PCM to
ffmpeg to produce the per-chunk WAV the app expects.

## Build (automated)

The app compiles and ad-hoc code-signs the helper on first use into
`~/.cache/live-meeting-transcriber/systemaudiotap` (or `$XDG_CACHE_HOME/...`). This needs the
Xcode command line tools:

```bash
xcode-select --install   # provides swiftc + codesign
```

To build manually (what the adapter runs):

```bash
swiftc native/macos/systemaudiotap.swift -O -o systemaudiotap \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker native/macos/Info.plist
codesign -s - --force systemaudiotap        # ad-hoc signature
./systemaudiotap --out /tmp/sys.f32 --seconds 3   # writes raw f32le PCM
```

> The embedded `Info.plist` (`NSAudioCaptureUsageDescription`) **and** a code signature are both
> required, or the macOS permission prompt never fires and capture returns silence.
>
> Note: the app uses an **ad-hoc** signature, which changes the binary's cdhash on every
> rebuild. macOS ties the grant to the cdhash, so a rebuild (e.g. after updating the app) can
> re-trigger the one-time "System Audio Recording" prompt — approve it again if asked.

## Manual operator checklist (the permission step needs a human)

The "System Audio Recording Only" grant is an interactive prompt tied to the signed binary — it
cannot be approved from a headless/CI session. To verify capture on a real machine:

1. macOS 14.4 or newer, Xcode command line tools installed, `ffmpeg` on `PATH`.
2. Leave `AUDIO_MACOS_SYSTEM_CAPTURE=auto` (the default). Confirm the tap shows up:
   `live-transcriber devices` lists **"System Audio (Core Audio tap — no BlackHole needed)"**.
3. Start a recording (`live-transcriber record`) with some audio playing (e.g. a YouTube video).
4. On first capture macOS shows **"…would like to record this computer's audio"** — click
   **Allow**. (Re-check later under *System Settings ▸ Privacy & Security ▸ Audio Recording*.)
5. Confirm the transcript contains the played-back audio, with **no BlackHole installed**.

If `swiftc` is missing, the app raises a clear error; install the CLT or set
`AUDIO_MACOS_SYSTEM_CAPTURE=avfoundation` and use a BlackHole loopback device instead.

## Code scanning (CodeQL) — Swift intentionally excluded

This lone `.swift` file has no `Package.swift`/`.xcodeproj` build target, so GitHub CodeQL's
Swift autobuild produces no database and the `/language:swift` analysis errors
(`unsuccessful execution`). Rather than stand up a Swift build harness just for scanning, the
repo's CodeQL **default setup** is pinned to `python` + `actions` only (Swift excluded) — see
story **C5**. If this helper ever grows into a real Swift build target, re-enable Swift scanning
deliberately (advanced setup with an explicit language matrix + build step).
