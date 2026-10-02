# Desktop app preview

The settings app is available in source and local builds. Public signed installers
have not been released yet. Maintainers can generate test downloads with the
[desktop build workflow](releasing.md).

## Run from source

Install Python 3.12 or newer, then run from the repository:

```bash
python -m pip install -e ".[desktop]"
cap-to-talk-desktop
```

Use the Python executable from your virtual environment. On Windows its commands
are under `.venv\Scripts`; on macOS/Linux they are under `.venv/bin`.
The existing `cap-to-talk` command and Linux shell launcher remain available.
Stop an existing command-line instance before starting dictation in the GUI.

## Set up dictation

1. Open **General** and select your microphone and dictation key.
2. Open **AI providers**. Choose separate transcription and optional cleanup,
   or one audio-capable model. Enter a model name available to your provider account.
3. For a remote provider, choose **Saved on this computer** and paste your API key.
   Use **No API key** for an unauthenticated local service. Local services and model
   downloads must be set up separately.
4. Click **Save settings**, then **Check setup**. Checks can contact the selected
   provider's health endpoint; they do not send a recording.
5. Click **Test microphone (3 s)** and speak. This checks recording locally and
   reports its peak level. It does not save or send the test audio.
6. Click **Start dictation**. Focus a text field, hold the dictation key, speak,
   and release it. Hold Shift before the key to select raw transcription.

For single-model mode, choose a model that accepts audio and returns text.
See [provider examples](providers.md) for endpoint and model requirements.

### Permissions

- **macOS:** allow Cap To Talk in Accessibility and Input Monitoring under
  System Settings > Privacy & Security. Allow Microphone access when requested.
  For source launches, the responsible application may be your terminal or Python.
  Restart after changing permissions. The default key is F8; some keyboards
  require Fn + F8.
- **Windows:** allow desktop applications to use the microphone. The default
  key is Caps Lock. Input into applications running with higher privileges may fail.
- **Linux:** use an X11 session. The default key is Caps Lock. The GUI prepares
  and restores its mapping; a function key leaves the Caps Lock mapping alone.

Settings changes are disabled while dictation or a check is running. Click
**Stop** before changing providers, shortcuts, or microphones.

## Tray and closing behavior

On desktops with a system tray or menu bar, closing Settings leaves the controller
available there. Use the icon to reopen Settings, start/stop dictation, or quit.
On desktops without a tray, closing the window stops dictation and exits.

Stopping releases the shortcut and prevents a pending provider result from being
inserted afterward. A request already sent to a provider may still finish and
incur usage there. **Downloads and updates** opens the GitHub releases page;
the app does not install updates automatically.

## Credentials and settings

Keys saved through the app use macOS Keychain, Windows Credential Manager, or
Linux Secret Service. The Linux credential store must be running and unlocked.
If the native store is unavailable, saving a key reports an error. There is no
plaintext-file fallback.

Each saved credential is tied to its configured name and the endpoint's scheme,
host, and port. A different endpoint origin needs its own saved key.
**Environment variable** mode continues to support existing command-line setups;
the selected credential mode is explicit.

API keys are not written into TOML. Settings writes preserve comments and advanced
options, and refuse to overwrite a file edited since the window opened.
Existing environment overrides still apply. The default config directories are
listed in the [README](../README.md#configuration).

To remove a stored key, select its provider and endpoint, check **Remove the saved
key when saving settings**, and save. Uninstalling the application leaves personal
settings and credentials in place.

## Testing status

Headless tests cover settings changes, saved-key isolation, checks, shutdown, and
packaged startup. macOS/Windows adapter and installer behavior still requires
real desktop testing. The first release targets macOS 15+, Windows 11 x64,
and Ubuntu 24.04+ x64 with X11.
