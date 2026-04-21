# bssync

Two-way sync between local markdown files and a [BookStack](https://www.bookstackapp.com/) wiki.

Edit docs in your editor, push to BookStack. Edit in BookStack's WYSIWYG, pull back to your editor. Safe against silent overwrites, auto-uploads images and file attachments, discovers untracked pages.

---

## Install

**Homebrew** (macOS arm64, Linux x86_64):

```bash
brew tap alexamber/bssync
brew install bssync
```

**Direct binary** from [GitHub Releases](https://github.com/alexamber/bssync/releases) — download the `.tar.gz` for your platform, extract, and place `bssync/bssync` on your PATH.

**With Python:**

```bash
pip install bssync
# with the MCP server for Claude Desktop / terminal:
pip install 'bssync[mcp]'
# or direct from GitHub (pre-PyPI):
pip install git+https://github.com/alexamber/bssync.git
```

If `pip install` errors with `externally-managed-environment` (common on Homebrew
Python), either use a venv or install via `pipx install bssync` instead.

After install, `bssync` is on your PATH.

---

## Quick start

```bash
# Set up config interactively — one command, prompts for URL + token, tests connection
bssync init

# Explore what's on your BookStack
bssync ls

# Find pages not yet tracked in config, copy-paste the YAML snippets into your config
bssync pull --new --book Documentation

# Pull tracked content to local
bssync pull

# Edit markdown locally, then push
bssync push
```

---

## Commands

| Command | Description |
|---------|-------------|
| `bssync init` | Interactive config setup |
| `bssync push` | Upload local → BookStack |
| `bssync pull` | Download BookStack → local |
| `bssync pull --new` | List pages not in config, print YAML snippets to add them |
| `bssync ls` | List all pages on BookStack, mark tracked vs untracked |
| `bssync ls --missing` | Only show pages not tracked in config |
| `bssync verify` | Test API connection |
| `bssync completions SHELL` | Print shell completion script (bash/zsh/fish) |

All commands accept `-c <path>` to use a non-default config file and `--verbose` to log API requests. The `-c` default is `$BSSYNC_CONFIG` if set, otherwise `bookstack.yaml` in the current directory.

### Push

```bash
bssync push                        # all config entries
bssync push --only guide           # filter by file or title substring
bssync push --dry-run              # preview without API writes
bssync push --diff                 # show content diff per updated page
bssync push --force                # skip conflict check (see below)
bssync push --refresh-uploads      # force re-upload of all images and attachments
```

### Pull

```bash
bssync pull                        # all config entries
bssync pull --only guide           # filter

# Discovery mode — find pages on BookStack not yet in your config
bssync pull --new --book Engineering
bssync pull --new --chapter "Getting Started"
```

### ls

```bash
bssync ls                          # full BookStack tree
bssync ls --book Engineering       # one book
bssync ls --chapter "Setup"        # one chapter
bssync ls --missing                # only untracked pages
```

### Shell completions

```bash
# zsh (with oh-my-zsh, save to a completions dir on your fpath)
bssync completions zsh > ~/.zsh/completions/_bssync

# bash (source in your .bashrc)
bssync completions bash > ~/.bash_completion.d/bssync
# or load on demand:
source <(bssync completions bash)

# fish
bssync completions fish > ~/.config/fish/completions/bssync.fish
```

---

## Config format

`bookstack.yaml` (location configurable with `-c`):

```yaml
bookstack:
  url: https://docs.example.com
  token_id: ""       # or env var: BOOKSTACK_TOKEN_ID
  token_secret: ""   # or env var: BOOKSTACK_TOKEN_SECRET

publish:
  - file: docs/getting-started.md            # relative to config file
    book: Documentation                       # created if missing
    chapter: Guides                           # optional, created if missing
    title: Getting Started                    # optional, defaults to first H1
    strip_title: true                         # optional (default true)
    attachments:                              # optional, sidebar downloads
      - assets/diagram.svg
```

Credentials come from the config or from environment variables (`BOOKSTACK_TOKEN_ID`, `BOOKSTACK_TOKEN_SECRET`). The env vars override the config, which is useful for CI.

---

## Conflict guard

When you push, bssync checks whether the BookStack page has been modified since your last sync. If yes, you get a prompt:

```
⚠ CONFLICT: "Architecture Overview" modified on BookStack since last publish
  Remote diff vs last sync: +12 / -3 lines
  [o] overwrite remote   [s] skip   [d] show diff   [p] pull remote first   [q] quit
```

- `o` — overwrite BookStack with your local version
- `s` — skip this entry, continue with others
- `d` — show unified diff between your local and the remote
- `p` — pull remote to local (abandons your local unpushed changes)
- `q` — abort the whole run

In **non-interactive** mode (CI/cron), conflicts cause the entry to be skipped with a non-zero exit. Use `--force` to override.

**How it works:** A `content_hash` tag is stored on each BookStack page. Before pushing, bssync compares the page's current content hash to the stored tag. Mismatch means someone edited externally. No local state file — all sync metadata lives on BookStack as tags.

---

## Images and attachments

**Images** — local image references in markdown are auto-uploaded to BookStack's gallery:

```markdown
![Architecture](assets/architecture.png)
```

On push: detects the reference, uploads, rewrites URL to BookStack's. Supported: `png`, `jpg`, `jpeg`, `gif`, `webp`, `svg`, `bmp`.

**Attachments** — two paths:

1. **Inline file links** — `[schema.sql](path/to/schema.sql)` in markdown auto-uploads and rewrites to the BookStack download URL.
2. **Config list** — explicit `attachments:` list for files not referenced inline.

Both de-duplicate by filename. When a file with the same name already exists on the page, bssync compares a SHA256 of the local file against a hash tag stored on the page (`bssync.att_hash.*` / `bssync.img_hash.*`). On content change it replaces the remote file in place via `PUT` — attachment IDs and download URLs are preserved, so external links don't break. Use `--refresh-uploads` to force re-upload regardless.

---

## Configuration lifecycle

Typical workflow:

1. **Set up** — `bssync init` (prompts + creates config + tests connection)
2. **Discover** — `bssync ls --missing` to see untracked pages
3. **Track new pages** — `bssync pull --new --book X` prints YAML snippets to paste into `publish:`
4. **Day-to-day** — edit locally → `bssync push`; someone edits on BookStack → `bssync pull`

---

## MCP server (Claude Desktop, Claude Code & terminal)

bssync ships a Model Context Protocol server so Claude (Desktop, Claude Code, or any MCP client) can sync, browse, and author BookStack pages directly. It reuses the same `bookstack.yaml` — no second config.

**Install options:**

```bash
# Standalone binary (no Python needed) — download the bssync-mcp-*.tar.gz
# for your platform from https://github.com/alexamber/bssync/releases,
# extract, and place `bssync-mcp/bssync-mcp` on your PATH.

# Or via pip (bundles the mcp SDK):
pip install 'bssync[mcp]'
# isolated:
pipx install 'bssync[mcp]'
```

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "bssync": {
      "command": "bssync-mcp",
      "env": {
        "BSSYNC_CONFIG": "/absolute/path/to/bookstack.yaml",
        "BOOKSTACK_TOKEN_ID": "xxx",
        "BOOKSTACK_TOKEN_SECRET": "yyy"
      }
    }
  }
}
```

**Claude Code** — one command:

```bash
claude mcp add bssync bssync-mcp \
  -e BSSYNC_CONFIG=/absolute/path/to/bookstack.yaml \
  -e BOOKSTACK_TOKEN_ID=xxx \
  -e BOOKSTACK_TOKEN_SECRET=yyy
