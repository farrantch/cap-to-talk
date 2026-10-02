# Changelog

All notable changes to Cap To Talk are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Desktop settings and tray/menu-bar controls, microphone selection and local
  recording checks, provider setup, and explicit credential-store selection.
- API-key storage in the native OS credential store, scoped to each endpoint
  origin. Settings writes preserve comments and reject stale edits.
- PyInstaller bundles, Linux .deb and Windows installer recipes, Mac disk images,
  signing/notarization hooks, checksums, and a four-platform draft-release workflow.
- Experimental native Windows and macOS adapters with shortcut handling,
  permission diagnostics, window targeting, Unicode insertion, and shared lifecycle
  tests. Real desktop validation is still pending.
- Configurable `input.hotkey`: Caps Lock or F1–F12 on Windows/Linux; F1–F12 on
  macOS, where the default is F8. Shift selects raw transcription.
- Platform configuration directories and OS-specific dependencies. CI includes
  shared tests and native SDK smoke tests on macOS and Windows.
- Common desktop interface with a Linux/X11 adapter. Microphone streams and
  captured window references are released after errors and aborted recordings.
- Clear errors for unavailable desktop integrations and shortcut conflicts;
  X11 keyboard resources are released on startup and callback failures.
- Optional single-model dictation: one audio request returns cleaned text, with
  verbatim instructions for Shift + the dictation key. Supports OpenAI audio models and
  compatible endpoints, with separate configuration and active-provider checks.
- Independent transcription and cleanup provider configuration, including OpenAI,
  compatible endpoints, Anthropic cleanup, and an option to disable cleanup.
- Per-provider models, endpoints, timeouts, vocabulary controls, and API-key
  environment variables while preserving OpenASR/Ollama defaults and legacy settings.
- Provider-aware diagnostics and startup, with optional cleanup failures reported
  as warnings, and `--skip-local-services` for installations using existing services.

### Changed

- Prepare WAV uploads in memory so quitting during a request leaves no temporary
  recording file. Stopping dictation prevents late provider results from being inserted.
- Bumped the development version to 0.3.0b1 for the desktop beta.
- Restore the Linux shortcut's previous key-repeat setting when the listener exits.
- Restored the project name, package, commands, paths, and brand assets to
  Cap To Talk while preserving automatic migration from Caps Talk installations.
- Made on-demand installation the default and added an explicit `--autostart`
  installer flag for starting Cap To Talk at desktop login.
- Expanded the example hotword and master glossary files with the complete
  technical vocabulary set.

## [0.2.0] - 2026-09-26

### Changed

- Renamed the project to Caps Talk, including the repository, package,
  commands, configuration paths, services, and brand assets.
- Added automatic configuration migration plus compatibility aliases for the
  previous command and environment-variable names.

## [0.1.0] - 2026-09-26

### Added

- Caps Lock push-to-talk recording on Linux/X11.
- Local transcription through OpenASR and optional cleanup through Ollama.
- Raw transcription mode with Shift + Caps Lock.
- Personal recognition hints and context-aware spelling glossary.
- Guided installer, desktop autostart, health checker, and safe uninstaller.
- TOML and environment-variable configuration.
- Privacy-conscious logging and immediate temporary-audio cleanup.
- Automated tests, linting, dependency auditing, and CodeQL analysis.

[Unreleased]: https://github.com/farrantch/cap-to-talk/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/farrantch/cap-to-talk/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/farrantch/cap-to-talk/releases/tag/v0.1.0
