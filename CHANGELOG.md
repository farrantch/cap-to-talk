# Changelog

All notable changes to Caps Talk are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- Made on-demand installation the default and added an explicit `--autostart`
  installer flag for starting Caps Talk at desktop login.
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
