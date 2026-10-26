# Contributing

Thanks for helping improve Cap To Talk. Bug reports, documentation fixes, and
focused pull requests are welcome.

## Before opening an issue

- Run `cap-to-talk check` and include its non-sensitive output.
- Search existing issues for the same behavior.
- Never post dictated text, audio, private glossary entries, or credentials.
- Use the private security-reporting link in [SECURITY.md](SECURITY.md) for
  vulnerabilities.

## Development setup

Cap To Talk uses Python 3.12+. Linux/X11 has an installer; macOS and Windows
have experimental source adapters. See [platform setup](docs/desktop.md#macos-and-windows-setup)
for native dependencies and permissions.

On Linux or macOS:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev,desktop]'
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest
```

On Windows, create the environment with `py -3.12 -m venv .venv` and use
executables under `.venv\Scripts\`. Install the same `.[dev,desktop]` extras. Run
the portable tests with:

```powershell
.\.venv\Scripts\python.exe -m pytest --ignore=tests/test_install.py --ignore=tests/test_install_user.py --ignore=tests/test_start.py
```

Use that test selection on macOS too; the omitted tests exercise Linux shell
installers and startup. Native SDK smoke tests run only on their target OS.

Check shell changes on Linux too:

```bash
bash -n install.sh uninstall.sh scripts/*.sh
shellcheck install.sh uninstall.sh scripts/*.sh
```

## Desktop builds

GUI tests use Qt's offscreen platform and mock microphones, credential stores,
and provider requests. Set `QT_QPA_PLATFORM=offscreen` on a headless machine.
To test the packaged app and create installers, follow [releasing.md](docs/releasing.md).

## Desktop integrations

The app uses a desktop interface for shortcuts, window targeting, insertion,
notifications, and desktop checks. See [Desktop integrations](docs/desktop.md)
for the contract, platform implementations, and manual validation steps.
Shared tests use fake desktops. Native smoke tests load the OS APIs without
recording audio, requesting permissions, or installing keyboard hooks. Real
desktop tests are required before promoting an experimental adapter.

Keep changes small, add tests for changed behavior, and update the README or
changelog when users will notice the difference. By participating, you agree
to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
