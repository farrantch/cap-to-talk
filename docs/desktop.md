# Desktop integrations

Cap To Talk has adapters for Linux/X11, Windows, and macOS. The Windows and macOS
adapters are experimental: their behavior is covered by simulated tests, but
recording, permissions, and insertion still need validation on real desktops.
The Linux shell installer remains the supported automated setup.

## macOS and Windows setup

These instructions run the app from a source checkout with Python 3.12 or newer.
Clone the repository and enter its directory first. Use the terminal to start
and stop command-line dictation. The [desktop settings app](desktop-app.md)
and [installer build workflow](releasing.md) provide a graphical launch path.

### Install dependencies

On macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

On Windows, in PowerShell with Python 3.12 installed:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

The package installs PyObjC frameworks only on macOS and uses Windows APIs
through Python's standard library on Windows. Neither port needs X11.
The audio dependency supplies PortAudio when installed with pip on these
platforms; see the [sounddevice installation guide](https://python-sounddevice.readthedocs.io/en/latest/installation.html).

### Configure providers and the shortcut

Create your [configuration directory](../README.md#configuration) and copy
`config/config.example.toml` into it as `config.toml` if you do not already
have one. Copy or create `hotwords.txt` and `master-hotwords.txt` beside it
to add personal vocabulary.

Select [AI providers](providers.md) and set any required API-key environment
variables in the terminal where you will run the app. The source installation
does not provision OpenASR, Ollama, or model files. Use services you have already
set up, or configure a remote provider.

```toml
[input]
hotkey = "auto"
```

| Setting | Linux/X11 | Windows | macOS |
| --- | --- | --- | --- |
| `auto` | Legacy `ptt_keycode` (Caps Lock by default) | Caps Lock | F8 |
| `caps_lock` | Legacy `ptt_keycode` | Caps Lock | Unsupported |
| `f1` through `f12` | Selected function key | Selected function key | Selected function key |

You can also set `CAP_TO_TALK_HOTKEY=f9`. Restart after changing settings.
Hold Shift before pressing the dictation key for raw transcription. Auto-repeat
does not restart recording or change the mode selected at the first press.

On Mac keyboards with media controls, use Fn/Globe + F8 or enable standard
function keys in Keyboard settings. See [Apple's function-key instructions](https://support.apple.com/en-us/102439).
Caps Lock is excluded on macOS because its toggle events do not provide the
press/release behavior this hold-to-talk implementation needs.

### Grant access and run

On macOS, enable the terminal or Python application used to launch Cap To Talk
in **System Settings > Privacy & Security > Accessibility** and **Input Monitoring**.
Restart that application after changing permissions. Microphone access is requested
when recording first opens; allow it for the same application. The diagnostic
command reports denied access without requesting new permissions. See
[Apple's input monitoring settings](https://support.apple.com/guide/mac-help/control-access-to-input-monitoring-on-mac-mchl4cedafb6/mac).

```bash
.venv/bin/cap-to-talk check
.venv/bin/cap-to-talk run
```

On Windows, allow desktop applications to use the microphone in Windows privacy
settings and run from an interactive desktop session:

```powershell
.\.venv\Scripts\cap-to-talk.exe check
.\.venv\Scripts\cap-to-talk.exe run
```

A provider check can contact the configured service but does not record audio or
send a dictation request. Add `--services-only` to check providers independently
of desktop and microphone access. Both commands accept `--config PATH`.

Keep the terminal open. Focus a text field, hold the configured key, speak, and
release the key. Release Shift too before insertion. Use Ctrl+C in the terminal
to stop and release the shortcut. Recording and processing status appear in
the terminal.

For an optional status overlay, run `cap-to-talk-status` from the same virtual
environment in a second terminal. It requires a Python installation with Tk.
The overlay reads the default configuration and environment; its status host
and port must match the dictation process if you use a custom config file.

### Insertion behavior

The native adapters retain the original window, wait for modifiers to be
released, and require a pause in user input before switching back from another
window. They check focus before each character and stop if the target closes,
focus changes, or a modifier is pressed. Unicode is sent as keyboard input.

When insertion temporarily switches windows, the previous window is restored
if focus is still on the dictation target. A window switch the user makes during
insertion is respected. Some text may already have been inserted when an error
occurs; insertion is not retried automatically.

Windows may refuse foreground activation or input into an application with
higher privileges. The adapter reports that failure. Switch to a normal target
application and dictate again. See Microsoft's [foreground activation](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow)
and [SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)
documentation.

## Adapter interface

`DesktopBackend` is defined in `src/cap_to_talk/desktop/base.py`. Recording,
vocabulary, and AI requests remain in the shared app and services.

| Operation | Responsibility |
| --- | --- |
| `check()` | Report desktop requirements without recording, changing settings, or grabbing keys. |
| `capture_target()` | Capture the window where dictation started; return an opaque string ID. |
| `release_target()` | Release references after insertion, an error, or an aborted recording. |
| `insert_text()` | Insert into the captured target; fail if it disappeared. |
| `notify()` | Report status through the adapter's available notification channels. |
| `run_hotkey_loop()` | Register the shortcut, deliver callbacks, and release native resources on exit. |

The shortcut loop calls `on_ready()` after successful registration.
`on_press(raw_mode)` receives the mode chosen at the first press;
`on_release()` ends the recording. Callbacks run serially. Native hook
callbacks only enqueue events, keeping microphone startup off the hook thread.
Text insertion and completion notifications run on the dictation worker thread.

The app closes microphone streams when the listener exits. Each adapter also
implements a thread-safe `stop()` request for the GUI. Adapters use
`DesktopUnavailableError` for actionable setup and native connection errors.

### Platform implementations

- `desktop/linux_x11.py` owns X11 shortcut registration, desktop checks,
  and notifications. It disables repeat for the selected key and restores its
  previous setting on exit. The `x11.py` helpers handle insertion. The Linux
  launcher owns Caps Lock remapping, keyboard-layout restoration, process
  locking, and the status-overlay process. Function-key mode leaves Caps Lock
  mapping alone.
- `desktop/windows.py` uses a low-level keyboard hook, foreground window
  handles with process IDs, and `SendInput` with UTF-16 input.
- `desktop/macos.py` uses Quartz event taps, Accessibility window references,
  and Unicode keyboard events through PyObjC.
- `desktop/native.py` shares event dispatch, target lifetime, focus checks,
  and console/overlay status for Windows and macOS. Native toast notifications
  are not implemented by these adapters. The desktop GUI supplies a settings
  window and tray/menu-bar controller.

Native libraries load only when the selected adapter needs them.
`cap-to-talk check --services-only` does not load a desktop SDK.

## Validation and release work

Automated tests simulate keyboard events, focus changes, permission failures,
Unicode insertion, and cleanup after errors. CI is configured to run shared
tests and native SDK import/binding smoke tests on macOS and Windows with
Python 3.12. Linux also runs the shell installer/launcher tests and a broader
Python version matrix.

Before promoting either experimental port, test on its real target OS:

1. Grant and deny required permissions; confirm startup gives an actionable result.
2. Hold/release the default key and a configured function key, including repeat
   and Shift raw mode. Confirm stopping the app restores normal key behavior.
3. Record into a plain text editor and a browser field using the configured
   provider. Check punctuation, accents, emoji, and line breaks.
4. Switch windows while processing, close the original window, and interrupt
   insertion with another window switch. Confirm text reaches the intended window.
5. Stop during recording/processing and retry after microphone or provider failure.

Passing simulated tests does not establish native desktop compatibility.
The [desktop UI and packaging workflow](releasing.md) are implemented. A public
release still needs configured signing accounts and clean-machine installation
tests. No standalone Mac/Windows download is published by these source changes.
