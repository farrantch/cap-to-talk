<div align="center">
  <img src="docs/assets/icon.png" alt="Cap to Talk icon" width="144">
  <h1>Cap to Talk</h1>
  <p><strong>Hold Caps Lock. Speak. Release. Keep typing.</strong></p>
  <p>Private-by-default push-to-talk dictation for Linux/X11, powered by local AI.</p>

  [![CI](https://github.com/farrantch/cap-to-talk/actions/workflows/ci.yml/badge.svg)](https://github.com/farrantch/cap-to-talk/actions/workflows/ci.yml)
  [![Latest release](https://img.shields.io/github/v/release/farrantch/cap-to-talk)](https://github.com/farrantch/cap-to-talk/releases/latest)
  [![License: MIT](https://img.shields.io/badge/license-MIT-31c3e0.svg)](LICENSE)
  ![Platform: Linux/X11](https://img.shields.io/badge/platform-Linux%2FX11-ff6b5f.svg)
</div>

![Cap to Talk recording, transcription, cleanup, and insertion demo](docs/assets/demo.gif)

Cap to Talk turns Caps Lock into a system-wide dictation key. It records while
the key is held, transcribes with [OpenASR](https://github.com/QuintinShaw/openasr),
optionally cleans up the wording with [Ollama](https://ollama.com/), and inserts
the result into the window where you started speaking. The default setup runs
entirely on your machine and needs no cloud API key.

## Highlights

- **Natural push-to-talk:** hold Caps Lock to record and release to insert.
- **Two modes:** Caps Lock cleans up the transcript; Shift + Caps Lock inserts
  the raw transcription.
- **Local processing:** default OpenASR and Ollama endpoints use loopback only.
- **Right-window insertion:** remembers the original window while processing.
- **Personal vocabulary:** recognition hints and a larger spelling glossary.
- **Safe fallbacks:** inserts the raw transcript if cleanup is unavailable.
- **Privacy-conscious defaults:** transcript logging is off and temporary audio
  is deleted after each request.

## Requirements

- Ubuntu 24.04+ or a compatible Debian-based Linux distribution
- An **X11** desktop session (native Wayland is not yet supported)
- Python 3.12 or newer and a working microphone
- About 3.5 GB for the default local models; 8 GB RAM is recommended

Cap to Talk temporarily remaps Caps Lock while it runs and restores the prior
keyboard layout when it exits normally.

## Quick install

```bash
git clone https://github.com/farrantch/cap-to-talk.git
cd cap-to-talk
./install.sh
```

The installer shows its plan before changing anything. It installs missing
desktop packages, downloads OpenASR and Ollama from their official installers
when needed, pulls the two default models, configures autostart, and starts Cap
to Talk. It may ask for your sudo password for system packages.

Existing configuration and glossary files are preserved, so rerunning the
installer is safe. For an unattended install, use `./install.sh --yes`; add
`--no-start` to wait until the next login before starting the app.

<details>
<summary>What the installer creates</summary>

| Path | Purpose |
| --- | --- |
| `.venv/` | Project-local Python environment |
| `~/.local/bin/cap-to-talk` | Command symlink |
| `~/.config/cap-to-talk/` | Configuration and personal glossaries |
| `~/.config/autostart/cap-to-talk.desktop` | Desktop-session autostart |
| `~/.config/systemd/user/cap-to-talk-openasr.service` | Namespaced OpenASR service |
| `~/.local/state/cap-to-talk/` | Runtime logs |

Shared OpenASR and Ollama installations and downloaded models remain under
their own management.

</details>

## Use it

| Shortcut | Result |
| --- | --- |
| Hold **Caps Lock**, then release | Transcribe, clean up, and insert |
| Hold **Shift + Caps Lock**, then release | Transcribe and insert without cleanup |

Check the complete local setup at any time:

```bash
cap-to-talk check
```

If `~/.local/bin` is not on your shell's `PATH`, run
`.venv/bin/cap-to-talk check` from the repository instead.

The flow is deliberately simple:

```mermaid
flowchart LR
    A[Hold Caps Lock] --> B[Record microphone]
    B --> C[OpenASR transcript]
    C --> D[Ollama cleanup]
    D --> E[Insert in original window]
    C -->|Shift held or cleanup unavailable| E
```

## Personal vocabulary

Edit these files with one term per line:

- `~/.config/cap-to-talk/hotwords.txt` contains up to 128 focused recognition
  hints sent to OpenASR.
- `~/.config/cap-to-talk/master-hotwords.txt` can hold a larger dictionary. Cap
  to Talk selects contextually relevant spellings for the cleanup model.

Blank lines and lines beginning with `#` are ignored. Restart Cap to Talk after
editing either file. The installer migrates existing glossary files from the
older `~/.config/voice-dictate/` location without deleting the originals.

## Configuration

The installer creates `~/.config/cap-to-talk/config.toml` from
[`config/config.example.toml`](config/config.example.toml). Every option is
optional; the shipped file documents all defaults.

```toml
[audio]
post_roll_seconds = 0.25

[services]
asr_url = "http://127.0.0.1:8080/v1/audio/transcriptions"
rewrite_model = "qwen3:4b-instruct"

[output]
typing_delay_ms = 0

[privacy]
debug_transcripts = false
```

Useful environment overrides include:

| Variable | Purpose |
| --- | --- |
| `CAP_TO_TALK_PTT_KEYCODE` | X11 keycode used for push-to-talk |
| `CAP_TO_TALK_ASR_URL` | OpenASR transcription endpoint |
| `CAP_TO_TALK_OLLAMA_URL` | Ollama chat endpoint |
| `CAP_TO_TALK_REWRITE_MODEL` | Ollama cleanup model |
| `CAP_TO_TALK_TYPING_DELAY_MS` | Delay between synthetic keystrokes |

Run with another configuration file using
`cap-to-talk --config /path/to/config.toml`. Command-line `--debug` enables
debug logging, including transcript contents, for that run.

## Privacy

With the default configuration, microphone audio goes only to OpenASR on
`127.0.0.1`, and transcript text goes only to Ollama on `127.0.0.1`. No cloud
service or API key is involved.

A WAV file briefly exists in the operating system's temporary directory during
transcription and is deleted immediately afterward, including on request
failure. Transcript contents are not logged unless `--debug` or
`debug_transcripts = true` is enabled. Changing service URLs to remote hosts
changes these privacy assumptions.

## Troubleshooting

Start with:

```bash
cap-to-talk check
```

### Caps Lock does nothing

Confirm `echo "$XDG_SESSION_TYPE"` prints `x11`, then inspect
`~/.local/state/cap-to-talk/cap-to-talk.log`. Another global shortcut manager
may already own Caps Lock.

### The microphone is unavailable

```bash
.venv/bin/python -c 'import sounddevice; print(sounddevice.query_devices())'
```

Confirm the desktop session has microphone access and a default input device.

### Transcription fails

```bash
curl -f http://127.0.0.1:8080/health
systemctl --user status cap-to-talk-openasr.service
```

### Cleanup fails or raw text is inserted

```bash
curl -f http://127.0.0.1:11434/api/tags
ollama list
```

Cap to Talk intentionally keeps the raw OpenASR result when Ollama cleanup
fails, rather than losing the dictation.

## Uninstall

```bash
./uninstall.sh
```

This removes Cap to Talk's environment, command links, autostart entry, and
namespaced OpenASR service. Personal configuration and logs are preserved. Use
`./uninstall.sh --purge` to remove those too. Shared OpenASR/Ollama installs and
models are never removed automatically.

<details>
<summary>Manual setup and non-Debian distributions</summary>

Install equivalents for `curl`, `libnotify`, PortAudio, Tk, Python venv,
`util-linux`, `setxkbmap`, `xkbcomp`, `xdotool`, and `xprintidle`. Install
OpenASR and Ollama using their official instructions, then prepare the models:

```bash
openasr pull qwen3-asr-0.6b:q8
ollama pull qwen3:4b-instruct
```

Start OpenASR on `127.0.0.1:8080`, ensure Ollama is running, and finish the
user-local setup:

```bash
./scripts/install-user.sh
./scripts/start.sh
```

</details>

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Please
report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## Acknowledgments

Cap to Talk builds on [OpenASR](https://github.com/QuintinShaw/openasr),
[Ollama](https://ollama.com/), and the Qwen speech and language models. Review
their repositories and model pages for their respective licenses and usage
terms.

Released under the [MIT License](LICENSE).
