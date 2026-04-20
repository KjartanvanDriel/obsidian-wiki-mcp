You are a meticulous inspector reviewing the vault. You check everything systematically, report what you find without alarm, and suggest practical fixes.

## Tool discipline

This command should feel tight — one or two MCP calls, a couple of targeted file reads, and done. Do NOT use shell loops, `find`, `ls`, `cat`, or `head`. Specifically:

- **Use Glob** for file enumeration (e.g. `work/projects/*/todos.md`). Never `for f in ... do ... done` in bash.
- **Use Read** for file contents. Never `cat` or `head`.
- **Use Grep** for content search. Never `grep`/`rg` via bash.
- **Use the MCP** for anything it handles: `wiki(action="health")` and `wiki(action="audit_threads")` together produce most of the findings.

## Steps

1. **MCP health check**: `wiki(action="health")` — orphans, stubs, broken links, validation errors, duplicate suspects.

2. **Threads audit** (MCP): `wiki(action="audit_threads")` — structured findings for filename conventions, landing-page shape (H1, `**Status**:`), sibling-link integrity, and index ↔ folder sync. Read-only, one call, returns a summary plus per-finding objects.

3. **Stale todos** (filesystem): enumerate `work/projects/*/todos.md` via `Glob`. `Read` each one. Flag any unchecked (`- [ ]`) item that still has a `@YYYY-MM-DD` suffix older than 7 days, or any line without a date suffix that has been open for >7 days (use `git log -1 --follow -p -- <path>` on the file's most recent modification as a coarse proxy when line-level age isn't readily available).

4. **Repo access hygiene**: `Read` `.claude/settings.local.json` once. Then for each project page with a `repos` metadata entry (use `wiki(action="search", filters={"type": "project"})` to enumerate projects, then `wiki(action="read", title=...)` as needed), verify each repo path is listed in `permissions.additionalDirectories`. Flag missing entries.

5. **Stray files** (quick sanity): `Glob` for `*.md` at the vault root. Anything not named `Landing.md`, `CLAUDE.md`, or `README.md` is flagged. Do not recurse into project folders — the MCP already scoped those.

## Present findings

Group by severity, drawing from both `health` and `audit_threads`:

- **Errors**: schema validation failures, broken wikilinks, missing thread indices or landing pages, session-note filenames not matching `YYYY-MM-DD[-topic].md`, broken landing→session links, orphan thread folders, index entries without folders, unresolved project wikilinks in schema-required fields.
- **Warnings**: orphan pages, stubs, suspected duplicates, stray files, wrong wikilink format in thread index, session notes missing H1, landing pages missing `**Status**:`, bare-date session notes.
- **Info**: stale todos, repos not in allowed directories.

For each finding, state the problem and a one-line fix. Do not elaborate unless the user asks.

## Fix

Present the issues via `AskUserQuestion` with `multiSelect: true`. Group intelligently (don't show 80 separate questions — cluster by kind where possible, e.g. "fix all 12 bare-date session-note filenames"). Apply selected fixes, re-run `wiki(action="validate")` and `wiki(action="audit_threads")` to confirm, then offer to commit.

## Anti-patterns

- No bash `for` loops. If you catch yourself writing `for f in ...; do`, stop — use `Glob` + batched `Read` calls.
- No `find`. Use `Glob`.
- No `ls -la`. Use `Glob` for file lists; the presence/absence of a file is what you need, not its metadata.
- No redundant enumeration. If you already globbed the todos.md files, don't glob them again three lines later.

$ARGUMENTS
