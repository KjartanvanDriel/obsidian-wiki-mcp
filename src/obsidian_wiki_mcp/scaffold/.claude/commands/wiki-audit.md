You are a meticulous inspector reviewing the vault. You check everything systematically, report what you find without alarm, and suggest practical fixes.

## Steps

1. **MCP health check**: Run `wiki(action="health")` for the full report.
2. **Schema validation**: Run `wiki(action="validate")` for detailed errors.
3. **Stray files**: Check the vault root and project folders for markdown files that don't belong (not in `knowledge/`, `work/`, or expected locations). Use the filesystem to look.
4. **Threads check**: For each project:
   - Verify `threads/index.md` exists
   - Each thread folder listed in the index has a landing page (`{slug}/{slug}.md`)
   - Wikilinks in index.md use full path format (`[[slug/slug|name]]`, not `[[slug]]`)
   - No thread folders exist that aren't listed in the index
5. **Stale todos**: Read each project's `todos.md` — flag items older than 7 days that are still open.
6. **Repo access**: Check project `repos` metadata — verify each path is in `.claude/settings.local.json` → `additionalDirectories`.

## Present findings

Group by severity:

- **Errors**: validation failures, broken links, missing thread indices or landing pages
- **Warnings**: orphan pages, stubs, suspected duplicates, stray files, wrong wikilink format in thread index
- **Info**: stale todos, empty thread folders, repos not in allowed directories

For each issue, state the problem and a concrete fix. Don't elaborate.

## Fix

Ask the user which issues to fix using `AskUserQuestion` with `multiSelect: true`. Then fix the selected items. Validate again after fixes, then offer to commit.

$ARGUMENTS
