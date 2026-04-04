Survey a project and update the wiki to reflect what's changed.

## Modes

- **New project from repo**: `/wiki-survey /path/to/repo` — creates a project page, does initial survey of the codebase
- **Existing project**: `/wiki-survey [[Project Name]]` — diffs since last survey and updates the wiki
- **All projects**: `/wiki-survey` (no args) — surveys all active projects

## Options

Parse from arguments if provided:
- **approval**: `autonomous` | `checked` (default: `checked`)
- **scope**: `central` | `thorough` (default: `central`)

## Steps

### 1. Identify the project

- If a path is given: check if a project page already tracks this repo. If not, create a new project page via `/wiki` and add the repo to its `repos` metadata.
- If a project name is given: read the project page, get its `repos` list and `last_vault_survey` hash.
- If no args: search for all active projects and survey each.

### 2. Collect diffs

**Always — vault project folder:**
- Get the project's `last_vault_survey` commit hash from metadata
- If set: `git diff {last_vault_survey}..HEAD -- work/projects/{slug}/` in the vault repo
- If not set (first survey): treat the entire project folder as new content
- Also diff any knowledge-layer pages linked from the project

**For each linked repo:**
- Get its `last_surveyed` commit hash from the `repos` metadata
- If set: `git diff {last_surveyed}..HEAD` in that repo
- If not set (first survey): scan the repo broadly — README, directory structure, dependencies, recent git log (last 20 commits)

### 3. Analyze changes

From the diffs, identify:

- **New concepts** — abstractions, patterns, algorithms that don't have wiki pages yet
- **New tools** — dependencies, frameworks, services added or changed
- **Decisions** — architecture choices visible in the diff (new patterns, migrations, config changes)
- **Status updates** — has the project's status changed? New milestones? Blockers?
- **Stale pages** — wiki pages that reference code/patterns that have been removed or renamed

### 4. Present findings

Based on **approval** mode:

**checked (default):**
Present a summary grouped by category:
```
## Survey: {Project Name}

### Vault changes since {last_vault_survey}
- {summary of wiki changes}

### Repo changes since {last_surveyed} ({repo path})
- {summary of code changes}

### Proposed wiki updates
- [ ] Create concept: {name} — {reason}
- [ ] Create tool: {name} — {reason}
- [ ] Create decision: {name} — {reason}
- [ ] Update project status: {old} → {new}
- [ ] Flag stale: {page} — {reason}

Which of these should I proceed with?
```

**autonomous:**
Proceed with all proposed updates without asking.

### 5. Execute updates

For each approved update:
- Create/update pages following the standard wiki workflow (read style guide, set provenance, validate)
- Use `sources_used: [{type: "context", ref: "Survey of {repo} at commit {hash}"}]`
- For concept/tool stubs, follow the **scope** setting (central = key items only, thorough = everything identified)

### 6. Update survey markers

After all changes:
- Update the project page's `last_vault_survey` to the current vault HEAD commit
- Update each repo's `last_surveyed` to its current HEAD commit
- Update the project page's status/body if warranted

### 7. Commit

Ask for approval, then commit with message: `Survey: {Project Name} ({date})`

$ARGUMENTS
