# Architectural Decisions

Lightweight ADRs for decisions that shape bssync's design. Each entry explains the choice made, the alternatives considered, and why.

---

## 1. State lives on BookStack, not locally

**Decision:** Sync metadata (content hashes) is stored as tags on BookStack pages, not in a local `.bssync/` directory.

**Alternatives considered:**
- Local `.bssync/state.json` with per-page metadata
- Git notes
- No state — always compare byte-for-byte

**Why:** The tool should work the same from any machine with just a config file and API credentials — no extra files to sync. A local state file would create "works on my machine" issues where one user's cache goes out of date while another's doesn't. Storing `content_hash` as a tag on each page means the remote is authoritative about "what was last synced," and any client can reason about conflicts without prior state.

**Tradeoff:** Requires one extra API call per push to reconcile the stored hash when BookStack normalizes markdown differently from us. Acceptable.

---

## 2. Normalized hashing, not byte-for-byte

**Decision:** Hash a normalized form of markdown (line endings, trailing whitespace, trailing empty lines) rather than raw bytes.

**Alternatives:**
- Hash raw bytes — simplest
- Parse to AST and hash semantic structure — most robust but complex

**Why:** BookStack's markdown editor normalizes some whitespace on save. Raw-byte hashing would produce false-positive conflicts on every push even when nothing changed semantically. Semantic AST hashing would need a full markdown parser and would be over-engineered for a sync tool.

**Escape hatch:** If normalization turns out insufficient and still produces false conflicts, `--force` bypasses the check. We also re-tag with the true stored hash after each push to self-correct.

---

## 3. Single normalization source of truth

**Decision:** All markdown normalization happens in `content.normalize_markdown()`. Other modules call it; they do not implement their own normalization.

**Why:** Normalization is load-bearing — a bug here causes false-positive conflicts everywhere. One place to fix means one place to get right. Tests in `test_content.py` pin the behavior.

---

## 4. No full git-style two-way merge

**Decision:** bssync detects conflicts and prompts the user to pick a side (overwrite-remote or pull-remote-first). It does not attempt three-way merge or produce conflict markers in files.

**Alternatives:**
- Three-way merge with a stored base version — robust but requires local state
- Merge via `git merge-file` — pulls in git as a dependency

**Why:** Merging markdown automatically can corrupt tables, code blocks, and lists in subtle ways. The user is better served by seeing the diff and choosing a side. BookStack's own version history handles reversibility.

---

## 5. stdlib `argparse`, not click or typer

**Decision:** CLI uses `argparse` from the standard library.

**Why:** Minimizes dependencies. The CLI surface is small (5 commands, ~15 flags). click/typer buy us nothing material at this scale while adding a dep. Python's `argparse` is good enough.

---

## 6. Two runtime dependencies only

**Decision:** `pyyaml` and `requests`. No more without strong justification.

**Why:** CLI tools that pull in dozens of deps are fragile to install, slow to start, and hard to audit for security. Users install bssync via `pip` — every dep they get is a dep they have to trust.

**Consequence:** No rich terminal formatting (rich), no fancy argument parsing (click/typer), no dataclass serialization (pydantic). Plain prints and argparse are fine.

---

## 7. Hashed tags are the sync primitive, not timestamps

**Decision:** Conflict detection compares content hashes, not `updated_at` timestamps.

**Alternatives:**
- Compare `updated_at` on BookStack vs local `mtime` — simpler, but fragile
- Use BookStack's revision system directly — ties us to their API internals

**Why:** Timestamps suffer clock skew, editor "save-with-no-changes" events, and timezone ambiguity. Content hashes are unambiguous: if the hash changed, the content changed. If it didn't, nothing changed.

---

## 8. Lazy imports in the CLI module

**Decision:** `cli.py` imports subcommand handlers inside the function body where they're used.

**Why:** `bssync init` and `bssync --help` shouldn't pay for loading `requests`, `yaml`, and the full sync logic. Lazy imports keep these common paths fast (~50ms vs ~200ms). Trivial optimization, but CLI startup time is a UX concern.

---

## 9. `init` is a subcommand, not a separate tool

**Decision:** `bssync init` prompts for URL and credentials, tests the connection, and writes `bookstack.yaml`. Distinct subcommand of the main tool.

**Why:** "One-command setup" is a core UX goal. If init were a separate binary or a separate manual procedure, we'd be shipping complexity the user has to discover. Making it a subcommand keeps everything in one tool.

---

## 10. Entry-point binary, PyInstaller for releases

**Decision:**
- For Python users: `pip install bssync` wires up a `bssync` command via `[project.scripts]` in `pyproject.toml`.
- For users without Python: GitHub Release includes PyInstaller-built single-file binaries for macOS and Linux.

**Why:** Python users expect pip-based installs. Non-Python users expect "download a binary and run it." Both audiences exist. PyInstaller binaries are larger (~15MB) but require zero dependencies on the target machine.
