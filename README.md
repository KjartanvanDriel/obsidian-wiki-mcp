# obsidian-wiki-mcp

A structured wiki layer on top of Obsidian, exposed as an MCP server for Claude Code. An LLM creates and maintains wiki pages; you curate in Obsidian.

## Quick start

```bash
# Install
pip install -e .

# Initialize a vault
obsidian-wiki-init /path/to/my-wiki

# Open in Obsidian, then run Claude Code in the vault
cd /path/to/my-wiki
claude
```

The init command creates everything: folder structure, page type schemas, style guide, CLAUDE.md, and slash commands. It also initializes git.

## What you get

### Vault structure

```
my-wiki/
├── CLAUDE.md                        # Agent identity (loaded every session)
├── .claude/commands/
│   ├── wiki.md                      # /wiki — main wiki operations
│   ├── wiki-audit.md                # /wiki-audit — health checks
│   └── wiki-ingest.md               # /wiki-ingest — add papers/resources
├── _schemas/                        # Page type definitions (YAML)
├── _wiki/style-guide.md             # Writing conventions
├── references.bib                   # BibTeX citations
├── knowledge/
│   ├── concepts/
│   ├── tools/
│   ├── people/
│   └── resources/attachments/
└── work/
    ├── daily/                       # Auto-generated daily logs
    └── projects/
        └── {project-name}/
            ├── _project.md
            ├── experiments/
            ├── deliverables/
            ├── decisions/
            ├── tasks/
            ├── notes/
            └── attachments/         # Raw files (gitignored)
```

### Page types

**Knowledge layer** (cross-project, long-lived): Concept, Tool, Person, Resource

**Work layer** (scoped to a project): Project, Deliverable, Experiment, Decision, Task, Note

Each type has a YAML schema defining required fields, enums, and defaults.

### MCP tool

A single `wiki` tool with 12 actions:

| Action | Purpose |
|--------|---------|
| `create` | Create a page — validates schema, blocks duplicates |
| `read` | Page content + metadata + backlinks |
| `update` | Patch metadata and/or body |
| `search` | Full-text and metadata-filtered search |
| `validate` | Check pages against schemas |
| `health` | Orphans, stubs, broken links, duplicates |
| `project` | Project overview with children and artifacts |
| `links` | Backlinks and outlinks |
| `provenance` | Get/set generation sources |
| `commit` | Git commit changes + auto-append to daily log |
| `style` | Read/update the style guide |
| `move_file` | Move/rename files to attachments with BibTeX-key naming |

### Slash commands

| Command | Use case |
|---------|----------|
| `/wiki create a concept page about RLHF` | Any wiki work — loads full operational context |
| `/wiki-audit` | Run health checks, fix issues |
| `/wiki-ingest https://arxiv.org/...` | Add a paper or resource (supports `--approval` and `--scope` flags) |
| `/wiki-update-project /path/to/repo` | Diff a project since last update, create/update wiki pages |

## Configuration

After `obsidian-wiki-init`, add the MCP server config. Create `.mcp.json` in the vault root:

```json
{
  "mcpServers": {
    "obsidian-wiki": {
      "command": "obsidian-wiki-mcp",
      "env": {
        "VAULT_PATH": "/path/to/my-wiki"
      }
    }
  }
}
```

Or if running without installing:

```json
{
  "mcpServers": {
    "obsidian-wiki": {
      "command": "python",
      "args": ["-m", "obsidian_wiki_mcp.server"],
      "env": {
        "VAULT_PATH": "/path/to/my-wiki",
        "PYTHONPATH": "/path/to/obsidian-wiki-mcp/src"
      }
    }
  }
}
```

## Architecture

```
┌──────────────┐     MCP      ┌──────────────────────┐
│  Claude Code │◄────────────►│  wiki MCP server     │
└──────────────┘              │  (stateless, parses   │
                              │   vault files on      │
       ┌──────────┐           │   each request)       │
       │ Obsidian │           └──────────┬────────────┘
       └────┬─────┘                      │
            │      shared filesystem     │
            └────────────┬───────────────┘
                  ┌──────▼───────┐
                  │  Vault (.md) │
                  │  + Git       │
                  └──────────────┘
```

No database. No index. No sync. The MCP server reads and writes markdown files directly. Obsidian and Claude Code share the same folder. Git provides versioning.

## Extending

### Add a new page type

1. Create `_schemas/mytype.yaml` following the existing schema format
2. Define required fields, enums, defaults
3. The MCP server picks it up automatically on next request

### Evolve the style guide

Tell Claude: "update the style guide to say we prefer tables over bullet lists in concept pages" — or edit `_wiki/style-guide.md` directly in Obsidian.

### Add new slash commands

Drop a `.md` file in `.claude/commands/`. Use `$ARGUMENTS` to pass through user input.
