## Desktop install (Phase 0+1)

Local desktop launcher for the Textual TUI on Linux (XDG), plus the macOS installer
(F5). This is **not** a Snap/Flatpak/deb/pkg yet — everything installs under your home
directory: the CLI via `uv tool`, a launch script, and (Linux) a `.desktop` entry.

### Prerequisites

- **Python 3.12+** and [uv](https://docs.astral.sh/uv/)
- **System audio tools:** `ffmpeg` (all platforms); `pactl` on Linux (PulseAudio/PipeWire)

On Ubuntu/Debian:

```bash
sudo apt install ffmpeg pulseaudio-utils
# PipeWire: ensure pipewire-pulse or wireplumber provides pactl
```

On macOS use the dedicated installer below — it handles ffmpeg (Homebrew) for you.
System audio needs **no** loopback driver on macOS 14.4+ (driver-free Core Audio
process tap; the tiny Swift helper compiles on first use and needs the Xcode command
line tools: `xcode-select --install`).

Optional extras (local STT, offline finalize) follow the same rules as the main README — pin Python 3.13 for PyTorch extras if needed.

### One-shot install — macOS

From the repository root:

```bash
task install:macos            # or: bash packaging/install-macos.sh
task install:macos -- --offline   # also install whisperx/diarization/mlx extras
task install:macos -- --dry-run   # preview every action without changing anything
```

This will:

1. Verify **Homebrew** (required; the script never curl-pipes installers) and
   `brew install` **ffmpeg** and **uv** only if missing
2. Warn if the **Xcode command line tools** are absent (needed once, for the Core
   Audio tap helper)
3. Install `live-transcriber` globally with `uv tool install --python 3.13` (with
   `--offline`: the `whisperx`, `diarization`, and `mlx` extras; `mlx` is
   marker-guarded to Apple Silicon)
4. Create the config directory (`live-transcriber paths --config-dir`; fresh installs:
   `~/Library/Application Support/live-meeting-transcriber`, existing XDG installs keep
   `~/.config/live-meeting-transcriber`)
5. Run `live-transcriber doctor` so you immediately see what (if anything) is missing

There is no `.desktop` entry on macOS — start the app from any terminal with
`live-transcriber tui`.

Uninstall (macOS):

```bash
uv tool uninstall live-meeting-transcriber
# Config/data stay in ~/Library/Application Support/live-meeting-transcriber
# (or the legacy XDG dirs) until you delete them yourself.
```

### One-shot install — Linux

From the repository root:

```bash
task install:desktop
```

This will:

1. Install `live-transcriber` globally with `uv tool install --editable .`
2. Copy `packaging/bin/notetaker-launch.sh` to `~/.local/bin/notetaker-launch`
3. Install `live-meeting-transcriber.desktop` to `~/.local/share/applications/`
4. Create `~/.config/live-meeting-transcriber/` (or `$XDG_CONFIG_HOME/live-meeting-transcriber/`)

After install, search the app menu for **Live Meeting Transcriber**, or run:

```bash
~/.local/bin/notetaker-launch
```

### Configuration (first run)

Settings load from **environment variables** and from `.env` files in this order (later overrides earlier):

1. `$XDG_CONFIG_HOME/live-meeting-transcriber/.env` (default: `~/.config/live-meeting-transcriber/.env`)
2. `./.env` in the current working directory (useful when developing in the repo)

Create your config file (`live-transcriber paths --config-dir` prints the right
directory for your platform and install):

```bash
CONFIG_DIR="$(live-transcriber paths --config-dir)"
mkdir -p "${CONFIG_DIR}"
printf 'OPENAI_API_KEY=sk-...\n' > "${CONFIG_DIR}/.env"
# see docs/configuration.md for all variables — or use the TUI Settings screen
```

The launch script warns on first run if that file is missing; the TUI still starts so you can explore, but recording/transcription needs valid settings.

### CLI default

With no subcommand, `live-transcriber` opens the TUI (same as `live-transcriber tui`). Subcommands (`record`, `sessions`, …) behave as before.

### Terminal support (TUI slide preview)

**Inline slide thumbnails** in Meetings → Slide preview use the optional **`tui-image`** extra:

```bash
uv sync --extra tui-image
```

They render reliably only in terminals with **graphics protocols** (Kitty graphics, Sixel, etc.):

| Terminal | Inline PNG preview |
|----------|-------------------|
| **Kitty**, **WezTerm**, **Ghostty** | Yes |
| **Terminator**, classic **xterm**, many default emulators | No — use workarounds below |

If inline preview is unavailable, the TUI still lists **candidate timestamps and scores** in the table. To view a frame:

- Press **`o`** in slide preview to open the PNG with **`xdg-open`** (or macOS `open`).
- Optional: install **`chafa`** for a coarse ASCII preview in the pane (`sudo apt install chafa` on Debian/Ubuntu).

For day-to-day use in Terminator, prefer **`o`** or a graphics-capable terminal for slide review.

### Manual install

```bash
chmod +x packaging/bin/notetaker-launch.sh
bash packaging/install-desktop.sh
```

Override install locations with `INSTALL_PREFIX` (default `~/.local`) if needed.

### Uninstall

```bash
uv tool uninstall live-meeting-transcriber
rm -f ~/.local/bin/notetaker-launch
rm -f ~/.local/share/applications/live-meeting-transcriber.desktop
# Keep ~/.config/live-meeting-transcriber/.env and app data unless you want a full reset
```
