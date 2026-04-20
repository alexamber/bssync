# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-04-20

### Fixed
- `push` now reconciles chapter moves for existing pages. When the yaml declares a different `chapter:` than where the page currently lives on BookStack, the page is moved into the declared chapter and a `MOVED` line is printed. Previously the content would update silently without a move. Scope: within-book moves only; cross-book moves tracked in [#2](https://github.com/alexamber/bssync/issues/2). ([#1](https://github.com/alexamber/bssync/issues/1))

## [0.2.0] - 2026-04-17

### Added
- Homebrew tap at `alexamber/bssync`. Install with `brew tap alexamber/bssync && brew install bssync`.
- `bssync completions bash|zsh|fish` prints a shell completion script to stdout.
- `BSSYNC_CONFIG` environment variable as the default `--config` path.
- Colorized output for status labels (UPDATED/CREATED/UNCHANGED/SKIP/CONFLICT/ERROR) and unified diffs. Auto-disabled when stdout is not a TTY, when `NO_COLOR` is set, or `TERM=dumb`.

### Changed
- Invoking `bssync` with no subcommand now prints `--help` instead of silently running `push`. Safer default; avoids accidental writes to remote.
- Release binaries are now built with PyInstaller `--onedir` and packaged as `.tar.gz` archives. Warm-run startup drops from ~7s to ~130ms.
- Missing-config error now suggests `bssync init` and documents `--config` and `BSSYNC_CONFIG` as alternatives.

## [0.1.0] - 2026-04-15

### Added
- Initial release. Two-way sync between local markdown files and BookStack.
- `push` command — upload local → BookStack, with conflict guard against silent overwrites.
- `pull` command — download BookStack → local, with interactive diff/overwrite prompts.
- `pull --new` — discover pages on BookStack not yet in config, suggests YAML entries.
- `ls` command — explore BookStack tree, flag tracked vs untracked pages.
- `verify` command — test API connection.
- Auto-upload of images referenced in markdown (`![](path)`) to BookStack's image gallery.
- Auto-upload of file links (`[text](file.ext)`) as BookStack attachments.
- Explicit `attachments:` config list for files not referenced inline.
- Normalized markdown hashing for stable conflict detection across push/pull round-trips.
