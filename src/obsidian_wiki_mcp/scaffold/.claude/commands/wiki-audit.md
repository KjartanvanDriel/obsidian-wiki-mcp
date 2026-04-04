Run a full wiki audit and present findings. Then offer to fix issues.

## Steps

1. Run `wiki(action="health")` to get the full report.
2. Run `wiki(action="validate")` for detailed schema errors.
3. Present a summary to the user grouped by severity:
   - **Errors**: validation failures, broken links
   - **Warnings**: orphan pages, stubs, suspected duplicates
4. For each category, offer concrete next steps:
   - Broken links → create stub pages or fix the link
   - Validation errors → fill in missing required fields
   - Orphans → link them from relevant pages or mark for deletion
   - Stubs → expand with content or mark as intentional stubs (`status: stub`)
   - Duplicates → merge or add aliases
5. Ask the user which issues to fix, then fix them.
6. Validate again after fixes, then commit.

$ARGUMENTS
