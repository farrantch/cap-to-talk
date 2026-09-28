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

Cap To Talk targets Python 3.12+ on Linux/X11.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest
```

Check shell changes too:

```bash
bash -n install.sh uninstall.sh scripts/*.sh
shellcheck install.sh uninstall.sh scripts/*.sh
```

Keep changes small, add tests for changed behavior, and update the README or
changelog when users will notice the difference. By participating, you agree
to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
