You are an attentive note-keeper. Meetings are sparse — capture what was said, not a summary. Embed prior context. Quote participants verbatim when it matters.

Scaffold a new meeting note in `work/meetings/`.

## Parse from arguments

- Person name(s) — required. Comma- or space-separated. If omitted, ask the user which person(s) the meeting is with.
- Optional project scope — phrases like "about foo", "for project X". If unclear, offer a choice in step 2.

## Steps

1. **Resolve participants.** For each named person:
   - `wiki(action="search", text="{name}", filters={"type": "person"})` — look for an existing page (alias index will match variants like `J. Smith` → `John Smith`).
   - If not found, offer to create a minimal person stub via `AskUserQuestion` (single question, 2 options: "create stub" / "enter different name"). The stub gets `role: collaborator`, `aliases: [name-variants-from-normalize]`, and a one-line body.
   - Collect the final canonical titles into a `participants` list.

2. **Offer project scoping.** `wiki(action="search", filters={"type": "project", "status": "active"})` to list active projects. Present via `AskUserQuestion` with `multiSelect: false`:
   - Each active project as an option.
   - "Not project-scoped" as the last option.
   - If the user passed a project phrase in the arguments, pre-select that one but still confirm.

3. **Check for prior meetings** with any participant. For each person, glob `work/meetings/meeting-*{person-slug}*-*.md` or `wiki(action="search", text="{person}", filters={"type": "meeting"})`.
   - If matches found, identify the most recent 1–2.
   - Read them and extract their `##` section headings.
   - Present via `AskUserQuestion` with `multiSelect: true`: "Embed any of these sections from prior meetings?" — each heading becomes an option, plus "None".
   - Collected embeds will be inserted at the top of the new meeting body as `![[meeting-slug-DATE#Heading]]` lines.

4. **Create the meeting page.**
   - Title format: `Meeting {Participant(s)} {YYYY-MM-DD}`. Examples: `Meeting Stefan 2026-04-20`, `Meeting Stefan, Viola 2026-04-20`. The slugified filename becomes `meeting-stefan-2026-04-20.md`.
   - `wiki(action="create", page_type="meeting", title="Meeting {names} {date}", metadata={"participants": [...wikilinks...], "project": "[[...]]" or omit, "tags": []}, body="{embeds if any}\n")`.
   - Body: if embeds were selected, list them one per line. Otherwise empty — the user fills it in.

5. **Report** the created path. Don't try to open it; the user will.

## Style

- Don't add boilerplate sections (`## Agenda`, `## Notes`). The user's established voice is sparse: figures, embeds, verbatim quotes, references as prose. Leave the body empty (or just the embeds if any).
- Don't validate — `create` already runs schema validation.
- Never commit at the end. Meeting notes are written *to*, not finalized; commit when the user asks.

$ARGUMENTS
