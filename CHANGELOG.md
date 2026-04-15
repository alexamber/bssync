# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
