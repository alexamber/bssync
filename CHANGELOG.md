# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] - 2026-04-21

### Added
- **MCP resources** — `bookstack://page/{page_id}` and `bookstack://page/by-title/{book}/{title}`. Claude Desktop users can `@`-mention wiki pages to pull them into conversation context natively.
- **MCP prompts** — `summarize_page` and `find_docs` templates available in Claude Desktop's slash-picker.
- **Claude Desktop Extension (.dxt)** bundle — one-click install. Download `bssync-mcp-<platform>.dxt` from Releases, Desktop prompts for URL + tokens, done. No PATH setup or JSON editing required.
- **By-name lookups** on `get_page` and `update_page` — accept `(book, title)` as an alternative to `page_id`. Cuts "update the onboarding doc" from 4 tool calls to 1.
- **Progress notifications** on `push` and `pull` — per-entry status via the MCP Context, so long syncs report progress instead of hanging silently.

### Changed
- **`update_page` parameter rename:** the "set new title" arg renamed from `title` to `new_title`, freeing `title` to mean "page title to look up". Breaking change for anyone calling `update_page(page_id, markdown, title=...)` — pre-release API only, no shipped v0.3.0 consumers.
- **Deferred config loading:** when config is missing or BookStack is unreachable at startup, the MCP server now starts anyway and every tool returns a structured `{"status": "error", "reason": "config_invalid", "fix": "..."}` response. Previously the server exited with a stderr message, which Claude Desktop surfaced only as "server disconnected" with no actionable detail.

## [0.3.0] - 2026-04-21

### Added
- **MCP server** (`bssync-mcp`) — Model Context Protocol server for Claude Desktop, Claude Code, and any MCP-compatible client. Install via `pip install 'bssync[mcp]'` or download the standalone `bssync-mcp-*.tar.gz` from GitHub Releases (no Python required on the host). Exposes 12 tools: sync (`verify`, `push`, `pull`, `ls`, `discover`), read-only live access (`list_books`, `list_chapters`, `list_pages_in`, `search_pages`, `get_page`), and guarded live writes (`create_page`, `update_page`). Live writes refuse pages tracked in the config's `publish:` list — those must go through the local files + `push` flow — preserving bssync's "local markdown is the source of truth" invariant.
- **`BOOKSTACK_URL` env var** and config-less operation. When `BOOKSTACK_URL` + `BOOKSTACK_TOKEN_ID` + `BOOKSTACK_TOKEN_SECRET` are set, `bookstack.yaml` becomes optional — ideal for MCP server usage where all config comes from Claude Desktop / Claude Code's `env:` block. Push/pull need a `publish:` list and so still require a yaml file; live and read-only MCP tools work without one.
- **`bssync-mcp --version`** — version flag that short-circuits config loading, so install verification works without credentials.
- **Standalone `bssync-mcp` binary** in GitHub Releases (`bssync-mcp-macos-arm64.tar.gz`, `bssync-mcp-linux-x86_64.tar.gz`) built via PyInstaller `--onedir` alongside the existing `bssync` binary.
- `BookStackClient.search()` — public search API, consumed by the MCP `search_pages` tool.

### Fixed
- `push` now preserves user-added tags on BookStack pages (labels, categories, anything from the BookStack UI). Previously every push replaced the full tag set with only bssync-managed tags, silently wiping the rest.
- Image and attachment replacement (`update_image`, `update_attachment`) now works on BookStack instances that don't accept `PUT` with multipart — falls back to `POST` with `_method=PUT` override.
- Attachment and image content changes are now properly reconciled on push — content-hash drift no longer causes spurious "UNCHANGED" reports when binary content differs.

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
