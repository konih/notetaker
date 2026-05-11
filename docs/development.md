## Development

### Requirements

- Python 3.12+
- `uv`
- Linux packages:
  - `pulseaudio-utils` (for `pactl`)
  - `ffmpeg`

### Install

```bash
task install
```

### Quality checks

```bash
task check
```

### Running locally

```bash
task devices
task run
task tui
```

### Integration tests

Integration tests are skipped unless explicitly enabled:

```bash
RUN_INTEGRATION_TESTS=1 task test:integration
```
