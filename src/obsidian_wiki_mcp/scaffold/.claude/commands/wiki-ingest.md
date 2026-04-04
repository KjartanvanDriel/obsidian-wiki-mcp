Ingest a resource (paper, article, dataset, book) into the wiki.

## Steps

1. Identify the resource from the user's input (URL, file, or description).
2. Search the wiki to check it doesn't already exist:
   `wiki(action="search", text="...")`
3. Read the style guide for resources:
   `wiki(action="style", section="Resources")`
4. Create a resource page with:
   - Full metadata: resource_type, authors, year, url, bibtex_key, tags
   - A body containing: one-sentence summary, key takeaways, relevance to our work
   - Provenance tracking what you used to generate the summary
5. Link to related concept pages. If key concepts don't exist yet, create stubs.
6. If the user provides a project, tag the resource with `used_in_projects` links and note which project page should reference it.
7. Validate, then commit.

If the user provides a raw file (PDF), read it first, then summarize. If only a URL, fetch and summarize.

$ARGUMENTS
