# CLAUDE.md — bssync

Instructions for AI assistants (Claude Code, Cursor, etc.) working in this repo.

## Project summary

`bssync` is a production-oriented CLI tool that two-way-syncs local markdown files with a BookStack wiki instance. Written in Python, distributed as a pip package and as pre-built binaries via GitHub Releases.

**Key design principles — do not violate without strong reason:**

1. **Stateless locally.** All sync metadata (content hashes) lives on BookStack as page tags. There must be no `.bssync/` directory or local database file.
2. **One normalization source of truth.** `bssync.content.normalize_markdown()` is where markdown-normalization rules live. Extend there — do not scatter normalization logic across modules.
3. **Idempotent operations.** Running `push` or `pull` twice in a row with no changes must produce `UNCHANGED` for every entry. Violating this breaks CI use cases.
4. **No silent overwrites.** `push` must refuse (or prompt, interactively) when the BookStack page has changed since last sync. `--force` is the only escape hatch.
5. **Secrets never committed.** `bookstack.yaml` and any config file containing tokens must stay gitignored. Environment variables (`BOOKSTACK_TOKEN_ID`, `BOOKSTACK_TOKEN_SECRET`) are the preferred source in CI.

## Repository structure

```
bssync/
├── pyproject.toml              ← package metadata, deps, CLI entry point
├── README.md                   ← user-facing docs
├── CLAUDE.md                   ← you are here
├── CONTRIBUTING.md             ← dev setup, test, lint, release
├── DECISIONS.md                ← architectural decisions (ADR-lite)
├── CHANGELOG.md                ← user-visible changes per release
├── LICENSE                     ← MIT
├── bookstack.yaml.example      ← config template
├── .gitignore                  ← credentials + build artifacts
├── docs/
│   └── BACKLOG.md              ← ideas, known issues, future work
├── src/bssync/
│   ├── __init__.py             ← version, public exports
│   ├── __main__.py             ← `python -m bssync` entry
│   ├── cli.py                  ← argparse + dispatch
│   ├── client.py               ← BookStackClient (all API access)
│   ├── config.py               ← YAML config loading
│   ├── content.py              ← markdown: read, H1, normalize, hash, images, links
│   ├── conflict.py             ← diff, prompts, sync tags
│   ├── sync.py                 ← publish_entry, pull_entry (orchestrators)
│   ├── discovery.py            ← ls, pull --new, is_tracked
│   └── init.py                 ← interactive config setup
├── tests/
│   ├── test_content.py
│   ├── test_discovery.py
│   └── test_sync.py
└── .github/workflows/
    ├── test.yml                ← CI: pytest on push/PR
    └── release.yml             ← build PyInstaller binaries on version tags
```

## Module responsibilities

- **`client.py`** — HTTP access to BookStack. All network calls live here. If you're adding a new endpoint, add a method to `BookStackClient`. No other module should use `requests`.
- **`content.py`** — pure functions only. No network, no side effects beyond reading the input file. Easy to unit-test.
- **`conflict.py`** — diff display, interactive prompts, and the `set_sync_tag` helper. Depends on `client` and `content`.
- **`sync.py`** — the orchestrators. `publish_entry` and `pull_entry` tie everything together. If adding a new sync mode (e.g., dry-merge), add a new top-level function here.
- **`discovery.py`** — read-only exploration. `ls`, `pull --new`, matching logic.
- **`cli.py`** — argparse + dispatch. No business logic. Lazy-imports subcommand handlers to keep `--help` fast.
- **`init.py`** — interactive wizard for generating a config. Called directly from `cli.py`; does not depend on a loaded config.
- **`config.py`** — load + validate YAML. Exits on validation error with a clear message.

## Common tasks

**Add a new BookStack API endpoint:**
1. Add method to `BookStackClient` in `client.py`
2. Add a unit test with a mocked requests library in `tests/`
3. Use it from the appropriate orchestrator in `sync.py` or `discovery.py`

**Add a new CLI command:**
1. Add a subparser in `build_parser()` in `cli.py`
2. Add a dispatch branch in `main()`
3. Write the handler in a new or existing module (keep business logic out of `cli.py`)
4. Document in README

**Change markdown normalization:**
1. Only edit `normalize_markdown()` in `content.py`
2. Add a test covering the new rule in `tests/test_content.py`
3. Note that changing normalization will cause one-time false-positive conflicts for pages hashed with the old rules — document in CHANGELOG under "Breaking changes" if necessary

**Bump version:**
1. Update `__version__` in `src/bssync/__init__.py`
2. Update `version` in `pyproject.toml` (keep in sync)
3. Add release notes to `CHANGELOG.md`
4. Tag: `git tag v0.x.y && git push origin v0.x.y`
5. GitHub Actions `release.yml` will auto-build binaries and publish the release

## Code style

- Python 3.9+ syntax. Use `list[X]`, `dict[K, V]`, `X | Y` type hints freely.
- Standard library `argparse` — no click, no typer (keep dependencies minimal).
- Only two runtime dependencies: `pyyaml`, `requests`. Do not add more without a strong justification in a PR.
- Prefer small, testable pure functions over methods on stateful objects.
- Use the ASCII section dividers (`# ─── Section ───`) to organize long files.

## Testing

- `pytest` runs all tests
- `pytest --cov=bssync` for coverage
- All pure functions in `content.py` should have tests
- Mock `BookStackClient` in tests for sync/discovery — do not hit real APIs in CI

## Things NOT to do

- Do not add a local state file (`.bssync/`, `.bssync_state.json`, etc.) — state lives on BookStack
- Do not add a web UI, GUI, or daemon mode — bssync is a CLI
- Do not add auto-commit-to-git functionality — that's the user's concern
- Do not add support for other wiki systems — this is a BookStack tool. Fork for other systems.
- Do not expand the dependency list without clear justification
- Do not reference any specific organization, company, or project in code or docs — bssync is a general-purpose tool
