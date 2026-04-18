"""MCP server exposing a single `wiki` tool with sub-commands."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from mcp.server.fastmcp import FastMCP

from .schemas import SchemaRegistry
from .vault import Vault

SCAFFOLD_DIR = Path(__file__).parent / "scaffold"

# ── Configuration ─────────────────────────────────────────────────────

mcp = FastMCP(
    "obsidian-wiki",
    instructions="""Wiki MCP server for structured operations on an Obsidian vault.
Use the `wiki` tool with an `action` parameter. Available actions:
  create  — Create a new page (validates schema, checks duplicates)
  read    — Read a page's metadata + body + backlinks
  update  — Patch a page's metadata and/or body
  search  — Full-text and/or metadata-filtered search
  validate — Check one page or whole vault against schemas
  health  — Orphans, stubs, broken links, duplicates report
  project — Project overview with children and artifacts
  links   — Backlinks and/or outlinks for a page
  provenance — Get or set generation sources for a page
  commit  — Git commit all current changes
  style   — Read or update the wiki style guide. Read this before writing content.
  move_file — Move/rename a file to attachments with optional BibTeX-key naming
  create_thread — Create a research thread (folder, landing page, index entry)
""",
)


def _get_vault() -> Vault:
    """Initialize vault and schema registry from env vars."""
    vault_path_str = os.environ.get("VAULT_PATH", "")
    schemas_path_str = os.environ.get("SCHEMAS_PATH", "")

    vault_path = Path(vault_path_str)
    if not vault_path.exists():
        raise ValueError(f"VAULT_PATH does not exist: {vault_path_str}")

    if schemas_path_str:
        schemas_dir = Path(schemas_path_str)
    else:
        schemas_dir = vault_path / "_schemas"

    schemas = SchemaRegistry(schemas_dir)
    return Vault(vault_path, schemas)


# ── The wiki tool ─────────────────────────────────────────────────────


@mcp.tool()
def wiki(
    action: str,
    title: str | None = None,
    page_type: str | None = None,
    metadata: dict[str, Any] | None = None,
    body: str | None = None,
    project: str | None = None,
    append: bool = False,
    text: str | None = None,
    filters: dict[str, Any] | None = None,
    sort: str | None = None,
    limit: int = 20,
    direction: str = "both",
    mode: str = "get",
    sources: list[dict] | None = None,
    message: str | None = None,
    checks: list[str] | None = None,
    content: str | None = None,
    section: str | None = None,
    section_content: str | None = None,
    files: list[str] | None = None,
    source: str | None = None,
    destination: str | None = None,
    bibtex_key: str | None = None,
) -> str:
    """
    Structured wiki operations on an Obsidian vault.

    Actions:
      create     — Create a page. Requires: page_type, title. Optional: metadata, body, project.
      read       — Read a page. Requires: title.
      update     — Update a page. Requires: title. Optional: metadata, body, append, section, section_content. Use section + section_content to replace a section. Use section + body + append=true to append to a section.
      search     — Search pages. Optional: text (full-text), filters (metadata), sort, limit.
      validate   — Validate pages. Optional: title (omit for whole vault).
      health     — Vault health report. Optional: checks (list of: orphans, stubs, broken_links, validation, duplicates).
      project    — Project overview. Requires: title.
      links      — Get links. Requires: title. Optional: direction (in/out/both).
      provenance — Get/set sources. Requires: title. Optional: mode (get/set), sources.
      commit     — Git commit. Requires: message. Optional: files (list of paths to stage; omit for all).
      style      — Read or update the wiki style guide. mode='read' (default): read full or section. mode='update': replace full (content) or patch (section + section_content). mode='init': create default.
      move_file  — Move/rename a file into attachments. Requires: source (path relative to vault root). Optional: destination, bibtex_key.
      create_thread — Create a research thread. Requires: project, title. Optional: body (description). Creates folder, landing page, and index entry.
    """
    try:
        vault = _get_vault()
    except ValueError as e:
        return json.dumps({"error": str(e)})

    try:
        result = _dispatch(
            vault,
            action=action,
            title=title,
            page_type=page_type,
            metadata=metadata,
            body=body,
            project=project,
            append=append,
            text=text,
            filters=filters,
            sort=sort,
            limit=limit,
            direction=direction,
            mode=mode,
            sources=sources,
            message=message,
            checks=checks,
            content=content,
            section=section,
            section_content=section_content,
        )
    except Exception as e:
        result = {"error": f"Unexpected error: {e}"}

    return json.dumps(result, indent=2, default=str)


def _dispatch(vault: Vault, *, action: str, **kwargs) -> dict:
    """Route action to the appropriate vault method."""

    if action == "create":
        if not kwargs.get("page_type"):
            return {"error": "create requires 'page_type'"}
        if not kwargs.get("title"):
            return {"error": "create requires 'title'"}
        return vault.create_page(
            page_type=kwargs["page_type"],
            title=kwargs["title"],
            metadata=kwargs.get("metadata"),
            body=kwargs.get("body", ""),
            project=kwargs.get("project"),
        )

    elif action == "read":
        if not kwargs.get("title"):
            return {"error": "read requires 'title'"}
        return vault.read_page(kwargs["title"])

    elif action == "update":
        if not kwargs.get("title"):
            return {"error": "update requires 'title'"}
        return vault.update_page(
            title=kwargs["title"],
            metadata=kwargs.get("metadata"),
            body=kwargs.get("body"),
            append=kwargs.get("append", False),
            section=kwargs.get("section"),
            section_content=kwargs.get("section_content"),
        )

    elif action == "search":
        return vault.search(
            text=kwargs.get("text"),
            filters=kwargs.get("filters"),
            sort=kwargs.get("sort"),
            limit=kwargs.get("limit", 20),
        )

    elif action == "validate":
        return vault.validate(title=kwargs.get("title"))

    elif action == "health":
        return vault.health(checks=kwargs.get("checks"))

    elif action == "project":
        if not kwargs.get("title"):
            return {"error": "project requires 'title'"}
        return vault.project_overview(kwargs["title"])

    elif action == "links":
        if not kwargs.get("title"):
            return {"error": "links requires 'title'"}
        return vault.get_links(
            title=kwargs["title"],
            direction=kwargs.get("direction", "both"),
        )

    elif action == "provenance":
        if not kwargs.get("title"):
            return {"error": "provenance requires 'title'"}
        if kwargs.get("mode") == "set":
            if not kwargs.get("sources"):
                return {"error": "provenance set requires 'sources'"}
            return vault.set_provenance(kwargs["title"], kwargs["sources"])
        return vault.get_provenance(kwargs["title"])

    elif action == "commit":
        if not kwargs.get("message"):
            return {"error": "commit requires 'message'"}
        return vault.commit(kwargs["message"], files=kwargs.get("files"))

    elif action == "style":
        m = kwargs.get("mode", "read")
        if m in ("read", "get"):
            return vault.get_style_guide(section=kwargs.get("section"))
        elif m == "update":
            return vault.update_style_guide(
                content=kwargs.get("content"),
                section=kwargs.get("section"),
                section_content=kwargs.get("section_content"),
            )
        elif m == "init":
            default = _load_default_style_guide()
            return vault.init_style_guide(default)
        else:
            return {"error": f"Unknown style mode: {m}. Use 'read', 'update', or 'init'."}

    elif action == "move_file":
        if not kwargs.get("source"):
            return {"error": "move_file requires 'source'"}
        return vault.move_file(
            source=kwargs["source"],
            destination=kwargs.get("destination"),
            bibtex_key=kwargs.get("bibtex_key"),
        )

    elif action == "create_thread":
        if not kwargs.get("project"):
            return {"error": "create_thread requires 'project'"}
        if not kwargs.get("title"):
            return {"error": "create_thread requires 'title'"}
        return vault.create_thread(
            project=kwargs["project"],
            title=kwargs["title"],
            description=kwargs.get("body", ""),
        )

    else:
        return {
            "error": f"Unknown action: {action}",
            "available_actions": [
                "create", "read", "update", "search", "validate",
                "health", "project", "links", "provenance", "commit",
                "style", "move_file", "create_thread",
            ],
        }


def _load_default_style_guide() -> str:
    """Load the bundled default style guide."""
    style_path = Path(__file__).parent / "scaffold" / "_wiki" / "style-guide.md"
    if style_path.exists():
        return style_path.read_text(encoding="utf-8")
    return "# Wiki Style Guide\n\n> This is a living document. Update it as conventions evolve.\n\n## Voice & Tone\n\nWrite like a knowledgeable colleague. Be direct, precise, and concise.\n"


# ── Scaffold sync ────────────────────────────────────────────────────

# Files that are safe to auto-update (not user-customizable)
_SYNC_PATHS = [
    ".claude/commands/wiki.md",
    ".claude/commands/wiki-audit.md",
    ".claude/commands/wiki-ingest.md",
    ".claude/commands/wiki-update-project.md",
    ".claude/commands/research.md",
    ".claude/commands/wiki-diary.md",
    "CLAUDE.md",
]

# Files synced only if unchanged from a previous scaffold version
_SYNC_IF_UNCHANGED_PATHS = [
    "Landing.md",
    "_schemas/concept.yaml",
    "_schemas/decision.yaml",
    "_schemas/deliverable.yaml",
    "_schemas/experiment.yaml",
    "_schemas/note.yaml",
    "_schemas/person.yaml",
    "_schemas/project.yaml",
    "_schemas/resource.yaml",
    "_schemas/task.yaml",
    "_schemas/tool.yaml",
]


def _file_hash(path: Path) -> str:
    """SHA256 hash of a file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sync_scaffold(vault_path: Path) -> None:
    """Sync scaffold files from the installed package into the vault.

    - Command files and CLAUDE.md are always updated.
    - Schema files are only updated if the vault copy matches the previous
      scaffold version (i.e., the user hasn't customized them).
    """
    if not SCAFFOLD_DIR.exists():
        return

    updated = []

    # Always-sync files
    for rel in _SYNC_PATHS:
        src = SCAFFOLD_DIR / rel
        dest = vault_path / rel
        if not src.exists():
            continue
        if dest.exists() and _file_hash(src) == _file_hash(dest):
            continue  # Already up to date
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        updated.append(rel)

    # Sync-if-unchanged files (schemas)
    hash_file = vault_path / ".scaffold-hashes.json"
    prev_hashes: dict[str, str] = {}
    if hash_file.exists():
        try:
            prev_hashes = json.loads(hash_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    new_hashes: dict[str, str] = {}
    for rel in _SYNC_IF_UNCHANGED_PATHS:
        src = SCAFFOLD_DIR / rel
        dest = vault_path / rel
        if not src.exists():
            continue

        src_hash = _file_hash(src)
        new_hashes[rel] = src_hash

        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())
            updated.append(rel)
        elif _file_hash(dest) == src_hash:
            continue  # Already up to date
        elif rel in prev_hashes and _file_hash(dest) == prev_hashes[rel]:
            # Vault copy matches previous scaffold version — safe to update
            dest.write_bytes(src.read_bytes())
            updated.append(rel)
        else:
            # User has customized this file — skip
            logger.info("Skipping %s (locally modified)", rel)

    # Save current scaffold hashes for next sync
    hash_file.write_text(json.dumps(new_hashes, indent=2), encoding="utf-8")

    if updated:
        logger.info("Synced %d scaffold file(s): %s", len(updated), ", ".join(updated))