```

Then `claude mcp list` to verify, and it's available in every Claude Code session.

Put secrets in the `env:` block (or `-e` flags) rather than the yaml file — the env vars override the config, so you can keep `token_id`/`token_secret` blank in a shared/checked-in config. `BSSYNC_CONFIG` **must be absolute** because Claude Desktop/Code launch the server from an unspecified working directory.

**No yaml at all (pure env config):** if you set `BOOKSTACK_URL`, `BOOKSTACK_TOKEN_ID`, and `BOOKSTACK_TOKEN_SECRET`, the server runs without `bookstack.yaml`. You lose `push`/`pull` (those need a `publish:` list), but every other tool works — ideal for MCP-only usage.

`publish:` is optional in the config when you only want live/read-only usage — leave it blank and you still get `ls`, `search_pages`, `get_page`, and the live write tools.

**Terminal (MCP Inspector)** — for debugging or trying out the server:

```bash
BSSYNC_CONFIG=/abs/path/bookstack.yaml npx -y @modelcontextprotocol/inspector bssync-mcp
```

### Tools

**Sync** — mirrors the CLI, runs against the config's `publish:` list:

| Tool | Notes |
|------|-------|
| `verify` | API reachability check |
| `push` | Conflicts return `status: skipped` with a reason; retry with `force: true` (no TTY prompts in MCP mode) |
| `pull` | Non-interactive: entries that differ from remote are reported, not overwritten |
| `ls` | Full tree with `tracked: true/false` per page |
| `discover` | Returns untracked pages + ready-to-paste YAML snippets |

**Live (read-only)** — work with BookStack directly, no local files needed:

| Tool | Notes |
|------|-------|
| `list_books` / `list_chapters` / `list_pages_in` | Navigation |
| `search_pages(query)` | BookStack full-text search |
| `get_page(page_id)` | Returns markdown + `content_hash` for optimistic concurrency |

**Live (write)** — guarded to prevent desyncing tracked content:

| Tool | Guardrail |
|------|-----------|
| `create_page(book, title, markdown, chapter?)` | Refuses if `(book, title)` matches a config entry |
| `update_page(page_id, markdown, title?, expected_hash?)` | Refuses if the page is tracked; optional `expected_hash` from `get_page` blocks stomping concurrent edits |

The guardrail exists because local markdown is the source of truth for tracked pages — letting Claude write to them live would silently invalidate the sync state. For tracked pages, edit the local file and call `push` instead.

### Roadmap

- Homebrew formula for the `bssync-mcp` binary (currently CLI-only).
- Claude Desktop `.dxt` extension bundle for one-click install.
- MCP `resources` and `prompts` primitives — expose `bookstack://page/{id}` as a resource and ship a few prompt templates.
- Optional full live-write mode for tracked pages (with conflict detection via the `content_hash` tag), behind a config flag. Today, writes to tracked pages are refused.

---

## Security

- `bookstack.yaml` is gitignored by default in bssync's own `.gitignore` — if you use a different config filename, make sure it matches an ignored pattern
- Never commit API tokens. Prefer env vars in CI.
- BookStack tokens inherit the user's permissions. Use a dedicated service account with minimum required scope.

---

## Design

- **Single-file scripts are easy. Multi-file packages are maintainable.** bssync is split into focused modules (~100-300 lines each): `client`, `sync`, `content`, `conflict`, `discovery`, `config`, `cli`.
- **State lives on the remote.** No `.bssync/` directory, no local database. All sync metadata is stored as BookStack page tags. The tool is stateless from the local filesystem's perspective, which means it works cleanly across machines and with git.
- **Normalization for stable hashing.** Push/pull round-trips can subtly mutate markdown (whitespace, line endings). A consistent normalization before hashing avoids false-positive conflicts.
- **Lazy imports in the CLI.** `bssync init` and `bssync --help` don't load the API client — they start fast.

See [`DECISIONS.md`](DECISIONS.md) for the key design decisions and their rationales.

---

## Contributing

PRs welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for setup, testing, and code style.

## License

MIT — see [`LICENSE`](LICENSE).
