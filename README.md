<div align="center">
  <img src="docs/assets/icon-wide.png" alt="Cap To Talk logo" width="360">
  <h1>Cap To Talk</h1>
  <p><strong>Push-to-talk dictation, local by default.</strong></p>

  [![CI](https://github.com/farrantch/cap-to-talk/actions/workflows/ci.yml/badge.svg)](https://github.com/farrantch/cap-to-talk/actions/workflows/ci.yml)
  [![Latest release](https://img.shields.io/github/v/release/farrantch/cap-to-talk)](https://github.com/farrantch/cap-to-talk/releases/latest)
  [![License: MIT](https://img.shields.io/badge/license-MIT-31c3e0.svg)](LICENSE)
  ![Platform: Linux/X11](https://img.shields.io/badge/platform-Linux%2FX11-ff6b5f.svg)
</div>

![Cap To Talk recording, transcription, cleanup, and insertion demo](docs/assets/demo.gif)

Cap To Talk turns a keyboard shortcut into a system-wide dictation key. It records while
the key is held, transcribes with [OpenASR](https://github.com/QuintinShaw/openasr),
optionally cleans up the wording with [Ollama](https://ollama.com/), and inserts
the result into the window where you started speaking. The default setup runs
entirely on your machine and needs no cloud API key. You can independently select
OpenAI or compatible services for transcription, and Ollama, OpenAI, compatible
services, or Anthropic for cleanup. You can also choose one audio-capable model
that transcribes and cleans up in a single request, or disable cleanup.

## Platforms

| Platform | Default shortcut | Status |
| --- | --- | --- |
| Linux/X11 | Caps Lock | Existing installer and desktop integration |
| Windows | Caps Lock | Experimental source adapter; desktop testing needed |
| macOS | F8 | Experimental source adapter; desktop testing needed |

All platforms use the same provider configuration and dictation pipeline.
See the [desktop app guide](docs/desktop-app.md) for the settings window and
[release guide](docs/releasing.md) for installer builds. Public signed installers
are pending desktop validation and signing setup.

## Desktop app preview

The desktop app adds a settings window and tray/menu-bar controls for providers,
models, credentials, microphones, and shortcuts. Install it from this checkout:

```bash
python -m pip install -e ".[desktop]"
cap-to-talk-desktop
```

Use **Check setup** and **Test microphone** before starting dictation.
See the [desktop guide](docs/desktop-app.md) for permissions and provider setup.
Maintainers can create native installers using the [release workflow](docs/releasing.md).

## Linux requirements

- Ubuntu 24.04+ or a compatible Debian-based Linux distribution
- An **X11** desktop session (native Wayland is not yet supported)
- Python 3.12 or newer and a working microphone
- About 3.5 GB for the default local models; 8 GB RAM is recommended for local use

Cap To Talk temporarily remaps Caps Lock while it runs and restores the prior
keyboard layout when it exits normally.

## Install on Linux

```bash
git clone https://github.com/farrantch/cap-to-talk.git
cd cap-to-talk
```

### On demand (default)

```bash
./install.sh
```

Cap To Talk starts after installation. After a later login, start it from the
checkout with `./scripts/start.sh`.

### Start at login

```bash
./install.sh --autostart
```

Cap To Talk starts after installation and automatically at future desktop logins.

Both methods install the required packages and local models while preserving
existing settings. Add `--no-start` to leave Cap To Talk stopped after installation
or `--yes` for an unattended install; flags can be combined.

## Use it

| Shortcut | Result |
| --- | --- |
| Hold the dictation key, then release | Transcribe, clean up, and insert |
| Hold **Shift + the dictation key**, then release | Request raw transcription |

The dictation key defaults to Caps Lock on Linux/Windows and F8 on macOS.
Choose another function key with `[input].hotkey = "f9"`. Hold Shift before
pressing the key to select raw mode; release the keys before text is inserted.

Check the setup at any time:

```bash
cap-to-talk check
```

## Personal vocabulary

Edit these files in your configuration directory with one term per line
(the paths below show Linux defaults):

- `~/.config/cap-to-talk/hotwords.txt` contains up to 128 focused recognition
  hints sent to the selected transcription or audio dictation provider.
- `~/.config/cap-to-talk/master-hotwords.txt` can hold a larger dictionary.
  In two-stage mode, Cap To Talk selects relevant spellings for the cleanup
  model. Single-model dictation uses the focused recognition hints above.

Blank lines and lines beginning with `#` are ignored. Restart Cap To Talk after
editing either file.

## Configuration

Edit `config.toml` to change audio, shortcuts, providers, output, or privacy
settings. The default locations are:

| Platform | Configuration file |
| --- | --- |
| Linux | `~/.config/cap-to-talk/config.toml` |
| macOS | `~/Library/Application Support/cap-to-talk/config.toml` |
| Windows | `%APPDATA%\cap-to-talk\config.toml` |

Use `--config PATH` to select another file. An explicit `XDG_CONFIG_HOME`
overrides the platform default. All options are documented in
[`config/config.example.toml`](config/config.example.toml).

### AI providers

Choose speech recognition and cleanup separately, or let one audio-capable
model do both in a single request. Keep the default local setup, use cloud
services, or turn cleanup off. See [AI provider configuration](docs/providers.md)
for examples, API-key setup, custom endpoints, and connection checks.

On Linux, for an installation using existing or cloud services, use
`./install.sh --skip-local-services --no-start`, configure your providers, then
run `./scripts/start.sh`.

## Privacy

By default, audio and transcript text stay on your machine. Audio uploads are
prepared in memory, and transcripts are not logged unless debug logging is enabled. If you select a remote provider, audio goes to the transcription
provider; transcript text and relevant vocabulary go to the cleanup provider.
In single-model mode, the recording, instructions, and enabled recognition hints
go to the selected dictation provider.
API keys come from the selected environment variable or your system credential
store. See [data handling](docs/providers.md#data-handling-and-failure-behavior).

<details>
<summary>Troubleshooting</summary>

Start with:

```bash
cap-to-talk check
```

### The shortcut does nothing

On macOS or Windows, follow the [platform setup and permissions](docs/desktop.md#macos-and-windows-setup)
and inspect the terminal running Cap To Talk.

On Linux, confirm `echo "$XDG_SESSION_TYPE"` prints `x11`, then inspect
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

In two-stage mode, Cap To Talk uses the raw transcript when cleanup is
unavailable. Single-model mode has no separate raw transcript to fall back to;
a provider failure inserts nothing. Use `cap-to-talk check --services-only` to
check the active provider configuration.

</details>

## Uninstall on Linux

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

Pass `--autostart` to `install-user.sh` if Cap To Talk should start automatically
at desktop login. Without that flag, the setup is idempotently configured for
on-demand use.

</details>

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and
[Desktop integrations](docs/desktop.md) for platform setup, adapter behavior, and
manual validation. Report security
issues privately as described in [SECURITY.md](SECURITY.md).

## Acknowledgments

Cap To Talk builds on [OpenASR](https://github.com/QuintinShaw/openasr),
[Ollama](https://ollama.com/), and the Qwen speech and language models. Review
their repositories and model pages for their respective licenses and usage
terms.

Released under the [MIT License](LICENSE).