# ── Entry point ───────────────────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog="obsidian-wiki-mcp",
        description="MCP server for structured wiki operations on an Obsidian vault",
    )
    subparsers = parser.add_subparsers(dest="command")

    # init subcommand
    init_parser = subparsers.add_parser("init", help="Initialize a new wiki vault")
    init_parser.add_argument("path", type=Path, help="Path to the vault directory")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing files")

    # serve is the default (no subcommand)
    serve_parser = subparsers.add_parser("serve", help="Start the MCP server")
    serve_parser.add_argument("--vault", type=str, help="Path to vault (overrides VAULT_PATH env)")

    args = parser.parse_args()

    if args.command == "init":
        from .init import init_vault
        init_vault(args.path, force=args.force)
        return

    # Default: serve
    vault_path = getattr(args, "vault", None) or os.environ.get("VAULT_PATH", "")
    if not vault_path:
        logger.error("VAULT_PATH environment variable or --vault flag is required.")
        logger.error("  export VAULT_PATH=/path/to/your/obsidian/vault")
        logger.error("  obsidian-wiki-mcp serve --vault /path/to/vault")
        logger.error("To create a new vault:")
        logger.error("  obsidian-wiki-mcp init /path/to/vault")
        sys.exit(1)

    if not Path(vault_path).exists():
        logger.error("Vault path does not exist: %s", vault_path)
        logger.error("To initialize a new vault:")
        logger.error("  obsidian-wiki-mcp init %s", vault_path)
        sys.exit(1)

    # Set env so _get_vault() picks it up
    os.environ["VAULT_PATH"] = str(vault_path)

    # Sync scaffold files into the vault
    _sync_scaffold(Path(vault_path))

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(name)s: %(message)s")
    logger.info("Starting obsidian-wiki MCP server (vault: %s)", vault_path)
    mcp.run()


if __name__ == "__main__":
    main()
