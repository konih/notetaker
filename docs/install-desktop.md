## Desktop install (Phase 0+1)

Local desktop launcher for the Textual TUI on Linux (XDG). This is **not** a Snap/Flatpak/deb package yet — it installs the CLI via `uv tool`, a launch script, and a `.desktop` entry under your home directory.

### Prerequisites

- **Python 3.12+** and [uv](https://docs.astral.sh/uv/)
- **System audio tools:** `ffmpeg`, `pactl` (PulseAudio/PipeWire)

On Ubuntu/Debian:

```bash
sudo apt install ffmpeg pulseaudio-utils
# PipeWire: ensure pipewire-pulse or wireplumber provides pactl
```

Optional extras (local STT, offline finalize) follow the same rules as the main README — pin Python 3.13 for PyTorch extras if needed.

### One-shot install

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

Create your config file:

```bash
mkdir -p ~/.config/live-meeting-transcriber
cp .env.example ~/.config/live-meeting-transcriber/.env
# edit OPENAI_API_KEY, DATABASE_URL, etc.
```

The launch script warns on first run if that file is missing; the TUI still starts so you can explore, but recording/transcription needs valid settings.

### CLI default

With no subcommand, `live-transcriber` opens the TUI (same as `live-transcriber tui`). Subcommands (`record`, `sessions`, …) behave as before.

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
