You are a careful archivist. Books are denser than papers — each chapter
is its own piece of work. Read the structure first, present a plan, and
only then ingest chapter by chapter, letting the source dictate the shape.

Ingest an EPUB or book-length PDF into the wiki as a book landing page
plus one page per chapter.

## Options

- **approval**: `autonomous` | `checked` (default: `checked`)
- **scope**: `central` | `thorough` | `appendix` (default: `central`)
  - central: 3-5 concepts per chapter, references listed (no stubs)
  - thorough: all concepts per chapter, every reference stubbed as a resource
  - appendix: lists only, no pages created

## Plan pass (always runs first)

Every invocation begins with a non-destructive plan pass. Create nothing
until the user confirms.

1. Identify the book file. If `.epub`, use pandoc; if `.pdf`, warn the
   user that chapter splitting is heuristic.

2. Convert and inspect structure:
   - `pandoc input.epub -o /tmp/{slug}.md --extract-media=/tmp/{slug}-media`
   - For EPUBs, read `nav.xhtml` (EPUB3) or `toc.ncx` (EPUB2) from inside
     the `.epub` (it is a zip) to get the authoritative TOC.
   - Fall back to first-level headings if nav is absent or malformed.

3. For each chapter, locate its references — a `## References` /
   `## Bibliography` / `## Works Cited` section at the chapter end or in
   back matter. Parse `[N]`, `(Author Year)`, and footnote styles.

4. Pre-filter reference candidates: run `wiki(action="search", ...)` on
   each parsed reference and drop ones that already have a page.

5. Present the plan to the user and stop:
   - The parsed TOC (chapter number, title, page/section span)
   - Per-chapter concept count estimate given `scope`
   - The deduplicated reference list that would be stubbed under
     `scope: thorough` (with count)
   Ask via `AskUserQuestion`: proceed, adjust chapter splits, or abort.
   Do not continue until the user confirms.

## Ingest pass (after confirmation)

6. Search for an existing book page:
   `wiki(action="search", text="{book title}", filters={"resource_type": "book"})`

7. Read the style guide: `wiki(action="style", section="Resources")`

8. Check active projects:
   `wiki(action="search", filters={"type": "project", "status": "active"})`

9. Move the file:
   `wiki(action="move_file", source="...", bibtex_key="authorBookYear")`
   Place it under `knowledge/resources/{book-slug}/attachments/`.

10. Create the book landing page at
    `knowledge/resources/{book-slug}/{book-slug}.md` with:
    - Metadata: `resource_type: book`, authors, year, bibtex_key,
      `file: "[[{book-slug}/attachments/authorBookYear.epub]]"`
    - Body: one-sentence summary, key themes, `## Table of contents`
      with `[[{book-slug}/chapter-NN-{slug}|N. Chapter Title]]` per chapter
    - If projects exist, `## Relevance to our work` linking them; else
      `TODO — link to relevant projects when created.`
    - Provenance: the epub file + pandoc conversion

11. For each chapter, create
    `knowledge/resources/{book-slug}/chapter-NN-{slug}.md` with:
    - Metadata: `resource_type: book`,
      `parent_book: "[[{book-slug}/{book-slug}|Book Title]]"`,
      `chapter_number: N`, `chapter_title: "..."`,
      authors (inherit from book unless edited volume), `status: unread`
    - Body: one-paragraph summary, key claims, `## Concepts`, `## References`
    - Provenance: parent epub

12. Concept extraction per chapter, per `scope`:
    - `central`: 3-5 concepts → present via `AskUserQuestion` under
      `checked`, auto-create under `autonomous`
    - `thorough`: all warrant-their-own-page concepts
    - `appendix`: list under `## Concepts` in chapter body, skip stubs

13. References:
    - Write the parsed list verbatim into each chapter's `## References`
      section regardless of scope.
    - If `scope: thorough`: take the deduplicated, pre-filtered list from
      the plan pass. Under `approval: checked`, present it as ONE
      `AskUserQuestion` with `multiSelect: true` (not per-chapter). Create
      a `resource` stub for each selected entry with `status: unread`,
      inferred `resource_type`, authors, year, and provenance pointing at
      the parent book.
    - If `scope: central` or `appendix`: no stubs.

14. Ingest authors via `wiki(action="ingest_authors", resource="...")`
    on the book landing. Under `scope: thorough`, also run per chapter if
    a chapter's bylines differ.

15. Validate everything:
    - `wiki(action="validate", title="{book-slug}")`
    - Each chapter page
    - Each reference stub
    Report broken-link or schema errors before commit.

16. Ask the user for approval, then commit with an explicit file list:
    `wiki(action="commit",
          message="Ingest book: {title}",
          files=["knowledge/resources/{book-slug}/..."])`

$ARGUMENTS
