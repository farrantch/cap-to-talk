# Cap to Talk

Local, push-to-talk dictation for Linux/X11. Hold **Caps Lock** to record,
release it to transcribe, and the cleaned-up text is inserted into the window
where dictation started.

`Caps Lock → microphone → OpenASR → Ollama cleanup → xdotool insertion`

All speech recognition and rewriting use services on `127.0.0.1` by default.
No cloud API key is required.

## Features

- **Caps Lock** records and inserts a cleaned-up transcript.
- **Shift + Caps Lock** skips the rewrite and inserts raw transcription.
- Remembers the target window even if focus changes while processing.
- Waits for a keyboard/mouse pause before temporarily returning to the target.
- Uses personal hotword lists to improve technical spellings.
- Falls back to raw transcription if Ollama is unavailable.
- Shows desktop notifications and an optional corner status overlay.
- Deletes each temporary WAV after transcription.

## Requirements

This implementation targets an **X11 desktop session**. It does not support
native Wayland because it grabs a global X11 key and types with `xdotool`.

- Linux with X11
- Python 3.10+
- [OpenASR](https://github.com/QuintinShaw/openasr) with the
  `qwen3-asr-0.6b` model
- [Ollama](https://ollama.com/) with the `qwen3:4b-instruct` model
- A working microphone

On Ubuntu/Debian, install the desktop and audio dependencies:

```bash
sudo apt update
sudo apt install \
  curl libnotify-bin libportaudio2 python3-tk python3-venv \
  x11-xserver-utils xdotool xprintidle
```

## Setup

### 1. Install and start OpenASR

Follow the [OpenASR installation instructions](https://github.com/QuintinShaw/openasr#install),
then download the model:

```bash
openasr pull qwen3-asr-0.6b:q8
```

For a quick test, run the local server in a terminal:

```bash
openasr serve --model qwen3-asr-0.6b --addr 127.0.0.1:8080
```

To run it as a user service, install the included template from the repository
directory:

```bash
mkdir -p ~/.config/systemd/user
sed "s|@OPENASR_BIN@|$(command -v openasr)|" \
  systemd/openasr.service.in \
  > ~/.config/systemd/user/openasr.service
systemctl --user daemon-reload
systemctl --user enable --now openasr.service
```

### 2. Install Ollama and the rewrite model

Install Ollama using its [Linux instructions](https://docs.ollama.com/linux),
make sure the service is running, and pull the model:

```bash
ollama pull qwen3:4b-instruct
curl -sf http://127.0.0.1:11434/api/tags >/dev/null && echo "Ollama is ready"
```

### 3. Install the dictation app

```bash
git clone git@github.com:farrantch/cap-to-talk.git
cd cap-to-talk
chmod +x scripts/install-user.sh scripts/start.sh
./scripts/install-user.sh
```

The installer creates `.venv`, installs the Python packages, adds safe example
glossaries under `~/.config/voice-dictate/`, and creates an XDG autostart entry.
It leaves existing glossary files untouched.

Log out and back in, or start it immediately:

```bash
./scripts/start.sh
```

## Usage

| Shortcut | Result |
| --- | --- |
| Hold **Caps Lock**, then release | Transcribe, clean up, and insert |
| Hold **Shift + Caps Lock**, then release | Transcribe and insert without cleanup |

The script disables Caps Lock's normal toggle behavior for the current X11
session. Stop the process and reset your keyboard layout if you want the
original Caps Lock behavior back.

## Personal spellings and hotwords

Edit these plain-text files, with one term per line:

- `~/.config/voice-dictate/hotwords.txt` — up to 128 focused terms sent to
  OpenASR as recognition hints.
- `~/.config/voice-dictate/master-hotwords.txt` — a larger dictionary. The app
  fuzzy-matches the raw transcript and sends only the most relevant spellings
  to the cleanup model.

Blank lines and lines beginning with `#` are ignored. Restart the dictation app
after changing either file.

## Configuration

The defaults are near the top of `src/cap_to_talk.py`:

| Setting | Default | Purpose |
| --- | --- | --- |
| `PTT_KEYCODE` | `66` | Physical X11 Caps Lock keycode |
| `POST_ROLL_SECONDS` | `0.25` | Captures the end of the last word |
| `ASR_URL` | `http://127.0.0.1:8080/v1/audio/transcriptions` | OpenASR endpoint |
| `ASR_MODEL` | `qwen3-asr-0.6b` | Transcription model name |
| `OLLAMA_URL` | `http://127.0.0.1:11434/api/chat` | Ollama chat endpoint |
| `REWRITE_MODEL` | `qwen3:4b-instruct` | Transcript cleanup model |

## Troubleshooting

**Nothing happens when Caps Lock is pressed**

- Confirm `echo "$XDG_SESSION_TYPE"` prints `x11`.
- Check that another application has not grabbed Caps Lock.
- Run `./scripts/start.sh` in a terminal and inspect the error output.

**Microphone error**

List devices with:

```bash
.venv/bin/python -c 'import sounddevice; print(sounddevice.query_devices())'
```

Then verify that the desktop session has microphone permission and a default
input device.

**Transcription fails**

```bash
curl -f http://127.0.0.1:8080/health
systemctl --user status openasr.service
```

**Cleanup fails or raw text is inserted**

```bash
curl -f http://127.0.0.1:11434/api/tags
ollama ls
```

If Ollama fails, the app deliberately inserts the raw OpenASR transcript rather
than discarding the dictation.

## Privacy notes

With the default URLs, audio and text are sent only to local loopback services.
Temporary audio files are deleted after each transcription. Raw and cleaned
transcripts are printed to the process output for debugging, so consider your
desktop session logs sensitive. Changing either endpoint to a remote address
changes these privacy assumptions.
