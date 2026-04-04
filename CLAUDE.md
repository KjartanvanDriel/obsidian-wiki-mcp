# obsidian-wiki-mcp

MCP server for structured wiki operations on an Obsidian vault.

## Build & run

- Uses `uv` for dependency management — always use `uv run`, never bare `python` or `pip`
- `uv run python -m obsidian_wiki_mcp.server` — run the server
- `uv run python -c "from obsidian_wiki_mcp.server import wiki"` — quick import check
- Installed in editable mode — code changes take effect immediately, no reinstall needed
- Exception: changes to `pyproject.toml` (dependencies, entry points) require `uv pip install -e .`

## Architecture

- Single `wiki` MCP tool with an `action` parameter dispatching to vault methods
- Stateless — no index, no cache, scans vault on every request
- `server.py` routes actions → `vault.py` does the work → `schemas.py` validates → `models.py` holds dataclasses
- `scaffold/` contains template files synced into vaults on server startup
- Scaffold sync: commands/CLAUDE.md always overwrite; schemas only if vault copy is unmodified (SHA256 hash check via `.scaffold-hashes.json`)

## Conventions

- All vault file operations must stay within `self.root` — never write outside the vault
- New actions: add to `_dispatch()` in server.py, implement in vault.py, update tool docstring and instructions string
- Keep the single-tool design — add actions, not new tools
