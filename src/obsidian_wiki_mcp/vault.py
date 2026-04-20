"""Core vault operations — read, write, search, link analysis, health checks."""

from __future__ import annotations

import re
import shutil
import subprocess
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import frontmatter

from . import bibtex as bibtex_lib
from .models import HealthReport, ValidationError, WikiPage, normalize_wikilink_escapes, strip_code
from .schemas import SchemaRegistry


def slugify(title: str) -> str:
    """Convert a title to a kebab-case filename slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def _extract_link_display(wikilink: str) -> str:
    """Extract the display name from a wikilink.

    [[slug|Display Name]] → Display Name
    [[Display Name]] → Display Name
    Display Name → Display Name
    """
    text = wikilink.strip("[]")
    if "|" in text:
        return text.split("|", 1)[1]
    return text


class Vault:
    """Stateless operations on an Obsidian vault."""

    def __init__(self, vault_path: Path, schemas: SchemaRegistry):
        self.root = vault_path
        self.schemas = schemas

    # ── Reading ────────────────────────────────────────────────────────

    def _parse_page(self, path: Path) -> WikiPage | None:
        """Parse a single .md file into a WikiPage."""
        try:
            post = frontmatter.load(str(path))
        except Exception:
            return None

        metadata = dict(post.metadata)
        page_type = metadata.get("type", "unknown")
        title = metadata.get("title", path.stem.replace("-", " ").title())
        created = metadata.get("created", None)

        return WikiPage(
            title=title,
            path=path.relative_to(self.root),
            page_type=page_type,
            metadata=metadata,
            body=post.content,
            created=created,
        )

    def _all_md_files(self) -> list[Path]:
        """Get all markdown files in the vault, excluding _ prefixed dirs that aren't pages."""
        files = []
        # Non-wiki files/dirs to skip
        skip_dirs = {".claude", ".obsidian", ".git", "node_modules", "daily", "to_ingest", "attachments", "threads"}
        skip_files = {"CLAUDE.md", "README.md", "TODO.md", "todos.md", "Landing.md"}
        for p in self.root.rglob("*.md"):
            rel = p.relative_to(self.root)
            parts = rel.parts
            # Skip dot-prefixed dirs, underscore-prefixed dirs, and known non-wiki dirs
            if any(part in skip_dirs or (part.startswith(".")) for part in parts[:-1]):
                continue
            if any(part.startswith("_") for part in parts[:-1]):
                continue
            # Skip known non-wiki files (anywhere in vault)
            if p.name in skip_files:
                continue
            if p.name.startswith("_"):
                continue
            files.append(p)
        return sorted(files)

    def _all_pages(self) -> list[WikiPage]:
        """Parse all pages in the vault."""
        pages = []
        for path in self._all_md_files():
            page = self._parse_page(path)
            if page:
                pages.append(page)
        return pages

    def _title_to_path(self, title: str) -> Path | None:
        """Find a page by title (case-insensitive) or alias."""
        title_lower = title.lower().strip()
        slug = slugify(title)

        for path in self._all_md_files():
            # Check filename match
            if path.stem.lower() == slug or path.stem.lower() == title_lower:
                return path
            # Check title in frontmatter
            page = self._parse_page(path)
            if page and page.title.lower() == title_lower:
                return path
            # Check aliases
            if page and title_lower in [a.lower() for a in page.aliases]:
                return path
        return None

    # ── CRUD ──────────────────────────────────────────────────────────

    def read_page(self, title: str) -> dict:
        """Read a page by title. Returns parsed metadata + body + backlink count."""
        path = self._title_to_path(title)
        if not path:
            return {"error": f"Page not found: {title}"}

        page = self._parse_page(path)
        if not page:
            return {"error": f"Could not parse page: {title}"}

        # Count backlinks
        backlinks = self._find_backlinks(page.title)

        return {
            "title": page.title,
            "path": str(page.path),
            "type": page.page_type,
            "metadata": page.metadata,
            "body": page.body,
            "backlink_count": len(backlinks),
            "backlinks": backlinks,
        }

    def create_page(
        self,
        page_type: str,
        title: str,
        metadata: dict[str, Any] | None = None,
        body: str = "",
        project: str | None = None,
    ) -> dict:
        """Create a new page with schema validation and duplicate checking."""
        # Check schema exists
        schema = self.schemas.get_schema(page_type)
        if not schema:
            return {"error": f"Unknown page type: {page_type}. Known types: {self.schemas.list_types()}"}

        # Check for duplicates (title and aliases)
        dup = self._check_duplicate(title, metadata.get("aliases", []) if metadata else [])
        if dup:
            return {"error": f"Duplicate detected: '{title}' conflicts with existing page '{dup}'"}

        # Build metadata
        full_metadata = self.schemas.get_default_metadata(page_type)
        full_metadata["title"] = title
        full_metadata["created"] = date.today().isoformat()
        if metadata:
            full_metadata.update(metadata)
        full_metadata["type"] = page_type  # Ensure type is always set

        # Add project reference for work-layer pages
        if project and "project" in schema.get("fields", {}):
            project_slug = slugify(project)
            full_metadata["project"] = f"[[{project_slug}/_project|{project}]]"

        # Determine file path
        file_path = self._resolve_path(page_type, title, project)

        # Validate before writing
        page = WikiPage(
            title=title,
            path=file_path,
            page_type=page_type,
            metadata=full_metadata,
            body=body,
        )
        errors = self.schemas.validate_page(page)
        real_errors = [e for e in errors if e.severity == "error"]
        if real_errors:
            return {
                "error": "Validation failed",
                "details": [{"field": e.field, "message": e.message} for e in real_errors],
            }

        # Write file
        self._write_page(file_path, full_metadata, body)

        return {
            "created": True,
            "title": title,
            "path": str(file_path),
            "type": page_type,
            "warnings": [{"field": e.field, "message": e.message} for e in errors if e.severity == "warning"],
        }

    def update_page(
        self,
        title: str,
        metadata: dict[str, Any] | None = None,
        body: str | None = None,
        append: bool = False,
        section: str | None = None,
        section_content: str | None = None,
    ) -> dict:
        """Update a page's metadata, body, or both. Supports section-level updates."""
        path = self._title_to_path(title)
        if not path:
            return {"error": f"Page not found: {title}"}

        page = self._parse_page(path)
        if not page:
            return {"error": f"Could not parse page: {title}"}

        # Merge metadata
        new_metadata = dict(page.metadata)
        if metadata:
            new_metadata.update(metadata)

        # Update body
        new_body = page.body
        if section is not None and (section_content is not None or (body is not None and append)):
            # Section-level update
            new_body = self._patch_section(
                page.body,
                section,
                section_content=section_content,
                append_text=body if append else None,
            )
            if new_body is None:
                return {"error": f"Section '{section}' not found in '{title}'"}
        elif body is not None:
            if append:
                new_body = page.body + "\n\n" + body
            else:
                new_body = body

        # Validate
        updated_page = WikiPage(
            title=page.title,
            path=page.path,
            page_type=page.page_type,
            metadata=new_metadata,
            body=new_body,
        )
        errors = self.schemas.validate_page(updated_page)
        real_errors = [e for e in errors if e.severity == "error"]
        if real_errors:
            return {
                "error": "Validation failed",
                "details": [{"field": e.field, "message": e.message} for e in real_errors],
            }

        # Write
        abs_path = self.root / page.path
        self._write_page(abs_path, new_metadata, new_body)

        return {
            "updated": True,
            "title": page.title,
            "path": str(page.path),
            "warnings": [{"field": e.field, "message": e.message} for e in errors if e.severity == "warning"],
        }

    # ── Search ────────────────────────────────────────────────────────

    def search(
        self,
        text: str | None = None,
        filters: dict[str, Any] | None = None,
        sort: str | None = None,
        limit: int = 20,
    ) -> dict:
        """Unified search — full-text and/or metadata filters."""
        limit = min(limit, 100)
        pages = self._all_pages()
        results = []

        for page in pages:
            # Apply metadata filters
            if filters:
                if not self._matches_filters(page, filters):
                    continue

            # Apply text search
            if text:
                text_lower = text.lower()
                if (
                    text_lower not in page.title.lower()
                    and text_lower not in page.body.lower()
                    and not any(text_lower in str(v).lower() for v in page.metadata.values())
                ):
                    continue

            results.append({
                "title": page.title,
                "path": str(page.path),
                "type": page.page_type,
                "status": page.status,
                "tags": page.tags,
                "created": str(page.created) if page.created else None,
            })

        # Sort
        if sort:
            reverse = sort.startswith("-")
            sort_key = sort.lstrip("-")
            results.sort(key=lambda r: r.get(sort_key, ""), reverse=reverse)

        return {
            "count": len(results),
            "results": results[:limit],
        }

    def _matches_filters(self, page: WikiPage, filters: dict[str, Any]) -> bool:
        """Check if a page matches all metadata filters."""
        for key, value in filters.items():
            if key == "type":
                if page.page_type != value:
                    return False
            elif key == "tags":
                # Support both exact match and prefix match
                if isinstance(value, str):
                    value = [value]
                page_tags = page.tags
                if not any(
                    any(pt == t or pt.startswith(t + "/") for pt in page_tags)
                    for t in value
                ):
                    return False
            elif key == "project":
                page_project = page.metadata.get("project", "")
                # Normalize wikilink comparison — handle [[slug|Name]] and [[Name]] formats
                clean_filter = _extract_link_display(value)
                clean_page = _extract_link_display(page_project) if isinstance(page_project, str) else ""
                if clean_filter.lower() != clean_page.lower():
                    return False
            else:
                page_value = page.metadata.get(key)
                if page_value != value:
                    return False
        return True

    # ── Links ─────────────────────────────────────────────────────────

    def get_links(self, title: str, direction: str = "both") -> dict:
        """Get backlinks, outlinks, or both for a page."""
        path = self._title_to_path(title)
        if not path:
            return {"error": f"Page not found: {title}"}

        page = self._parse_page(path)
        if not page:
            return {"error": f"Could not parse page: {title}"}

        result: dict[str, Any] = {"title": page.title}

        if direction in ("out", "both"):
            result["outlinks"] = page.outlinks()

        if direction in ("in", "both"):
            result["backlinks"] = self._find_backlinks(page.title)

        return result

    def _find_backlinks(self, title: str) -> list[str]:
        """Find all pages that link to the given title or its slug."""
        backlinks = []
        slug = slugify(title)

        # Match [[title...]], [[slug...]], or [[path/slug...]]
        # Build patterns for both title-based and slug-based links
        patterns = [
            re.compile(r"\[\[" + re.escape(title) + r"(\|[^\]]*)?\]\]", re.IGNORECASE),
            re.compile(r"\[\[([^\]|]*/)?""" + re.escape(slug) + r"(\|[^\]]*)?\]\]", re.IGNORECASE),
        ]

        for path in self._all_md_files():
            try:
                content = normalize_wikilink_escapes(strip_code(path.read_text(encoding="utf-8")))
            except Exception:
                continue
            if any(p.search(content) for p in patterns):
                page = self._parse_page(path)
                if page and page.title.lower() != title.lower():
                    backlinks.append(page.title)

        return sorted(backlinks)

    # ── Validation ────────────────────────────────────────────────────

    def validate(self, title: str | None = None) -> dict:
        """Validate one page or the entire vault."""
        if title:
            path = self._title_to_path(title)
            if not path:
                return {"error": f"Page not found: {title}"}
            page = self._parse_page(path)
            if not page:
                return {"error": f"Could not parse page: {title}"}
            errors = self.schemas.validate_page(page)
            return {
                "page": page.title,
                "valid": len([e for e in errors if e.severity == "error"]) == 0,
                "errors": [{"field": e.field, "message": e.message, "severity": e.severity} for e in errors],
            }

        # Validate entire vault
        all_errors: list[dict] = []
        pages = self._all_pages()
        for page in pages:
            errors = self.schemas.validate_page(page)
            if errors:
                for e in errors:
                    all_errors.append({
                        "page": page.title,
                        "field": e.field,
                        "message": e.message,
                        "severity": e.severity,
                    })

        error_count = len([e for e in all_errors if e["severity"] == "error"])
        warning_count = len([e for e in all_errors if e["severity"] == "warning"])

        return {
            "pages_checked": len(pages),
            "error_count": error_count,
            "warning_count": warning_count,
            "issues": all_errors,
        }

    # ── Health ────────────────────────────────────────────────────────

    def _resolve_link(self, link: str, slug_index: dict[str, str], title_index: dict[str, str], alias_index: dict[str, str]) -> str | None:
        """Resolve a wikilink to a page title by checking slug, title, and alias indices.

        Returns the page title if found, None otherwise.
        """
        link_lower = link.lower()
        # Check by slug path (e.g. "some-project/_project" or "my-concept")
        if link_lower in slug_index:
            return slug_index[link_lower]
        # Check the final path component as a slug (e.g. "my-project/_project" → "_project")
        link_stem = Path(link).stem.lower()
        if link_stem in slug_index:
            return slug_index[link_stem]
        # Check by title
        if link_lower in title_index:
            return title_index[link_lower]
        # Check by alias
        if link_lower in alias_index:
            return alias_index[link_lower]
        return None

    def _thread_link_set(self) -> set[str]:
        """Build a set of valid wikilink forms pointing into `threads/` folders.

        Threads are excluded from MCP indexing (see `_all_md_files`), but wiki
        pages legitimately link to thread landing pages and session notes via
        `[[thread-slug/file-stem]]`. Without this helper the broken-link
        checker would flag every such link as broken.

        We record both `{thread-slug}/{file-stem}` (the common form) and
        bare `{file-stem}` (fallback) in lowercase.
        """
        links: set[str] = set()
        for thread_dir in self.root.rglob("threads"):
            if not thread_dir.is_dir():
                continue
            for md in thread_dir.rglob("*.md"):
                # Only count files directly under a specific thread folder
                # (threads/{thread-slug}/{file}.md), not under threads/ itself.
                try:
                    rel = md.relative_to(thread_dir)
                except ValueError:
                    continue
                parts = rel.parts
                if len(parts) != 2:
                    continue
                thread_slug, fname = parts[0], parts[1]
                stem = Path(fname).stem
                links.add(f"{thread_slug}/{stem}".lower())
                links.add(stem.lower())
        return links

    def health(self, checks: list[str] | None = None) -> dict:
        """Run vault health checks."""
        all_checks = {"orphans", "stubs", "broken_links", "validation", "duplicates"}
        run_checks = set(checks) if checks else all_checks

        pages = self._all_pages()
        report = HealthReport()

        # Build indices: title, alias, and slug (relative path without .md)
        title_index = {p.title.lower(): p.title for p in pages}
        alias_index: dict[str, str] = {}
        slug_index: dict[str, str] = {}
        for p in pages:
            for alias in p.aliases:
                alias_index[alias.lower()] = p.title
            # Index by relative path without extension (how outlinks() returns slugs)
            rel_stem = str(p.path.with_suffix("")).lower()
            slug_index[rel_stem] = p.title
            # Also index by just the filename stem for simple [[slug]] links
            slug_index[p.path.stem.lower()] = p.title

        # Thread landing pages and session notes aren't in the MCP index but
        # are legitimate link targets.
        thread_links = self._thread_link_set()

        def _is_valid_link(link: str) -> bool:
            """True if `link` resolves to a real page or a known thread file.
            Intra-page anchor links (`#section`) are not checked."""
            if link.startswith("#"):
                return True
            if self._resolve_link(link, slug_index, title_index, alias_index):
                return True
            if link.lower() in thread_links:
                return True
            return False

        all_outlinks: dict[str, list[str]] = {}
        all_inlinks: defaultdict[str, list[str]] = defaultdict(list)

        for p in pages:
            outlinks = p.outlinks()
            all_outlinks[p.title] = outlinks
            for link in outlinks:
                if link.startswith("#"):
                    continue  # intra-page anchor, not a page reference
                resolved = self._resolve_link(link, slug_index, title_index, alias_index)
                if resolved:
                    all_inlinks[resolved.lower()].append(p.title)
                else:
                    all_inlinks[link.lower()].append(p.title)

        # Orphans: pages with no inbound links
        if "orphans" in run_checks:
            for p in pages:
                if p.title.lower() not in all_inlinks and p.page_type != "project":
                    # Project pages are roots, not orphans
                    report.orphans.append(p.title)

        # Stubs: pages with very little body content
        if "stubs" in run_checks:
            for p in pages:
                word_count = len(p.body.split())
                if word_count < 50 and p.status != "stub":
                    report.stubs.append(p.title)

        # Broken links: [[links]] pointing to nonexistent pages
        # Thread-targeted links (e.g. [[thread-slug/thread-slug]]) resolve
        # against the filesystem thread-link set; anchor-only links are skipped.
        if "broken_links" in run_checks:
            for p in pages:
                for link in p.outlinks():
                    if not _is_valid_link(link):
                        report.broken_links.append({"from": p.title, "to": link})

        # Validation errors
        if "validation" in run_checks:
            for p in pages:
                errors = self.schemas.validate_page(p)
                report.validation_errors.extend(
                    e for e in errors if e.severity == "error"
                )

        # Duplicate suspects: pages with overlapping aliases or similar titles
        if "duplicates" in run_checks:
            seen_names: dict[str, str] = {}  # normalized name → page title
            for p in pages:
                names = [p.title] + p.aliases
                for name in names:
                    norm = name.lower().strip()
                    if norm in seen_names and seen_names[norm] != p.title:
                        report.duplicate_suspects.append({
                            "name": name,
                            "pages": [seen_names[norm], p.title],
                        })
                    seen_names[norm] = p.title

        return report.to_dict()

    # ── Project overview ──────────────────────────────────────────────

    def project_overview(self, title: str) -> dict:
        """Get a project overview with children, artifacts, and linked concepts."""
        path = self._title_to_path(title)
        if not path:
            return {"error": f"Project not found: {title}"}

        page = self._parse_page(path)
        if not page or page.page_type != "project":
            return {"error": f"'{title}' is not a project page"}

        # Find children (pages that reference this project)
        children: defaultdict[str, list[dict]] = defaultdict(list)
        all_pages = self._all_pages()

        for p in all_pages:
            project_ref = p.metadata.get("project", "")
            if isinstance(project_ref, str):
                clean = _extract_link_display(project_ref)
                if clean.lower() == title.lower():
                    children[p.page_type].append({
                        "title": p.title,
                        "status": p.status,
                        "path": str(p.path),
                    })

        # Also find sub-projects
        for p in all_pages:
            parent = p.metadata.get("parent_project", "")
            if isinstance(parent, str):
                clean = _extract_link_display(parent)
                if clean.lower() == title.lower() and p.page_type == "project":
                    children["sub_project"].append({
                        "title": p.title,
                        "status": p.status,
                        "path": str(p.path),
                    })

        # Find linked knowledge pages (concepts/tools referenced by project pages)
        linked_concepts = set()
        for type_pages in children.values():
            for child_info in type_pages:
                child_path = self.root / child_info["path"]
                child_page = self._parse_page(child_path)
                if child_page:
                    for link in child_page.outlinks():
                        link_path = self._title_to_path(link)
                        if link_path:
                            linked_page = self._parse_page(link_path)
                            if linked_page and linked_page.page_type in ("concept", "tool", "resource"):
                                linked_concepts.add(link)

        return {
            "title": page.title,
            "goal": page.metadata.get("goal", ""),
            "status": page.status,
            "tags": page.tags,
            "artifacts": page.metadata.get("artifacts", []),
            "children": {k: v for k, v in children.items()},
            "children_summary": {k: len(v) for k, v in children.items()},
            "linked_knowledge": sorted(linked_concepts),
        }

    # ── Provenance ────────────────────────────────────────────────────

    def get_provenance(self, title: str) -> dict:
        """Get sources used to generate a page."""
        path = self._title_to_path(title)
        if not path:
            return {"error": f"Page not found: {title}"}
        page = self._parse_page(path)
        if not page:
            return {"error": f"Could not parse page: {title}"}
        return {
            "title": page.title,
            "sources_used": page.metadata.get("sources_used", []),
        }

    def set_provenance(self, title: str, sources: list[dict]) -> dict:
        """Set sources used to generate a page."""
        return self.update_page(title, metadata={"sources_used": sources})

    # ── Git ───────────────────────────────────────────────────────────

    def commit(self, message: str, files: list[str] | None = None) -> dict:
        """Stage specified files (or all) and commit, then append to the daily file."""
        try:
            if files:
                subprocess.run(["git", "add", "--"] + files, cwd=self.root, check=True, capture_output=True)
            else:
                subprocess.run(["git", "add", "-A"], cwd=self.root, check=True, capture_output=True)
            result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=self.root,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                # Get commit hash and changed files
                hash_result = subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    cwd=self.root, capture_output=True, text=True,
                )
                commit_hash = hash_result.stdout.strip()

                diff_result = subprocess.run(
                    ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
                    cwd=self.root, capture_output=True, text=True,
                )
                changed_files = [f for f in diff_result.stdout.strip().split("\n") if f]

                self._append_to_daily(commit_hash, message, changed_files)

                return {"committed": True, "message": message, "output": result.stdout.strip()}
            elif result.returncode == 1 and not result.stderr.strip():
                # Nothing to commit — git returns 1 with no stderr
                return {"committed": False, "message": "Nothing to commit"}
            elif "nothing to commit" in result.stdout or "nichts zu committen" in result.stdout:
                return {"committed": False, "message": "Nothing to commit"}
            else:
                return {"error": result.stderr.strip()}
        except FileNotFoundError:
            return {"error": "Git not found. Is git installed?"}
        except subprocess.CalledProcessError as e:
            return {"error": str(e)}

    def _append_to_daily(self, commit_hash: str, message: str, changed_files: list[str]) -> None:
        """Append a commit entry to today's daily file, grouped by project."""
        today = date.today().isoformat()
        daily_dir = self.root / "work" / "daily"
        daily_dir.mkdir(parents=True, exist_ok=True)
        daily_path = daily_dir / f"{today}.md"

        # Group changed files by project
        projects: dict[str, list[str]] = defaultdict(list)
        for f in changed_files:
            parts = Path(f).parts
            if len(parts) >= 3 and parts[0] == "work" and parts[1] == "projects":
                project_name = parts[2].replace("-", " ").title()
                projects[project_name].append(f)
            else:
                projects["General"].append(f)

        # Read or create daily file
        if daily_path.exists():
            content = daily_path.read_text(encoding="utf-8")
        else:
            content = f"# {today}\n"

        # Ensure ## Commits section exists
        if "## Commits" not in content:
            content = content.rstrip() + "\n\n## Commits\n"

        # Append entry under each project heading
        lines = content.split("\n")
        for project_name in sorted(projects.keys()):
            heading = f"### {project_name}"
            entry = f"- {commit_hash}: {message}"

            # Find existing project heading under ## Commits
            commits_idx = None
            heading_idx = None
            for i, line in enumerate(lines):
                if line.strip() == "## Commits":
                    commits_idx = i
                if commits_idx is not None and line.strip() == heading:
                    heading_idx = i
                    break

            if heading_idx is not None:
                # Find insertion point (after last list item under this heading)
                insert_at = heading_idx + 1
                while insert_at < len(lines) and (
                    lines[insert_at].startswith("- ") or lines[insert_at].strip() == ""
                ):
                    insert_at += 1
                # Insert before the next heading or end
                if insert_at > heading_idx + 1 and lines[insert_at - 1].strip() == "":
                    insert_at -= 1
                lines.insert(insert_at, entry)
            else:
                # Add new project heading at end
                lines.append(f"\n{heading}\n")
                lines.append(entry)

        daily_path.write_text("\n".join(lines), encoding="utf-8")

    # ── File management ────────────────────────────────────────────────

    def move_file(
        self, source: str, destination: str | None = None, bibtex_key: str | None = None
    ) -> dict:
        """Move/rename a file to the attachments folder, optionally with BibTeX-key naming."""
        source_path = (self.root / source).resolve()
        try:
            source_path.relative_to(self.root.resolve())
        except ValueError:
            return {"error": "Source path is outside the vault"}
        if not source_path.exists():
            return {"error": f"Source file not found: {source}"}

        # Determine destination
        if destination:
            dest_path = (self.root / destination).resolve()
            try:
                dest_path.relative_to(self.root.resolve())
            except ValueError:
                return {"error": "Destination path is outside the vault"}
        else:
            dest_path = self.root / "knowledge" / "resources" / "attachments"

        dest_path.mkdir(parents=True, exist_ok=True)

        # Determine filename
        if bibtex_key:
            filename = bibtex_key + source_path.suffix
        else:
            filename = source_path.name

        final_path = dest_path / filename
        if final_path.exists():
            return {"error": f"Destination already exists: {final_path.relative_to(self.root)}"}

        shutil.move(str(source_path), str(final_path))

        return {
            "moved": True,
            "from": source,
            "to": str(final_path.relative_to(self.root)),
        }

    # ── Threads ───────────────────────────────────────────────────────

    def create_thread(self, project: str, title: str, description: str = "") -> dict:
        """Create a new research thread: folder, landing page, and index entry."""
        # Find the project
        project_path = self._title_to_path(project)
        if not project_path:
            return {"error": f"Project not found: {project}"}
        project_page = self._parse_page(project_path)
        if not project_page or project_page.page_type != "project":
            return {"error": f"'{project}' is not a project page"}

        project_dir = self.root / project_page.path.parent
        threads_dir = project_dir / "threads"
        thread_slug = slugify(title)

        # Check thread doesn't already exist
        thread_dir = threads_dir / thread_slug
        if thread_dir.exists():
            return {"error": f"Thread already exists: {thread_slug}"}

        # Ensure threads/index.md exists
        index_path = threads_dir / "index.md"
        if not index_path.exists():
            threads_dir.mkdir(parents=True, exist_ok=True)
            index_path.write_text("# Threads\n\n## Active\n\n## Resolved\n", encoding="utf-8")

        # Create thread folder and landing page
        thread_dir.mkdir(parents=True, exist_ok=True)
        landing = thread_dir / f"{thread_slug}.md"
        landing_content = f"# {title}\n\n**Status**: exploring\n**Opened**: {date.today().isoformat()}\n"
        if description:
            landing_content += f"\n{description}\n"
        landing.write_text(landing_content, encoding="utf-8")

        # Add entry to index.md under ## Active
        index_content = index_path.read_text(encoding="utf-8")
        lines = index_content.split("\n")
        summary = f" — {description}" if description else ""
        entry = f"- [[{thread_slug}/{thread_slug}|{thread_slug}]]{summary}"

        # Find ## Active and insert after it
        inserted = False
        for i, line in enumerate(lines):
            if line.strip() == "## Active":
                # Find the insertion point (after existing entries, before next heading or blank gap)
                insert_at = i + 1
                while insert_at < len(lines) and lines[insert_at].startswith("- "):
                    insert_at += 1
                # Skip one blank line if present
                if insert_at < len(lines) and lines[insert_at].strip() == "":
                    lines.insert(insert_at, entry)
                else:
                    lines.insert(insert_at, entry)
                inserted = True
                break

        if not inserted:
            # No ## Active found, append
            lines.append(f"\n## Active\n\n{entry}")

        index_path.write_text("\n".join(lines), encoding="utf-8")

        return {
            "created": True,
            "thread": thread_slug,
            "project": project_page.title,
            "path": str(thread_dir.relative_to(self.root)),
            "landing_page": str(landing.relative_to(self.root)),
        }

    # ── Threads audit ─────────────────────────────────────────────────

    _SESSION_NOTE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(-[a-z0-9-]+)?\.md$")
    _BARE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
    _STATUS_LINE_RE = re.compile(r"^\*\*Status\*\*\s*:", re.MULTILINE)
    _INDEX_ENTRY_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]")
    _LANDING_LINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]")

    def audit_threads(self) -> dict:
        """Walk every project's threads/ folder, return structured findings.

        Checks:
          - filename matches YYYY-MM-DD[-topic].md (errors on bad, warns on bare date)
          - landing page present, has H1 and **Status**: line
          - session notes have an H1
          - landing-page wikilinks to siblings resolve
          - every thread folder is listed in threads/index.md
          - every index.md entry points to an existing folder
        """
        findings: list[dict] = []
        threads_checked = 0

        projects_root = self.root / "work" / "projects"
        if not projects_root.exists():
            return {"findings": [], "summary": {"errors": 0, "warnings": 0, "info": 0, "threads_checked": 0}}

        for project_dir in sorted(projects_root.iterdir()):
            if not project_dir.is_dir():
                continue
            threads_dir = project_dir / "threads"
            if not threads_dir.exists():
                continue

            project_name = project_dir.name

            # Parse index.md entries — only bullet-list wikilinks of the
            # canonical form `- [[slug/slug|name]]` or `- [[slug|name]]`.
            # Anything else (prose mentions, path-style links to non-threads)
            # is ignored so we don't flag random cross-references as orphans.
            index_path = threads_dir / "index.md"
            index_slugs: set[str] = set()
            if index_path.exists():
                index_content = normalize_wikilink_escapes(index_path.read_text(encoding="utf-8"))
                for line in index_content.splitlines():
                    m = re.match(r"\s*-\s+\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]", line)
                    if not m:
                        continue
                    target = m.group(1)
                    parts = target.split("/")
                    if len(parts) == 1:
                        index_slugs.add(parts[0].lower())
                    elif len(parts) == 2 and parts[0] == parts[1]:
                        # Canonical "slug/slug" form
                        index_slugs.add(parts[0].lower())
                    # Paths with more segments (e.g. `work/projects/...`) are
                    # cross-references, not thread entries; skip.

            # Thread folders on disk
            disk_slugs: set[str] = set()
            for entry in sorted(threads_dir.iterdir()):
                if entry.is_dir():
                    disk_slugs.add(entry.name.lower())
                    threads_checked += 1
                    self._audit_single_thread(entry, project_name, findings)

            # orphan_folder: thread folder exists but not in index
            for slug in sorted(disk_slugs - index_slugs):
                findings.append({
                    "project": project_name,
                    "thread": slug,
                    "kind": "orphan_folder",
                    "severity": "error",
                    "path": str((threads_dir / slug).relative_to(self.root)),
                    "detail": f"Thread folder '{slug}' exists but isn't listed in threads/index.md.",
                })

            # index_missing_folder: index references a slug whose folder doesn't exist
            for slug in sorted(index_slugs - disk_slugs):
                findings.append({
                    "project": project_name,
                    "thread": slug,
                    "kind": "index_missing_folder",
                    "severity": "error",
                    "path": str(index_path.relative_to(self.root)),
                    "detail": f"threads/index.md references '{slug}' but no matching folder exists.",
                })

        errors = sum(1 for f in findings if f["severity"] == "error")
        warnings = sum(1 for f in findings if f["severity"] == "warning")
        info = sum(1 for f in findings if f["severity"] == "info")
        return {
            "findings": findings,
            "summary": {
                "errors": errors,
                "warnings": warnings,
                "info": info,
                "threads_checked": threads_checked,
            },
        }

    def _audit_single_thread(self, thread_dir: Path, project: str, findings: list[dict]) -> None:
        """Check one thread folder's files; append findings in place."""
        thread_slug = thread_dir.name
        landing_name = f"{thread_slug}.md"
        landing_path = thread_dir / landing_name

        # Collect md files directly inside the thread folder
        md_files: list[Path] = []
        for entry in sorted(thread_dir.iterdir()):
            if entry.is_file() and entry.suffix == ".md":
                md_files.append(entry)
        file_stems = {p.stem for p in md_files}

        # landing_missing
        if not landing_path.exists():
            findings.append({
                "project": project,
                "thread": thread_slug,
                "kind": "landing_missing",
                "severity": "error",
                "path": str(thread_dir.relative_to(self.root)),
                "detail": f"Thread folder is missing its landing page ({landing_name}).",
            })

        for f in md_files:
            name = f.name
            is_landing = name == landing_name
            is_index = name == "index.md"

            if is_landing:
                self._audit_landing_page(f, project, thread_slug, file_stems, findings)
                continue
            if is_index:
                # index.md inside a specific thread folder is unusual but tolerated.
                continue

            # Session note checks
            if not self._SESSION_NOTE_RE.match(name):
                findings.append({
                    "project": project,
                    "thread": thread_slug,
                    "kind": "filename_bad",
                    "severity": "error",
                    "path": str(f.relative_to(self.root)),
                    "detail": "Filename doesn't match YYYY-MM-DD[-topic].md (lowercase, kebab).",
                })
                continue

            if self._BARE_DATE_RE.match(name):
                findings.append({
                    "project": project,
                    "thread": thread_slug,
                    "kind": "filename_bare_date",
                    "severity": "warning",
                    "path": str(f.relative_to(self.root)),
                    "detail": "Session note is a bare date; consider adding a topic suffix.",
                })

            # session_missing_h1
            try:
                first_nonempty = next(
                    (line for line in f.read_text(encoding="utf-8").splitlines() if line.strip()),
                    "",
                )
            except Exception:
                first_nonempty = ""
            if not first_nonempty.startswith("# "):
                findings.append({
                    "project": project,
                    "thread": thread_slug,
                    "kind": "session_missing_h1",
                    "severity": "warning",
                    "path": str(f.relative_to(self.root)),
                    "detail": "Session note has no H1 on its first non-empty line.",
                })

    def _audit_landing_page(
        self,
        landing_path: Path,
        project: str,
        thread_slug: str,
        sibling_stems: set[str],
        findings: list[dict],
    ) -> None:
        """Check landing-page shape and sibling wikilink integrity."""
        try:
            content = landing_path.read_text(encoding="utf-8")
        except Exception:
            return

        # landing_missing_h1
        first_nonempty = next(
            (line for line in content.splitlines() if line.strip()),
            "",
        )
        # Frontmatter may be present; skip it.
        if first_nonempty == "---":
            # Strip frontmatter
            try:
                post = frontmatter.loads(content)
                body = post.content
            except Exception:
                body = content
            first_nonempty = next(
                (line for line in body.splitlines() if line.strip()),
                "",
            )
        else:
            body = content

        if not first_nonempty.startswith("# "):
            findings.append({
                "project": project,
                "thread": thread_slug,
                "kind": "landing_missing_h1",
                "severity": "error",
                "path": str(landing_path.relative_to(self.root)),
                "detail": "Thread landing page has no H1.",
            })

        # landing_missing_status
        if not self._STATUS_LINE_RE.search(body):
            findings.append({
                "project": project,
                "thread": thread_slug,
                "kind": "landing_missing_status",
                "severity": "warning",
                "path": str(landing_path.relative_to(self.root)),
                "detail": "Landing page lacks a `**Status**:` line.",
            })

        # broken_sibling_link: links of the form [[YYYY-MM-DD...]] or [[thread-slug/...]]
        # that don't point at an existing sibling file.
        normalized = normalize_wikilink_escapes(strip_code(body))
        for m in self._LANDING_LINK_RE.finditer(normalized):
            target = m.group(1)
            # Resolve to the stem that should exist in this folder
            if "/" in target:
                prefix, _, suffix = target.partition("/")
                if prefix.lower() == thread_slug.lower():
                    stem = suffix
                else:
                    continue  # link to another thread, out of scope here
            elif self._SESSION_NOTE_RE.match(target + ".md") or self._BARE_DATE_RE.match(target + ".md"):
                stem = target
            else:
                continue  # not a sibling-style link
            if stem not in sibling_stems:
                findings.append({
                    "project": project,
                    "thread": thread_slug,
                    "kind": "broken_sibling_link",
                    "severity": "error",
                    "path": str(landing_path.relative_to(self.root)),
                    "detail": f"Wikilink [[{target}]] doesn't resolve to a sibling file in this thread.",
                })

    # ── People ingestion ──────────────────────────────────────────────

    def ingest_authors(
        self,
        resource: str,
        bibtex_key: str | None = None,
        confirmed_names: list[str] | None = None,
        extra_people: list[dict] | None = None,
    ) -> dict:
        """Populate person pages for authors of a resource.

        Two-phase by design:
          - Dry run (confirmed_names is None): returns existing matches and
            new candidates; caller decides which to create.
          - Commit (confirmed_names is a list): creates person stubs for the
            named new candidates, adds an "Authors:" line to the resource,
            and updates the resource's `authors` metadata field when present.

        `extra_people` lets callers inject non-BibTeX names (e.g. LLM-scanned
        body mentions under `scope=thorough`). Shape: [{"full": "Jane Doe",
        "aliases": ["J. Doe"], "role": "collaborator"}, ...]. Role defaults to
        "author" for BibTeX entries and "collaborator" for extras.
        """
        # Resolve resource
        path = self._title_to_path(resource)
        if not path:
            return {"error": f"Resource not found: {resource}"}
        page = self._parse_page(path)
        if not page:
            return {"error": f"Could not parse page: {resource}"}
        if page.page_type != "resource":
            return {"error": f"'{resource}' is not a resource page (type={page.page_type})"}

        # Determine BibTeX key
        key = bibtex_key or page.metadata.get("bibtex_key", "")
        candidates: list[dict[str, object]] = []

        if key:
            bib_path = self.root / "references.bib"
            parsed = bibtex_lib.extract_authors(bib_path, key)
            if parsed is None:
                return {"error": f"BibTeX entry not found: key='{key}' in {bib_path.name}"}
            for author in parsed:
                candidates.append({
                    "full": author["full"],
                    "aliases": list(author["aliases"]),
                    "role": "author",
                    "source": "bibtex",
                })

        # Append extra people (LLM-scanned or caller-supplied)
        for extra in extra_people or []:
            full = extra.get("full") or extra.get("name")
            if not full:
                continue
            candidates.append({
                "full": full,
                "aliases": list(extra.get("aliases", [])),
                "role": extra.get("role", "collaborator"),
                "source": extra.get("source", "manual"),
            })

        # Dedup: for each candidate, look up by full name and aliases. First hit
        # wins. Record both existing matches and fresh candidates.
        existing_matches: list[dict[str, str]] = []
        new_candidates: list[dict[str, object]] = []
        seen_full: set[str] = set()

        for cand in candidates:
            full = str(cand["full"]).strip()
            if not full or full.lower() in seen_full:
                continue
            seen_full.add(full.lower())

            match_title = self._resolve_person(full, list(cand["aliases"]))
            if match_title:
                existing_matches.append({"candidate": full, "page": match_title})
            else:
                new_candidates.append({
                    "full": full,
                    "aliases": cand["aliases"],
                    "role": cand["role"],
                    "source": cand["source"],
                })

        # Dry-run: return the dedup report
        if confirmed_names is None:
            return {
                "status": "pending",
                "resource": page.title,
                "bibtex_key": key or None,
                "existing_matches": existing_matches,
                "new_candidates": new_candidates,
            }

        # Commit phase: create confirmed new stubs
        created: list[dict[str, str]] = []
        skipped: list[dict[str, str]] = []
        name_to_cand = {c["full"]: c for c in new_candidates}

        for name in confirmed_names:
            cand = name_to_cand.get(name)
            if not cand:
                # May already exist (race) or caller typed an unknown name
                match = self._resolve_person(name, [])
                if match:
                    existing_matches.append({"candidate": name, "page": match})
                else:
                    skipped.append({"name": name, "reason": "not in proposed candidates"})
                continue

            stub_body = f"Author on [[{slugify(page.title)}|{page.title}]]. Stub."
            result = self.create_page(
                page_type="person",
                title=cand["full"],
                metadata={
                    "role": cand["role"],
                    "aliases": cand["aliases"],
                    "sources_used": [
                        {"type": "context", "ref": f"Ingested from {page.title}"}
                    ],
                },
                body=stub_body,
            )
            if result.get("created"):
                created.append({
                    "name": cand["full"],
                    "path": result["path"],
                })
            else:
                skipped.append({"name": cand["full"], "reason": result.get("error", "unknown")})

        # All people that should end up on the resource page (existing + newly created)
        linked_names: list[str] = [m["page"] for m in existing_matches]
        linked_names.extend(c["name"] for c in created)
        # De-duplicate while preserving order
        seen_link: set[str] = set()
        linked_unique: list[str] = []
        for n in linked_names:
            if n not in seen_link:
                seen_link.add(n)
                linked_unique.append(n)

        # Update resource body + metadata
        if linked_unique:
            self._apply_authors_to_resource(page, linked_unique)

        return {
            "status": "done",
            "resource": page.title,
            "created": created,
            "existing_matches": existing_matches,
            "linked": linked_unique,
            "skipped": skipped,
        }

    def _resolve_person(self, name: str, aliases: list[str]) -> str | None:
        """Return the title of an existing person page matching `name` or any
        alias, or None if no match. Only matches `type: person` pages."""
        candidates_to_try: list[str] = [name, *aliases]
        for candidate in candidates_to_try:
            if not candidate:
                continue
            path = self._title_to_path(candidate)
            if not path:
                continue
            existing = self._parse_page(path)
            if existing and existing.page_type == "person":
                return existing.title
        return None

    def _apply_authors_to_resource(self, page: WikiPage, names: list[str]) -> None:
        """Insert an 'Authors:' line below the H1 and update the `authors`
        metadata field. Idempotent: replaces an existing 'Authors:' line."""
        # Build the authors line
        author_links = ", ".join(
            f"[[{slugify(n)}|{n}]]" for n in names
        )
        authors_line = f"**Authors:** {author_links}"

        body = page.body
        lines = body.split("\n")

        # If an existing 'Authors:' line exists, replace it. Otherwise insert
        # just below the first H1.
        replaced = False
        for i, line in enumerate(lines):
            if line.strip().startswith("**Authors:**"):
                lines[i] = authors_line
                replaced = True
                break

        if not replaced:
            inserted = False
            for i, line in enumerate(lines):
                if line.startswith("# "):
                    # Insert a blank line + authors after H1
                    insertion = [""] if i + 1 >= len(lines) or lines[i + 1].strip() != "" else []
                    insertion.append(authors_line)
                    for off, new_line in enumerate(insertion):
                        lines.insert(i + 1 + off, new_line)
                    inserted = True
                    break
            if not inserted:
                # No H1 — prepend
                lines = [authors_line, ""] + lines

        new_body = "\n".join(lines)

        # Merge into metadata: resource.authors is a list of strings
        new_metadata = dict(page.metadata)
        if "authors" in new_metadata:
            new_metadata["authors"] = names

        abs_path = self.root / page.path
        self._write_page(abs_path, new_metadata, new_body)

    # ── Helpers ───────────────────────────────────────────────────────

    # ── Style Guide ───────────────────────────────────────────────────

    def _style_guide_path(self) -> Path:
        return self.root / "_wiki" / "style-guide.md"

    def get_style_guide(self, section: str | None = None) -> dict:
        """Read the style guide, optionally a specific section."""
        path = self._style_guide_path()
        if not path.exists():
            return {"error": "No style guide found. Create one at _wiki/style-guide.md or use style(mode='init') to create the default."}

        content = path.read_text(encoding="utf-8")

        if section:
            # Extract a section by heading
            lines = content.split("\n")
            in_section = False
            section_lines = []
            section_level = 0

            for line in lines:
                if line.startswith("#") and section.lower() in line.lower():
                    in_section = True
                    section_level = len(line) - len(line.lstrip("#"))
                    section_lines.append(line)
                    continue
                if in_section:
                    if line.startswith("#"):
                        current_level = len(line) - len(line.lstrip("#"))
                        if current_level <= section_level:
                            break  # Hit a same-level or higher heading
                    section_lines.append(line)

            if section_lines:
                return {"section": section, "content": "\n".join(section_lines).strip()}
            return {"error": f"Section '{section}' not found in style guide."}

        return {"content": content}

    def update_style_guide(self, content: str | None = None, section: str | None = None, section_content: str | None = None) -> dict:
        """Update the style guide — full replace or patch a section."""
        path = self._style_guide_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        if content is not None:
            # Full replace
            path.write_text(content, encoding="utf-8")
            return {"updated": True, "mode": "full_replace"}

        if section and section_content is not None:
            # Patch a specific section
            if not path.exists():
                return {"error": "Style guide doesn't exist yet. Use full content or mode='init' first."}

            existing = path.read_text(encoding="utf-8")
            lines = existing.split("\n")
            new_lines = []
            in_section = False
            section_level = 0
            replaced = False

            for line in lines:
                if not in_section and line.startswith("#") and section.lower() in line.lower():
                    in_section = True
                    section_level = len(line) - len(line.lstrip("#"))
                    new_lines.append(line)
                    new_lines.append("")
                    new_lines.append(section_content.strip())
                    new_lines.append("")
                    replaced = True
                    continue
                if in_section:
                    if line.startswith("#"):
                        current_level = len(line) - len(line.lstrip("#"))
                        if current_level <= section_level:
                            in_section = False
                            new_lines.append(line)
                    # Skip old section content
                    continue
                new_lines.append(line)

            if not replaced:
                return {"error": f"Section '{section}' not found."}

            path.write_text("\n".join(new_lines), encoding="utf-8")
            return {"updated": True, "mode": "section_patch", "section": section}

        return {"error": "Provide either 'content' (full replace) or 'section' + 'section_content' (patch)."}

    def init_style_guide(self, default_content: str) -> dict:
        """Initialize the style guide with default content if it doesn't exist."""
        path = self._style_guide_path()
        if path.exists():
            return {"exists": True, "message": "Style guide already exists. Use mode='read' to view or mode='update' to change."}

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(default_content, encoding="utf-8")
        return {"created": True, "path": str(path.relative_to(self.root))}

    # ── Helpers (continued) ───────────────────────────────────────────

    def _patch_section(
        self,
        body: str,
        section: str,
        section_content: str | None = None,
        append_text: str | None = None,
    ) -> str | None:
        """Replace or append to a section in a markdown body. Returns None if section not found."""
        lines = body.split("\n")
        new_lines = []
        in_section = False
        section_level = 0
        found = False

        for line in lines:
            if not in_section and line.startswith("#") and section.lower() in line.lower():
                in_section = True
                section_level = len(line) - len(line.lstrip("#"))
                found = True
                new_lines.append(line)

                if section_content is not None:
                    # Replace section content
                    new_lines.append("")
                    new_lines.append(section_content.strip())
                    new_lines.append("")
                elif append_text is not None:
                    # Keep existing content, we'll append after it
                    pass
                continue

            if in_section:
                if line.startswith("#"):
                    current_level = len(line) - len(line.lstrip("#"))
                    if current_level <= section_level:
                        in_section = False
                        if append_text is not None:
                            # Append before the next heading
                            new_lines.append(append_text.strip())
                            new_lines.append("")
                        new_lines.append(line)
                        continue

                if section_content is not None:
                    # Skip old section content (already replaced)
                    continue
                else:
                    # Keep existing content (for append mode)
                    new_lines.append(line)
            else:
                new_lines.append(line)

        # If section was the last one, append at end
        if in_section and append_text is not None:
            new_lines.append(append_text.strip())
            new_lines.append("")

        if not found:
            return None
        return "\n".join(new_lines)

    def _check_duplicate(self, title: str, aliases: list[str]) -> str | None:
        """Check if a page with this title or any alias already exists."""
        names_to_check = [title] + aliases
        for page in self._all_pages():
            existing_names = [page.title] + page.aliases
            for new_name in names_to_check:
                for existing_name in existing_names:
                    if new_name.lower().strip() == existing_name.lower().strip():
                        return page.title
        return None

    def _resolve_path(self, page_type: str, title: str, project: str | None = None) -> Path:
        """Determine the file path for a new page based on type and project."""
        slug = slugify(title)
        folder_template = self.schemas.get_folder(page_type)

        if not folder_template:
            return self.root / f"{slug}.md"

        # Replace {slug} and {project_slug} placeholders
        folder = folder_template
        if "{slug}" in folder:
            folder = folder.replace("{slug}", slug)
        if "{project_slug}" in folder:
            project_slug = slugify(project) if project else "unscoped"
            folder = folder.replace("{project_slug}", project_slug)

        folder_path = self.root / folder
        folder_path.mkdir(parents=True, exist_ok=True)

        return folder_path / f"{slug}.md"

    def _write_page(self, path: Path, metadata: dict[str, Any], body: str) -> None:
        """Write a page to disk as markdown with YAML frontmatter."""
        if isinstance(path, Path) and not path.is_absolute():
            path = self.root / path

        path.parent.mkdir(parents=True, exist_ok=True)

        post = frontmatter.Post(body, **metadata)
        with open(path, "w", encoding="utf-8") as f:
            f.write(frontmatter.dumps(post))
