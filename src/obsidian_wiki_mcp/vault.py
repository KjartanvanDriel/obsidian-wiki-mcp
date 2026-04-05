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

from .models import HealthReport, ValidationError, WikiPage, strip_code
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
    ) -> dict:
        """Update a page's metadata, body, or both."""
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
        if body is not None:
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
                content = strip_code(path.read_text(encoding="utf-8"))
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

        all_outlinks: dict[str, list[str]] = {}
        all_inlinks: defaultdict[str, list[str]] = defaultdict(list)

        for p in pages:
            outlinks = p.outlinks()
            all_outlinks[p.title] = outlinks
            for link in outlinks:
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
        if "broken_links" in run_checks:
            for p in pages:
                for link in p.outlinks():
                    if not self._resolve_link(link, slug_index, title_index, alias_index):
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

    def commit(self, message: str) -> dict:
        """Stage all changes and commit, then append to the daily file."""
        try:
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
