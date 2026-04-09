# obsidian-wiki-mcp

An MCP server for building structured, persistent wikis in Obsidian. The LLM writes and maintains the wiki; you curate in Obsidian.

Two agents with different roles: a **librarian** that organizes knowledge pages, and a **researcher** that thinks through problems and tracks progress in threads.

## Quick start

```bash
# Install with uv
uv pip install -e .

# Initialize a vault
obsidian-wiki-init /path/to/my-wiki

# Open in Obsidian, then run Claude Code in the vault
cd /path/to/my-wiki
claude
```

The init command creates everything: folder structure, page type schemas, style guide, landing page, CLAUDE.md, and slash commands. It also initializes git.

## What you get

### Vault structure

```
my-wiki/
├── CLAUDE.md                        # Agent identity (loaded every session)
├── Landing.md                       # Dataview dashboard (projects, activity, knowledge)
├── .claude/commands/
│   ├── wiki.md                      # /wiki — librarian operations
│   ├── wiki-audit.md                # /wiki-audit — health checks
│   ├── wiki-ingest.md               # /wiki-ingest — add papers/resources
│   ├── wiki-update-project.md       # /wiki-update-project — sync with repos
│   └── research.md                  # /research — project-scoped research agent
├── _schemas/                        # Page type definitions (YAML)
├── _wiki/style-guide.md             # Writing conventions
├── references.bib                   # BibTeX citations
├── to_ingest/                       # Drop files here for ingestion
├── knowledge/
│   ├── concepts/
│   ├── tools/
│   ├── people/
│   └── resources/attachments/
└── work/
    ├── daily/                       # Auto-generated daily logs
    └── projects/
        └── {project-name}/
            ├── {project-name}.md    # Project narrative
            ├── threads/             # Research threads
            │   ├── index.md         # Active/resolved thread list
            │   └── {thread-slug}/
            │       ├── {thread-slug}.md  # Landing page
            │       └── YYYY-MM-DD.md     # Session notes
            ├── todos.md
            ├── experiments/
            ├── deliverables/
            ├── decisions/
            ├── tasks/
            ├── notes/
            └── attachments/         # Raw files (gitignored)
```

### Agents

**Librarian** (`/wiki`) — organizes knowledge. Creates pages, validates schemas, maintains links, runs health checks. Quiet, careful, doesn't embellish.

**Researcher** (`/research`) — thinks about problems. Picks up threads, reasons step by step, accumulates notes in session files. Proposes wiki pages but delegates creation to the librarian. Presents new questions via `AskUserQuestion` so you choose what to pursue.

### Page types

**Knowledge layer** (cross-project, long-lived): Concept, Tool, Person, Resource

**Work layer** (scoped to a project): Project, Deliverable, Experiment, Decision, Task, Note

Each type has a YAML schema defining required fields, enums, and defaults. Schema validation catches errors before pages are written.

### MCP tool

A single `wiki` tool with 12 actions:

| Action | Purpose |
|--------|---------|
| `create` | Create a page — validates schema, blocks duplicates |
| `read` | Page content + metadata + backlinks |
| `update` | Patch metadata and/or body |
| `search` | Full-text and metadata-filtered search (capped at 100) |
| `validate` | Check pages against schemas |
| `health` | Orphans, stubs, broken links, duplicates |
| `project` | Project overview with children and artifacts |
| `links` | Backlinks and outlinks |
| `provenance` | Get/set generation sources |
| `commit` | Git commit (all or specific files) + auto-append to daily log |
| `style` | Read/update the style guide |
| `move_file` | Move/rename files to attachments with BibTeX-key naming |

### Slash commands

| Command | Purpose |
|---------|---------|
| `/wiki` | Librarian — create, update, organize wiki pages |
| `/wiki-audit` | Health check — broken links, orphans, stray files, stale todos |
| `/wiki-ingest URL` | Add a paper or resource (supports `--approval` and `--scope` flags) |
| `/wiki-update-project` | Diff a project's vault + repos since last update |
| `/research [[Project]]` | Research agent — work threads, explore concepts, synthesize |

### Link resolution

Wikilinks use `[[slug|Display Name]]` format. The health checker resolves links through three indices (slug, title, alias) and skips wikilinks inside code blocks.

For threads (where folder and file share a name): `[[thread-slug/thread-slug|Thread Name]]`.

## Configuration

Add the MCP server config to `.mcp.json` (or `.claude/mcp.json`):

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

If the binary isn't on PATH, use the full venv path:

```json
{
  "mcpServers": {
    "obsidian-wiki": {
      "command": "/path/to/obsidian-wiki-mcp/.venv/bin/obsidian-wiki-mcp",
      "env": {
        "VAULT_PATH": "/path/to/my-wiki"
      }
    }
  }
}
```

### External repo access

Projects can link to external repos via `repos` metadata. Add repo paths to `.claude/settings.local.json` → `permissions.additionalDirectories` so agents can read them. The agent will ask before accessing any external directory.

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

No database. No index. No sync. The MCP server reads and writes markdown files directly. Obsidian and Claude Code share the same folder. Git provides versioning. Scaffold files sync on server startup (commands always, schemas only if unchanged).

## Testing

```bash
uv run pytest tests/ -v
```

69 tests covering all 12 actions, including path traversal security, slug/title/alias link resolution, code block stripping, git commit with selective staging, and schema validation.

## Extending

### Add a new page type

1. Create `_schemas/mytype.yaml` following the existing schema format
2. Define required fields, enums, defaults
3. The MCP server picks it up automatically on next request

### Evolve the style guide

Tell Claude: "update the style guide to prefer tables over bullet lists in concept pages" — or edit `_wiki/style-guide.md` directly in Obsidian.

### Add new slash commands

Drop a `.md` file in `.claude/commands/`. Use `$ARGUMENTS` to pass through user input.

## Inspiration

Inspired by [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — the idea that an LLM should incrementally build and maintain a persistent wiki rather than re-derive knowledge from raw sources on every query.

## License

MIT
