# Contributing to bssync

Thanks for your interest. This doc covers development setup, testing, and release mechanics.

## Development setup

Requires Python 3.9+.

```bash
git clone https://github.com/alexamber/bssync.git
cd bssync
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
```

`-e` installs in editable mode — changes to the source are picked up without reinstall. `[dev]` adds pytest and friends.

Verify the install:

```bash
bssync --version
bssync --help
```

## Running tests

```bash
pytest
pytest --cov=bssync --cov-report=term-missing
```

Tests live in `tests/`. All pure functions in `content.py` should have coverage. Sync and discovery tests mock the `BookStackClient` — there are no tests against a live BookStack instance.

## Running against a real BookStack

For manual testing:

1. `bssync init` — interactive setup against your test BookStack instance
2. Add an entry to `publish:` pointing to a local markdown file
3. `bssync push --dry-run` and `bssync push`

The `bookstack.yaml` you create is gitignored.

## Code organization

See [`CLAUDE.md`](CLAUDE.md) for full module responsibilities. In short:

- **Network** → `client.py` only
- **Pure markdown processing** → `content.py`
- **Sync orchestration** → `sync.py`
- **CLI plumbing** → `cli.py` (no business logic)

When adding features, put the logic in the right module. The CLI should stay thin.

## Style

- Python 3.9+ syntax (`list[X]`, `dict[K, V]`, `X | Y` type hints)
- No click, no typer — stick with stdlib `argparse`
- Minimal dependencies: only `pyyaml` and `requests`. Adding a new runtime dep needs a strong justification.
- ASCII section dividers (`# ─── Section ───`) for long files
- Prefer small pure functions over stateful methods

## Commits and PRs

- Keep commits focused and atomic
- Write clear commit messages explaining the "why", not just the "what"
- Add tests for new functionality
- Update `CHANGELOG.md` under "Unreleased" for user-visible changes
- Update `README.md` if you change user-facing behavior

## Releasing (maintainers)

1. Move "Unreleased" entries in `CHANGELOG.md` under a new version heading with the date
2. Update `__version__` in `src/bssync/__init__.py` and `version` in `pyproject.toml`
3. Commit: `git commit -am "release v0.x.y"`
4. Tag: `git tag v0.x.y`
5. Push: `git push && git push --tags`
6. GitHub Actions `release.yml` automatically:
   - Builds PyInstaller binaries for macOS (arm64 + x86_64) and Linux (x86_64)
   - Publishes them to the GitHub Release
7. (Optional) Publish to PyPI: `python -m build && twine upload dist/*`

## Reporting bugs

Open a GitHub issue with:
- `bssync --version`
- Python version
- Your OS
- Minimal steps to reproduce
- Expected vs actual behavior
- Any API errors (remove sensitive tokens first)
