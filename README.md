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

## Quick install

On an Ubuntu or Debian X11 desktop:

```bash
git clone git@github.com:farrantch/cap-to-talk.git
cd cap-to-talk
./install.sh
```

The installer may ask for your sudo password and downloads several gigabytes of
local models. It:

- installs the required Ubuntu/Debian packages;
- installs [OpenASR](https://github.com/QuintinShaw/openasr) and
  [Ollama](https://ollama.com/) if they are missing;
- downloads the `qwen3-asr-0.6b` and `qwen3:4b-instruct` models;
- creates and starts the local OpenASR service;
- creates the Python environment, example glossaries, and desktop autostart
  entry; and
- starts Cap to Talk immediately when run from an X11 desktop.

Existing glossary files are preserved, so the installer is safe to rerun.
Review `install.sh` first if you prefer not to run automated installers.

Cap to Talk requires **X11** and a working microphone. Native Wayland is not
supported because the app grabs a global X11 key and inserts text with
`xdotool`.

<details>
<summary>Manual setup or other Linux distributions</summary>

Install equivalents for these Ubuntu packages:

```text
curl libnotify-bin libportaudio2 python3-tk python3-venv
x11-xserver-utils xdotool xprintidle
```

Install OpenASR using its
[official instructions](https://github.com/QuintinShaw/openasr#install), then:

```bash
openasr pull qwen3-asr-0.6b:q8
openasr serve --model qwen3-asr-0.6b --addr 127.0.0.1:8080
```

In another terminal, install Ollama using its
[official Linux instructions](https://docs.ollama.com/linux), then:

```bash
ollama pull qwen3:4b-instruct
```

Finally, from the repository directory:

```bash
./scripts/install-user.sh
./scripts/start.sh
```

</details>

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
