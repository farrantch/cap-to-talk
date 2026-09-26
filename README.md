<div align="center">
  <img src="docs/assets/icon-wide.png" alt="Caps Talk logo" width="360">
  <h1>Caps Talk</h1>
  <p>Push-to-talk dictation for Linux/X11, powered by local AI.</p>

  [![CI](https://github.com/farrantch/caps-talk/actions/workflows/ci.yml/badge.svg)](https://github.com/farrantch/caps-talk/actions/workflows/ci.yml)
  [![Latest release](https://img.shields.io/github/v/release/farrantch/caps-talk)](https://github.com/farrantch/caps-talk/releases/latest)
  [![License: MIT](https://img.shields.io/badge/license-MIT-31c3e0.svg)](LICENSE)
  ![Platform: Linux/X11](https://img.shields.io/badge/platform-Linux%2FX11-ff6b5f.svg)
</div>

![Caps Talk recording, transcription, cleanup, and insertion demo](docs/assets/demo.gif)

Caps Talk turns Caps Lock into a system-wide dictation key. It records while
the key is held, transcribes with [OpenASR](https://github.com/QuintinShaw/openasr),
optionally cleans up the wording with [Ollama](https://ollama.com/), and inserts
the result into the window where you started speaking. The default setup runs
entirely on your machine and needs no cloud API key.

## Requirements

- Ubuntu 24.04+ or a compatible Debian-based Linux distribution
- An **X11** desktop session (native Wayland is not yet supported)
- Python 3.12 or newer and a working microphone
- About 3.5 GB for the default local models; 8 GB RAM is recommended

Caps Talk temporarily remaps Caps Lock while it runs and restores the prior
keyboard layout when it exits normally.

## Install

```bash
git clone https://github.com/farrantch/caps-talk.git
cd caps-talk
```

### On demand (default)

```bash
./install.sh
```

Caps Talk starts after installation. After a later login, start it from the
checkout with `./scripts/start.sh`.

### Start at login

```bash
./install.sh --autostart
```

Caps Talk starts after installation and automatically at future desktop logins.

Both methods install the required packages and local models while preserving
existing settings. Add `--no-start` to leave Caps Talk stopped after installation
or `--yes` for an unattended install; flags can be combined.

## Use it

| Shortcut | Result |
| --- | --- |
| Hold **Caps Lock**, then release | Transcribe, clean up, and insert |
| Hold **Shift + Caps Lock**, then release | Transcribe and insert without cleanup |

Check the setup at any time:

```bash
caps-talk check
```

## Personal vocabulary

Edit these files with one term per line:

- `~/.config/caps-talk/hotwords.txt` contains up to 128 focused recognition
  hints sent to OpenASR.
- `~/.config/caps-talk/master-hotwords.txt` can hold a larger dictionary.
  Caps Talk selects contextually relevant spellings for the cleanup model.

Blank lines and lines beginning with `#` are ignored. Restart Caps Talk after
editing either file.

## Configuration

Edit `~/.config/caps-talk/config.toml` to change audio, service, output, or
privacy settings. All available options and defaults are documented in
[`config/config.example.toml`](config/config.example.toml).

## Privacy

By default, audio and transcript text stay on your machine. Temporary audio is
deleted after each request, and transcripts are not logged unless debug logging
is enabled.

<details>
<summary>Troubleshooting</summary>

Start with:

```bash
caps-talk check
```

### Caps Lock does nothing

Confirm `echo "$XDG_SESSION_TYPE"` prints `x11`, then inspect
`~/.local/state/caps-talk/caps-talk.log`. Another global shortcut manager
may already own Caps Lock.

### The microphone is unavailable

```bash
.venv/bin/python -c 'import sounddevice; print(sounddevice.query_devices())'
```

Confirm the desktop session has microphone access and a default input device.

### Transcription fails

```bash
curl -f http://127.0.0.1:8080/health
systemctl --user status caps-talk-openasr.service
```

### Cleanup fails or raw text is inserted

```bash
curl -f http://127.0.0.1:11434/api/tags
ollama list
```

Caps Talk uses the raw transcript when cleanup is unavailable.

</details>

## Uninstall

```bash
./uninstall.sh
```

Personal settings and logs are preserved. Use `./uninstall.sh --purge` to remove
them too. Shared OpenASR and Ollama installations are left alone.

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

Pass `--autostart` to `install-user.sh` if Caps Talk should start automatically
at desktop login. Without that flag, the setup is idempotently configured for
on-demand use.

</details>

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup. Report security
issues privately as described in [SECURITY.md](SECURITY.md).

## Acknowledgments

Caps Talk builds on [OpenASR](https://github.com/QuintinShaw/openasr),
[Ollama](https://ollama.com/), and the Qwen speech and language models. Review
their repositories and model pages for their respective licenses and usage
terms.

Released under the [MIT License](LICENSE).
