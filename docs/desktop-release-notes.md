## Desktop beta

Cap To Talk now includes a settings window and tray/menu-bar controls,
configurable microphones and shortcuts, provider selection, API-key storage in
the operating system's credential store, and a bottom-right status popup while
you dictate.

Choose separate transcription/cleanup providers or one audio-capable model.
Connect your own provider account or an existing local service.

### Install

On macOS 15+, run this in Terminal. It asks whether to use local models
(OpenASR and Ollama, in three sizes), Claude cleanup, or OpenAI, and sets up
only what you choose, without asking for an administrator password:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/farrantch/cap-to-talk/main/install.sh)"
```

Open Cap To Talk, click **Start dictation**, and enable it under Accessibility and
Input Monitoring when asked. Quit and reopen it, start dictation, and hold Caps Lock.

Other downloads:

- macOS 15+ disk images: Apple Silicon (arm64) or Intel (x86_64).
- Windows 11 x64: run the setup executable.
- Ubuntu 24.04+ x64: install the .deb and use an X11 session.

These installers bundle Python and application dependencies. Except through the
macOS installer command above, local AI services and models require separate
installation.

These beta builds are **not signed** by Apple or Microsoft. The macOS installer
command clears the download quarantine flag; a disk image opened from a browser
needs **Open Anyway** in System Settings > Privacy & Security. Windows SmartScreen
asks for confirmation. Check downloads against `SHA256SUMS.txt`.

Read the [desktop guide](https://github.com/farrantch/cap-to-talk/blob/main/docs/desktop-app.md)
for permissions, provider setup, and troubleshooting.

The desktop integrations are experimental. Please report microphone, shortcut,
or text-insertion problems through the project’s issue tracker, including your
operating system and the application you were dictating into.
