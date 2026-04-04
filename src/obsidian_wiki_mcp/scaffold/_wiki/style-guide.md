# Wiki Style Guide

> This is a living document. It governs how all wiki content is written — by human or LLM. When in doubt, refer here. When this guide is wrong, update it.

---

## Voice & Tone

**Write like a knowledgeable colleague explaining something at a whiteboard.** Not a textbook. Not a blog post. Not documentation for strangers. You're writing for someone who is technically capable but may not have context on this specific topic.

- **Direct.** Lead with the point. No throat-clearing ("In the field of computer science, it is well known that..."). Just say what it is.
- **Precise.** Use the correct term. Don't say "a bunch of" when you mean "a vector of." Don't say "fast" when you mean "O(log n)."
- **Concise.** Every sentence should earn its place. If a paragraph can be a sentence, make it a sentence. If a sentence can be cut, cut it.
- **Honest about uncertainty.** Say "likely," "appears to," "as of 2026" when appropriate. Never fake confidence. If something is a guess or inference, say so.
- **Present tense by default.** "FAISS uses product quantization" not "FAISS used product quantization" — unless it's genuinely historical.

### What we're NOT

- Not an encyclopedia. We don't need to be comprehensive — we need to be useful.
- Not a tutorial. We link to tutorials; we don't reproduce them.
- Not marketing. No superlatives ("the best," "incredibly powerful," "revolutionary").
- Not hedging everything. Don't pad with "it should be noted that" or "it is worth mentioning that." Just state it.

---

## Page Structure

Every page follows the same skeleton, adapted per type:

```
# {Title}

{One to three sentence summary — what is this and why does it matter to us?}

## {Main content sections}

{Varies by type — see below}

## See Also

{Links to related pages, if any}
```

### The opening summary is critical

The first lines under the title should give someone everything they need to decide whether to keep reading. Imagine someone scanning 20 pages in quick succession — the summary is all they'll read.

**Good:** "FAISS is a C++/Python library by Meta for efficient similarity search over dense vectors. We use it as the retrieval backend in the RAG Pipeline project."

**Bad:** "FAISS stands for Facebook AI Similarity Search. It was developed by Facebook AI Research and released as open source. It provides several types of indexes for searching..."

### Section headings

