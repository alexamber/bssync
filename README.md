# bssync

Two-way sync between local **markdown files** and a [BookStack](https://www.bookstackapp.com/) wiki, plus an MCP server for Claude.

bssync only syncs markdown (`.md`). Pages edited in BookStack's WYSIWYG editor store HTML, not markdown — bssync skips those on pull and won't touch them.

Git is the source of truth; BookStack is the presentation layer. The `publish:` list in your config picks which markdown files sync where. Conflicts are detected via a `content_hash` tag stored on each page — no local state file.

## Who it's for

- **Docs-as-code teams** — a curated subset of your git-tracked markdown mirrored to BookStack for non-engineer readers.
- **Claude Code authoring** — draft `.md` in the terminal with Claude, sync selected files with `bssync push`. The MCP server gives Claude wiki search and guarded live writes.
- **Non-engineer contributions** — contributors edit in BookStack's markdown editor; engineers `bssync pull` into git for review.
- **CI-driven publishing** — `bssync push --force` on merge to main.

**Not for:**
- Full BookStack admin via LLM (users, roles, permissions, recycle bin) — use [pnocera/bookstack-mcp-server](https://github.com/pnocera/bookstack-mcp-server).
- BookStack-first workflows where the wiki is the source of truth.
- Non-BookStack wikis (Confluence, Notion, etc.) — fork for those.

---

## Install

**Homebrew** (macOS arm64, Linux x86_64):

```bash
brew tap alexamber/bssync && brew install bssync
```

**Binary** — download the `.tar.gz` for your platform from [Releases](https://github.com/alexamber/bssync/releases), extract, place `bssync/bssync` on your PATH.

**Python**:

```bash
pip install bssync                    # CLI only
pip install 'bssync[mcp]'             # + MCP server
```

---

## Quick start

```bash
bssync init                           # interactive config; tests connection
bssync pull --new --book Docs         # find untracked pages, print YAML to paste into config
bssync pull                           # fetch tracked content locally
bssync push                           # after local edits
```

Default config path: `./bookstack.yaml` (override with `-c PATH` or `$BSSYNC_CONFIG`).

---

## Commands

| Command | Purpose |
|---------|---------|
| `bssync init` | Interactive config setup |
| `bssync push [--only X] [--dry-run] [--force] [--diff] [--refresh-uploads]` | Local → BookStack |
| `bssync pull [--only X]` | BookStack → local |
| `bssync pull --new [--book X] [--chapter Y]` | List untracked pages, print YAML snippets |
| `bssync ls [--book X] [--chapter Y] [--missing]` | List pages, mark tracked |
| `bssync verify` | Test API connection |
| `bssync completions {bash,zsh,fish}` | Shell completion script |
| `bssync mcp install` | Register MCP server with Claude Code / Desktop |

All commands accept `-c PATH` and `--verbose`.

---

## Config

`bookstack.yaml`:

```yaml
bookstack:
  url: https://docs.example.com
  token_id: ""       # or env BOOKSTACK_TOKEN_ID
  token_secret: ""   # or env BOOKSTACK_TOKEN_SECRET

publish:
  - file: docs/getting-started.md   # must be .md; paths relative to this config
    book: Documentation             # created if missing
    chapter: Guides                 # optional, created if missing
    title: Getting Started          # optional; default: first H1 in the file
    strip_title: true               # optional; remove first H1 from pushed body (default true)
    attachments:                    # optional; uploaded as sidebar downloads
      - assets/diagram.svg
```

Env vars `BOOKSTACK_URL`, `BOOKSTACK_TOKEN_ID`, `BOOKSTACK_TOKEN_SECRET` override the yaml. If all three are set, the yaml is optional (for MCP live-only usage).

---

## Conflicts

`push` compares the page's current remote hash to the `content_hash` tag set by the last sync. Mismatch → prompt:

```
⚠ CONFLICT: "Architecture Overview" modified on BookStack since last publish
  Remote diff vs last sync: +12 / -3 lines
  [o] overwrite remote   [s] skip   [d] show diff   [p] pull remote first   [q] quit
```

Non-interactive mode (CI, MCP): the entry is skipped. Use `--force` to override.

Sync state lives on BookStack as page tags (`content_hash`, `source_file`, `bssync.img_hash.*`, `bssync.att_hash.*`). No local state file — the tool works from any machine with just the config.

---

## Images and attachments

Local `![alt](path.png)` and `[text](file.ext)` references are auto-uploaded to BookStack on push; URLs are rewritten in the pushed content. Supported image formats: `png`, `jpg`, `jpeg`, `gif`, `webp`, `svg`, `bmp`. Files not inlined in the markdown go in the config's `attachments:` list.

Changed files are detected via SHA256 and replace the remote content in place — attachment IDs and download URLs stay stable, so external links don't break. Use `--refresh-uploads` to force re-upload.

---

## MCP server (Claude Desktop, Claude Code)

Reuses `bookstack.yaml`. Live tools (search, get, create/update untracked pages) run without a yaml if the three `BOOKSTACK_*` env vars are set.

### Setup

1. **BookStack token**: Profile → Edit Profile → API Tokens → Create Token. Copy both Token ID and Token Secret.
2. **Install one of:**
   - **DXT** (easiest for Claude Desktop): download `bssync-mcp-<platform>.dxt` from Releases, Claude Desktop → Settings → Extensions → Install from file.
   - **Binary**: PyInstaller onedir format — don't `cp` just the binary, sibling files are required:
     ```bash
     tar -xzf bssync-mcp-macos-arm64.tar.gz -C ~/.local/lib/
     ln -s ~/.local/lib/bssync-mcp/bssync-mcp ~/.local/bin/bssync-mcp
     ```
   - **Python**: `pip install 'bssync[mcp]'`.
3. **Register with Claude:**
   ```bash
   bssync mcp install                  # interactive; detects Claude Code + Desktop
   # non-interactive:
   bssync mcp install --non-interactive --target=code \
     --url=https://wiki.example.com --token-id=xxx --token-secret=yyy
   # --target: code | desktop | both | print
   ```

Manual Claude Desktop JSON (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "bssync": {
      "command": "/abs/path/to/bssync-mcp",
      "env": {
        "BOOKSTACK_URL": "https://wiki.example.com",
        "BOOKSTACK_TOKEN_ID": "xxx",
        "BOOKSTACK_TOKEN_SECRET": "yyy"
      }
    }
  }
}
```

Add `"BSSYNC_CONFIG": "/abs/path/bookstack.yaml"` to `env` for `push`/`pull` support.

### Tools

**Sync** (need a `publish:` list): `verify`, `push`, `pull`, `ls`, `discover`. Conflicts return `status: skipped`; retry with `force: true`.

**Live read**: `list_books`, `list_chapters`, `list_pages_in`, `search_pages(query)`, `get_page(page_id | book+title)`. Also `bookstack://page/{id}` and `bookstack://page/by-title/{book}/{title}` as `@`-mentionable resources in Claude Desktop.

**Live write**: `create_page`, `update_page`. **Both refuse pages tracked in the `publish:` list** — edit those locally and `push`. Optional `expected_hash` on `update_page` blocks stomping concurrent edits.

**Prompts** (Claude Desktop slash-picker): `summarize_page`, `find_docs`.

### Troubleshooting

- Claude Desktop says "server disconnected" or tools return `config_invalid` → check `~/Library/Logs/Claude/mcp*.log` (macOS) or `%APPDATA%\Claude\Logs\mcp*.log` (Windows); fix the env vars, restart the MCP client.
- "Can't find library" when running the binary → you moved just the binary out of its onedir bundle. Re-extract and symlink per above.

---

## Security

- `bookstack.yaml` is gitignored in bssync's `.gitignore`; add a matching pattern if you use a different filename.
- Never commit API tokens. Prefer env vars in CI.
- BookStack tokens inherit the user's permissions — use a dedicated service account scoped to what bssync needs.

---

## Roadmap

- PyPI publication.
- Homebrew formula for `bssync-mcp`.
- Windows binary + DXT.
- Optional live-write mode for tracked pages (with `content_hash` conflict detection), behind a config flag.

---

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). Design rationale: [DECISIONS.md](DECISIONS.md).

## License

MIT — [LICENSE](LICENSE).
