# Backlog

Ideas, known issues, and planned features. Not prioritized.

## Known issues / known limitations

- **BookStack WYSIWYG editor stores HTML, not markdown.** Pages edited only in the BookStack editor may return empty `markdown` from the API, causing `pull` to skip them with a warning. BookStack stores markdown only for pages created or edited via the markdown editor.
- **Slight chance of false-positive conflicts** if BookStack changes its markdown normalization rules in a way our `normalize_markdown()` doesn't cover. Mitigation: `--force`, plus post-push hash reconciliation.
- **No batched API calls** — pushes are sequential. For users with hundreds of tracked pages, this is slow. Mitigation planned: concurrent push via `asyncio` or a thread pool.

## Planned features

### High priority
- [ ] **Test coverage** — fill out `test_sync.py` with mocked client flows (push create/update, pull overwrite, conflict pull-first)
- [ ] **PyPI publication** — pick a final package name (`bssync` if available, else `bookstack-sync`), register, configure `release.yml` to publish
- [ ] **Better error messages** — when API returns 403/404/validation errors, translate to human-readable guidance
- [ ] **`bssync status`** — like `git status`: show what would push / pull without actually doing it
- [ ] **Interactive `pull --new`** — instead of printing YAML snippets to copy-paste, prompt per untracked page and auto-append to the config. Options per page: `[y] add & pull` / `[e] edit path` / `[s] skip` / `[a] accept all remaining` / `[q] quit`. Must use append-only writes to preserve comments and formatting in the user's config (no ruamel.yaml roundtrip).
- [ ] **`bssync add <file>`** — single-file interactive add: detect H1 as title, prompt for book/chapter, append to config, optionally push immediately. Solves "I just wrote a local doc, track it now" without manual YAML editing.

### Medium priority
- [ ] **`bssync scan <dir> --book X`** — bulk-add from a directory: walk for `.md` files, extract H1s as titles, prompt to add all or pick individually. Needs clear policy for book/chapter inference (probably require `--book`, use subdirectories as chapter hint). Design tradeoff: directory-to-chapter mapping conventions vary per repo — may be better to keep it manual via repeated `bssync add`.
- [ ] **`bssync watch`** — auto-push on local file save (useful for live preview)
- [ ] **Shelves support** — BookStack has a shelf abstraction above books; config could target shelves
- [ ] **Per-entry `direction: push|pull|both`** — some entries are push-only (authored locally), some pull-only (edited on BookStack by non-devs), some bidirectional
- [ ] **Bulk rename / move support** — moving a page in the config (different book/chapter) currently does nothing; need to explicitly move the BookStack page too
- [ ] **Config schema validation** — catch typos in field names early

### Lower priority
- [ ] **JSON output mode** (`--json`) for scripting — machine-parseable status reports
- [ ] **Concurrent push/pull** via thread pool
- [ ] **Markdown link rewriting** — when pulling, rewrite internal BookStack page links to local relative paths and vice versa on push
- [ ] **Pre-commit hook helper** — `bssync push --check` for CI to verify no un-pushed changes
- [ ] **Dry-run pull** — preview what would be pulled without writing to disk

## Non-goals

Explicitly not planning to build:

- **Full two-way merge** — markdown auto-merge corrupts tables and code blocks. Manual conflict resolution is correct.
- **Local state file** — state lives on BookStack. Breaks portability.
- **GUI / web UI / daemon** — CLI tool, stays a CLI tool.
- **Support for other wiki systems** (Confluence, MediaWiki, Notion, etc.) — bssync is BookStack-specific. Fork for other systems.
- **Auto-commit to git** — user's concern, not bssync's.
- **Built-in scheduler** — run it from cron or GitHub Actions if you want recurring syncs.

## Ideas worth prototyping

- **Attachment gc** — detect BookStack attachments that are no longer referenced in any local or remote page content and offer to delete
- **Image gallery migration** — currently images are per-page; BookStack's gallery is shared across pages. Add support for uploading to a shared gallery and de-duplicating.
- **`bssync diff <entry>`** — show unified diff between local and remote for a single entry on demand, without prompt loop