- Use `##` for top-level sections, `###` for subsections. Never use `#` in the body (that's the title).
- Keep headings short and scannable: "GPU Support" not "Information About GPU Support."
- Use sentence case: "How it works" not "How It Works."

---

## Content Standards Per Type

### Concepts

The goal is to explain *what it is* and *why we care* — not to be Wikipedia.

Structure:
```
# {Concept Name}

{What is it, in plain language? Why is it relevant to our work?}

## How it works

{Core mechanism or idea. Keep it to the level of detail we actually need.}

## Key properties

{What matters in practice — tradeoffs, limitations, assumptions.}

## Our usage

{How this concept shows up in our projects. Link to relevant experiments, decisions.
If no projects exist yet, use: TODO — link to relevant projects when created.}

## See Also
```

### Tools

Capture what it does, how we use it, and what we've learned.

Structure:
```
# {Tool Name}

{What it is and what we use it for. One to two sentences.}

## Key features

{The capabilities that matter to us — not a full feature list.}

## Setup & usage

{Brief notes on how we have it configured. Not a tutorial — link to official docs.}

## Gotchas

{Things we've learned the hard way. Version-specific issues. Workarounds.}

## See Also
```

### Resources (papers, datasets, etc.)

The page body is the *digested* version — what a colleague would want to know without reading the original.

Structure:
```
# {Resource Title}

{One sentence: what is this resource and what's the key takeaway?}

## Summary

{3-5 paragraph summary of the content. Focus on findings and implications, not methodology unless methodology is the point.}

## Key takeaways

{Bulleted list of the 3-5 most important points for our work.}

## Relevance to our work

{How this connects to our projects and concepts. Link liberally.
If no projects exist yet, use: TODO — link to relevant projects when created.}

## Notes

{Any caveats, critiques, or open questions.}
```

### Projects

Keep it high-level. The project page is a landing page, not the project itself.

Structure:
```
# {Project Name}

{What is this project and what's the goal? Two to three sentences.}

## Current status

{Brief narrative of where things stand. What's active, what's blocked.}

## Key decisions

{Link to decision pages with one-line summaries.}

## Open questions

{What we haven't figured out yet.}
```

### Experiments

Structure:
```
# {Experiment Title}

{One sentence: what are we testing?}

## Hypothesis

{What we expect to find and why.}

## Method

{What we did. Enough detail to reproduce, but link to code/notebooks for full details.}

## Results

{What we found. Be specific — numbers, comparisons, charts if useful.}

## Interpretation

{What this means. Did it confirm or refute the hypothesis? What do we do next?}
```

### Decisions

The most important section is *rationale*. Future-you needs to understand *why*, not just *what*.

Structure:
```
# {Decision Title}

{One sentence: what did we decide?}

## Context

{What situation prompted this decision?}

## Options considered

{Brief description of each alternative.}

## Decision

{What we chose and why. Be specific about the reasoning.}

## Consequences

{What this decision implies going forward. Any risks accepted.}
```

### Tasks

Keep it minimal. A task page only needs detail if the task is complex.

```
# {Task Title}

{What needs to be done? One to three sentences. Link to relevant context.}
```

### Notes (meetings, daily logs)

Structure:
```
# {Date} — {Topic or meeting name}

## Attendees / Context

{Who was there, or what prompted this note.}

## Key points

{What was discussed or decided. Bulleted is fine here.}

## Action items

{What needs to happen next. Link to tasks if created.}
```

---

## Linking Conventions

### Link format

**IMPORTANT: Always use `[[slug|Display Name]]` format.** Obsidian resolves links by filename, not by frontmatter title. The slug is the kebab-case filename without `.md`.

```
[[vector-similarity-search|Vector Similarity Search]]
[[faiss|FAISS]]
[[rag-pipeline|RAG Pipeline]]
```

Never use `[[Display Name]]` alone — it won't resolve because files are named in kebab-case.

For project pages (which use `_project.md`), link via the project folder name:
```
[[wiki-infrastructure/_project|Wiki Infrastructure]]
```

### When to create a link

- **Always link** the first mention of another wiki page in a body section.
- **Don't over-link.** If "FAISS" appears 12 times on a page, link it once (first mention). The reader gets it.
- **Link concepts, not common words.** Link `[[vector-similarity-search|Vector Similarity Search]]` but don't link "Python" unless we have a meaningful Tool page for it.

### When to create a new page

Create a new page when a concept, tool, or idea:
1. Is referenced from 2+ existing pages, or
2. Needs more than a sentence to explain, or
3. Has metadata worth tracking (status, tags, relations).

If it only needs a sentence, just explain it inline and move on.

### Link display names

Use the alias syntax when the display text should differ from the title:

```
We use [[vector-similarity-search|vector search]] for retrieval.
```

---

## Formatting Rules

### General

- Use standard Markdown. No HTML.
- One blank line between sections. No extra blank lines.
- No trailing whitespace.

### Math

- Use LaTeX notation for all math: `$inline$` for inline and `$$display$$` for display equations.
- Example inline: `The loss is $L = -\sum_i y_i \log \hat{y}_i$`
- Example display:
  ```
  $$
  \text{softmax}(x_i) = \frac{e^{x_i}}{\sum_j e^{x_j}}
  $$
  ```
- Obsidian renders LaTeX via MathJax. Use standard LaTeX commands.

### Lists

- Use `-` for unordered lists, `1.` for ordered lists.
- Use lists for 3+ parallel items. For 1-2 items, use prose.
- Keep list items parallel in structure (all sentences, or all fragments — don't mix).

### Code

- Inline code for `function_names`, `file_paths`, `variable_names`, and short commands.
- Code blocks with language tags for anything multi-line:
  ````
  ```python
  result = search(query, top_k=10)
  ```
  ````

### Emphasis

- **Bold** for terms being defined or key takeaways.
- *Italic* for emphasis within a sentence (use sparingly).
- Never use ALL CAPS for emphasis.

### Numbers and units

- Spell out numbers under 10 in prose: "three experiments" not "3 experiments."
- Use digits for technical values: "top-k=10", "128 dimensions", "0.95 cosine similarity."
- Always include units: "latency of 12ms" not "latency of 12."

---

## Naming Conventions

### Page titles

- **Concepts:** Noun phrase, title case. "Vector Similarity Search" not "vector-similarity-search" or "About Vector Similarity Search."
- **Tools:** Official name. "FAISS" not "Faiss" or "Facebook AI Similarity Search."
- **People:** Full name. "Alice Smith" not "Alice" or "Dr. Smith."
- **Projects:** Short descriptive name. "RAG Pipeline" not "The RAG Pipeline Project."
- **Experiments:** Descriptive of what's tested. "Chunking Strategy Comparison" not "Experiment 7."
- **Decisions:** "Why X Over Y" or "Choosing X for Y." "Why FAISS Over Pinecone" not "Database Decision."
- **Notes:** Date-first. "2026-04-03 Sync on Indexing" not "Meeting About Indexing."

### Tags

- Hierarchical, lowercase, slash-separated: `research/retrieval`, `software/backend`.
- Top-level categories: `research/`, `software/`, `infrastructure/`, `data/`, `meta/`.
- Be specific enough to be useful, general enough to reuse. `research/retrieval` is good. `research/retrieval/faiss-experiments-april` is too specific.

---

## Quality Expectations

### Every page should

- Have a clear, useful opening summary.
- Link to related pages where relevant.
- Have complete, valid frontmatter.
- Be honest about what's known vs. uncertain.

### A page is a "stub" if

- The body is under 50 words.
- It has a title and metadata but no real content.
- Stubs are fine as placeholders — mark them `status: stub` and they'll show up in health checks.

### A page is "draft" if

- It has substantive content but hasn't been reviewed by a human.
- All LLM-generated pages start as `draft` unless promoted.

### A page is "published" if

- A human has reviewed and approved the content.
- It's considered reliable for reference.

---

## LLM-Specific Guidelines

Since most content is generated by an LLM and curated by a human:

- **Don't hallucinate structure.** If you don't have enough information to fill a section, leave it out or mark it as "TODO" — don't fabricate plausible-sounding content.
- **Cite your sources.** Every generated page should have `sources_used` in its frontmatter. If you're working from a paper, link it. If you're working from conversation context, say so.
- **Prefer updating over creating.** Before creating a new page, search for existing pages that could be updated instead.
- **Respect existing content.** When updating a page, preserve what's there unless explicitly asked to replace it. Use `append` mode by default.
- **Ask when ambiguous.** If a page could be a Concept or a Tool, or could belong to multiple projects, ask rather than guess.
- **Don't editorialize.** State facts and analysis. Don't add "This is a fascinating development" or "Interestingly, the authors found..."
- **Match the existing style.** Read a few existing pages of the same type before writing a new one. Match their level of detail and structure.
