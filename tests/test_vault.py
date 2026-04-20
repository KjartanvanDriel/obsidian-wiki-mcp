"""Tests for vault operations — uses a temporary vault with real schemas."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from obsidian_wiki_mcp import bibtex
from obsidian_wiki_mcp.schemas import SchemaRegistry
from obsidian_wiki_mcp.models import strip_code
from obsidian_wiki_mcp.vault import Vault, slugify

SCAFFOLD_SCHEMAS = Path(__file__).parent.parent / "src" / "obsidian_wiki_mcp" / "scaffold" / "_schemas"


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    """Create a temporary vault with real schemas."""
    schemas_dir = tmp_path / "_schemas"
    shutil.copytree(SCAFFOLD_SCHEMAS, schemas_dir)
    schemas = SchemaRegistry(schemas_dir)
    return Vault(tmp_path, schemas)


# ── slugify ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Hello World", "hello-world"),
        ("  Spaces  ", "spaces"),
        ("CamelCase Title", "camelcase-title"),
        ("dots.and" + "'quotes", "dotsandquotes"),
        ("multiple   spaces", "multiple-spaces"),
        ("already-slugged", "already-slugged"),
    ],
)
def test_slugify(title: str, expected: str):
    assert slugify(title) == expected


# ── create / read ────────────────────────────────────────────────────


def test_create_and_read(vault: Vault):
    result = vault.create_page(
        page_type="concept",
        title="Test Concept",
        metadata={"status": "draft", "tags": ["test"]},
        body="Some content about the concept.",
    )
    assert result.get("created") is True
    assert result["title"] == "Test Concept"

    read = vault.read_page("Test Concept")
    assert read["title"] == "Test Concept"
    assert read["type"] == "concept"
    assert read["metadata"]["status"] == "draft"
    assert "Some content" in read["body"]


def test_create_unknown_type(vault: Vault):
    result = vault.create_page(page_type="nonexistent", title="Foo")
    assert "error" in result
    assert "Unknown page type" in result["error"]


def test_create_duplicate(vault: Vault):
    vault.create_page(page_type="concept", title="Dup", metadata={"status": "draft", "tags": ["x"]})
    result = vault.create_page(page_type="concept", title="Dup", metadata={"status": "draft", "tags": ["x"]})
    assert "error" in result
    assert "Duplicate" in result["error"]


def test_create_missing_required_field(vault: Vault):
    # tags is required and has no default — omitting it should fail validation
    result = vault.create_page(page_type="concept", title="No Tags", metadata={"status": "draft"})
    assert "error" in result


def test_read_not_found(vault: Vault):
    result = vault.read_page("Does Not Exist")
    assert "error" in result
    assert "not found" in result["error"].lower()


# ── file exclusion ───────────────────────────────────────────────────


def test_skip_files_excluded(vault: Vault):
    """threads/, todos.md, Landing.md, and attachments/ should not be indexed."""
    # Create files that should be skipped
    (vault.root / "Landing.md").write_text("# Landing\n")
    project_dir = vault.root / "work" / "projects" / "test-proj"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "todos.md").write_text("# TODOs\n")
    # threads/ is a directory, not a file
    threads_dir = project_dir / "threads" / "some-thread"
    threads_dir.mkdir(parents=True, exist_ok=True)
    (threads_dir / "2026-04-05.md").write_text("Session notes\n")
    (project_dir / "threads" / "index.md").write_text("# Threads\n")
    attachments = project_dir / "attachments"
    attachments.mkdir(parents=True, exist_ok=True)
    (attachments / "report.md").write_text("# Raw report\n")

    md_files = vault._all_md_files()
    names = [p.name for p in md_files]
    assert "todos.md" not in names
    assert "Landing.md" not in names
    assert "report.md" not in names
    assert "index.md" not in names
    assert "2026-04-05.md" not in names


# ── update ───────────────────────────────────────────────────────────


def test_update_metadata(vault: Vault):
    vault.create_page(page_type="concept", title="Updatable", metadata={"status": "stub", "tags": ["a"]})
    result = vault.update_page("Updatable", metadata={"status": "draft"})
    assert result.get("updated") is True

    read = vault.read_page("Updatable")
    assert read["metadata"]["status"] == "draft"


def test_update_body_append(vault: Vault):
    vault.create_page(page_type="concept", title="Appendable", metadata={"status": "draft", "tags": ["a"]}, body="First.")
    vault.update_page("Appendable", body="Second.", append=True)
    read = vault.read_page("Appendable")
    assert "First." in read["body"]
    assert "Second." in read["body"]


def test_update_body_replace(vault: Vault):
    vault.create_page(page_type="concept", title="Replaceable", metadata={"status": "draft", "tags": ["a"]}, body="Old body.")
    vault.update_page("Replaceable", body="New body.")
    read = vault.read_page("Replaceable")
    assert "New body." in read["body"]
    assert "Old body." not in read["body"]


def test_update_section_replace(vault: Vault):
    body = "# Intro\n\nSome intro.\n\n## Details\n\nOld details.\n\n## See Also\n\n- old link"
    vault.create_page(page_type="concept", title="Sectioned", metadata={"status": "draft", "tags": ["a"]}, body=body)
    result = vault.update_page("Sectioned", section="Details", section_content="New details here.")
    assert result.get("updated") is True
    read = vault.read_page("Sectioned")
    assert "New details here." in read["body"]
    assert "Old details." not in read["body"]
    # Other sections preserved
    assert "Some intro." in read["body"]
    assert "- old link" in read["body"]


def test_update_section_append(vault: Vault):
    body = "## Items\n\n- first\n- second\n\n## Footer\n\nEnd."
    vault.create_page(page_type="concept", title="Appendable Section", metadata={"status": "draft", "tags": ["a"]}, body=body)
    result = vault.update_page("Appendable Section", section="Items", body="- third", append=True)
    assert result.get("updated") is True
    read = vault.read_page("Appendable Section")
    assert "- first" in read["body"]
    assert "- second" in read["body"]
    assert "- third" in read["body"]
    assert "End." in read["body"]


def test_update_section_append_last(vault: Vault):
    """Append to the last section (no following heading)."""
    body = "## Notes\n\n- note one"
    vault.create_page(page_type="concept", title="Last Section", metadata={"status": "draft", "tags": ["a"]}, body=body)
    result = vault.update_page("Last Section", section="Notes", body="- note two", append=True)
    assert result.get("updated") is True
    read = vault.read_page("Last Section")
    assert "- note one" in read["body"]
    assert "- note two" in read["body"]


def test_update_section_not_found(vault: Vault):
    vault.create_page(page_type="concept", title="No Section", metadata={"status": "draft", "tags": ["a"]}, body="Just body.")
    result = vault.update_page("No Section", section="Missing", section_content="New stuff.")
    assert "error" in result
    assert "not found" in result["error"].lower()


def test_update_not_found(vault: Vault):
    result = vault.update_page("Ghost", metadata={"status": "draft"})
    assert "error" in result


# ── search ───────────────────────────────────────────────────────────


def test_search_by_text(vault: Vault):
    vault.create_page(page_type="concept", title="Alpha", metadata={"status": "draft", "tags": ["search"]}, body="unique-keyword-xyz")
    vault.create_page(page_type="concept", title="Beta", metadata={"status": "draft", "tags": ["search"]}, body="nothing special")
    result = vault.search(text="unique-keyword-xyz")
    assert result["count"] == 1
    assert result["results"][0]["title"] == "Alpha"


def test_search_by_filter(vault: Vault):
    vault.create_page(page_type="concept", title="Filtered", metadata={"status": "draft", "tags": ["infra"]})
    vault.create_page(page_type="tool", title="MyTool", metadata={"status": "draft", "tags": ["infra"]})
    result = vault.search(filters={"type": "tool"})
    assert all(r["type"] == "tool" for r in result["results"])


def test_search_limit_capped(vault: Vault):
    # Limit should be capped at 100
    result = vault.search(limit=999)
    # We can't easily test the cap directly, but the method shouldn't crash
    assert "count" in result


def test_search_sort(vault: Vault):
    vault.create_page(page_type="concept", title="Zebra", metadata={"status": "draft", "tags": ["sort"]})
    vault.create_page(page_type="concept", title="Apple", metadata={"status": "draft", "tags": ["sort"]})
    result = vault.search(filters={"tags": "sort"}, sort="title")
    titles = [r["title"] for r in result["results"]]
    assert titles == ["Apple", "Zebra"]

    result_desc = vault.search(filters={"tags": "sort"}, sort="-title")
    titles_desc = [r["title"] for r in result_desc["results"]]
    assert titles_desc == ["Zebra", "Apple"]


def test_search_by_tag_prefix(vault: Vault):
    vault.create_page(page_type="concept", title="Deep Tag", metadata={"status": "draft", "tags": ["infra/ci"]})
    vault.create_page(page_type="concept", title="Other Tag", metadata={"status": "draft", "tags": ["research"]})
    result = vault.search(filters={"tags": "infra"})
    assert result["count"] == 1
    assert result["results"][0]["title"] == "Deep Tag"


def test_search_by_project_filter(vault: Vault):
    vault.create_page(page_type="project", title="FilterProj", metadata={"status": "active", "goal": "test", "tags": ["t"]})
    vault.create_page(
        page_type="decision", title="ProjDec",
        metadata={"status": "accepted", "project": "[[filter-proj|FilterProj]]", "date": "2026-01-01", "decision": "x", "rationale": "y", "tags": ["t"]},
    )
    vault.create_page(
        page_type="decision", title="OtherDec",
        metadata={"status": "accepted", "project": "[[other|Other]]", "date": "2026-01-01", "decision": "x", "rationale": "y", "tags": ["t"]},
    )
    result = vault.search(filters={"project": "FilterProj"})
    assert result["count"] == 1
    assert result["results"][0]["title"] == "ProjDec"


def test_search_no_results(vault: Vault):
    result = vault.search(text="absolutely-nothing-matches-this")
    assert result["count"] == 0
    assert result["results"] == []


# ── code stripping ───────────────────────────────────────────────────


def test_strip_code_removes_inline():
    assert "[[link]]" not in strip_code("see `[[link]]` here")
    assert "outside" in strip_code("outside `[[link]]` text")


def test_strip_code_removes_fenced_block():
    text = "before\n```\n[[inside-block]]\n```\nafter"
    result = strip_code(text)
    assert "inside-block" not in result
    assert "before" in result
    assert "after" in result


def test_outlinks_ignores_code(vault: Vault):
    vault.create_page(
        page_type="concept", title="Code Example",
        metadata={"status": "draft", "tags": ["test"]},
        body="Real link: [[real-target|Real]]. Code: `[[fake-target|Fake]]`.\n\n```\n[[block-target|Block]]\n```",
    )
    page = vault._parse_page(vault._title_to_path("Code Example"))
    links = page.outlinks()
    assert "real-target" in links
    assert "fake-target" not in links
    assert "block-target" not in links


def test_health_ignores_links_in_code(vault: Vault):
    """Wikilinks inside code blocks should not generate broken link reports."""
    vault.create_page(
        page_type="concept", title="Docs Page",
        metadata={"status": "draft", "tags": ["test"]},
        body="Example: `[[example-link|Example]]`.\n\n```\n[[code-link|Code]]\n```",
    )
    report = vault.health(checks=["broken_links"])
    broken_targets = [b["to"] for b in report["broken_links"]]
    assert "example-link" not in broken_targets
    assert "code-link" not in broken_targets


def test_backlinks_ignores_code(vault: Vault):
    """Backlinks should not be found from wikilinks inside code blocks."""
    vault.create_page(
        page_type="concept", title="Real Page",
        metadata={"status": "draft", "tags": ["test"]},
        body="Content.",
    )
    vault.create_page(
        page_type="concept", title="Code Ref",
        metadata={"status": "draft", "tags": ["test"]},
        body="Example: `[[real-page|Real Page]]`.",
    )
    backlinks = vault._find_backlinks("Real Page")
    assert "Code Ref" not in backlinks


# ── links and health (slug resolution) ───────────────────────────────


def test_outlinks_extracts_slug(vault: Vault):
    vault.create_page(
        page_type="concept",
        title="Linker",
        metadata={"status": "draft", "tags": ["test"]},
        body="See [[my-slug|Display Name]] and [[plain-link]].",
    )
    read = vault.read_page("Linker")
    page = vault._parse_page(vault._title_to_path("Linker"))
    links = page.outlinks()
    assert "my-slug" in links
    assert "plain-link" in links


def test_health_slug_links_not_broken(vault: Vault):
    """Links using [[slug|Display]] format should not be reported as broken."""
    vault.create_page(
        page_type="concept",
        title="Target Page",
        metadata={"status": "draft", "tags": ["test"]},
        body="I am the target.",
    )
    vault.create_page(
        page_type="concept",
        title="Source Page",
        metadata={"status": "draft", "tags": ["test"]},
        body="Link to [[target-page|Target Page]].",
    )
    report = vault.health(checks=["broken_links"])
    broken = [b for b in report["broken_links"] if b["to"] == "target-page"]
    assert len(broken) == 0, f"Slug link 'target-page' incorrectly reported as broken: {broken}"


def test_health_slug_links_not_orphan(vault: Vault):
    """Pages linked via slug should not be reported as orphans."""
    vault.create_page(
        page_type="concept",
        title="Linked Page",
        metadata={"status": "draft", "tags": ["test"]},
        body="Content.",
    )
    vault.create_page(
        page_type="concept",
        title="Referring Page",
        metadata={"status": "draft", "tags": ["test"]},
        body="See [[linked-page|Linked Page]].",
    )
    report = vault.health(checks=["orphans"])
    assert "Linked Page" not in report["orphans"], "Slug-linked page incorrectly reported as orphan"


def test_health_title_link_not_broken(vault: Vault):
    """Links using [[Title]] format (matching by title index) should not be broken."""
    vault.create_page(
        page_type="concept",
        title="Exact Title Match",
        metadata={"status": "draft", "tags": ["test"]},
        body="Content.",
    )
    vault.create_page(
        page_type="concept",
        title="Title Linker",
        metadata={"status": "draft", "tags": ["test"]},
        body="See [[Exact Title Match]].",
    )
    report = vault.health(checks=["broken_links"])
    broken_targets = [b["to"] for b in report["broken_links"]]
    assert "Exact Title Match" not in broken_targets


def test_health_title_link_not_orphan(vault: Vault):
    """Pages linked by title should not be orphans."""
    vault.create_page(
        page_type="concept",
        title="Title Target",
        metadata={"status": "draft", "tags": ["test"]},
        body="Content.",
    )
    vault.create_page(
        page_type="concept",
        title="Title Source",
        metadata={"status": "draft", "tags": ["test"]},
        body="See [[Title Target]].",
    )
    report = vault.health(checks=["orphans"])
    assert "Title Target" not in report["orphans"]


def test_health_alias_link_not_broken(vault: Vault):
    """Links matching an alias should not be reported as broken."""
    vault.create_page(
        page_type="concept",
        title="Full Name Page",
        metadata={"status": "draft", "tags": ["test"], "aliases": ["FNP"]},
        body="Content.",
    )
    vault.create_page(
        page_type="concept",
        title="Alias Linker",
        metadata={"status": "draft", "tags": ["test"]},
        body="See [[FNP]].",
    )
    report = vault.health(checks=["broken_links"])
    broken_targets = [b["to"] for b in report["broken_links"]]
    assert "FNP" not in broken_targets


def test_health_alias_link_not_orphan(vault: Vault):
    """Pages linked via alias should not be orphans."""
    vault.create_page(
        page_type="concept",
        title="Alias Target",
        metadata={"status": "draft", "tags": ["test"], "aliases": ["AT"]},
        body="Content.",
    )
    vault.create_page(
        page_type="concept",
        title="Alias Source",
        metadata={"status": "draft", "tags": ["test"]},
        body="See [[AT]].",
    )
    report = vault.health(checks=["orphans"])
    assert "Alias Target" not in report["orphans"]


def test_health_all_checks_no_crash(vault: Vault):
    """Running all health checks together should not crash."""
    vault.create_page(
        page_type="concept",
        title="Page A",
        metadata={"status": "draft", "tags": ["test"]},
        body="Link to [[page-b|Page B]] and [[Page A]] and [[NonExistent]].",
    )
    vault.create_page(
        page_type="concept",
        title="Page B",
        metadata={"status": "draft", "tags": ["test"], "aliases": ["PB"]},
        body="Link to [[PB]] self-ref and [[page-a|Page A]].",
    )
    report = vault.health()  # all checks
    assert "orphans" in report
    assert "broken_links" in report
    assert "stubs" in report
    assert "validation_errors" in report
    assert "duplicate_suspects" in report
    # Only NonExistent should be broken
    broken_targets = [b["to"] for b in report["broken_links"]]
    assert "NonExistent" in broken_targets
    assert "page-b" not in broken_targets
    assert "page-a" not in broken_targets
    assert "PB" not in broken_targets


def test_health_real_broken_link(vault: Vault):
    """A link to a genuinely nonexistent page should still be broken."""
    vault.create_page(
        page_type="concept",
        title="Lonely",
        metadata={"status": "draft", "tags": ["test"]},
        body="See [[does-not-exist|Ghost]].",
    )
    report = vault.health(checks=["broken_links"])
    assert any(b["to"] == "does-not-exist" for b in report["broken_links"])


def test_backlinks_found_by_slug(vault: Vault):
    """_find_backlinks should find links that use the slug format."""
    vault.create_page(
        page_type="concept",
        title="Backlink Target",
        metadata={"status": "draft", "tags": ["test"]},
        body="I exist.",
    )
    vault.create_page(
        page_type="concept",
        title="Backlink Source",
        metadata={"status": "draft", "tags": ["test"]},
        body="Ref: [[backlink-target|Backlink Target]].",
    )
    backlinks = vault._find_backlinks("Backlink Target")
    assert "Backlink Source" in backlinks


# ── validate ─────────────────────────────────────────────────────────


def test_validate_single_page(vault: Vault):
    vault.create_page(page_type="concept", title="Valid", metadata={"status": "draft", "tags": ["ok"]}, body="x")
    result = vault.validate("Valid")
    assert result["valid"] is True


def test_validate_vault(vault: Vault):
    vault.create_page(page_type="concept", title="V1", metadata={"status": "draft", "tags": ["ok"]})
    result = vault.validate()
    assert "pages_checked" in result


def test_validate_with_errors(vault: Vault):
    """A page with an invalid enum value should fail validation."""
    import frontmatter as fm
    bad_path = vault.root / "knowledge" / "concepts" / "bad.md"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    post = fm.Post("", type="concept", title="Bad", status="invalid-status", tags=["x"])
    bad_path.write_text(fm.dumps(post))
    result = vault.validate("Bad")
    assert result["valid"] is False
    assert any("invalid-status" in e["message"] for e in result["errors"])


def test_validate_not_found(vault: Vault):
    result = vault.validate("Ghost")
    assert "error" in result


# ── move_file path traversal ─────────────────────────────────────────


def test_move_file_path_traversal_blocked(vault: Vault):
    # Create a file inside the vault
    (vault.root / "test.txt").write_text("hello")
    result = vault.move_file("../../../etc/passwd")
    assert "error" in result
    assert "outside" in result["error"].lower()


def test_move_file_dest_traversal_blocked(vault: Vault):
    (vault.root / "test.txt").write_text("hello")
    result = vault.move_file("test.txt", destination="../../../tmp/evil")
    assert "error" in result
    assert "outside" in result["error"].lower()


def test_move_file_normal(vault: Vault):
    (vault.root / "moveme.pdf").write_text("pdf content")
    result = vault.move_file("moveme.pdf")
    assert result.get("moved") is True
    assert "attachments" in result["to"]


def test_move_file_bibtex_key(vault: Vault):
    (vault.root / "paper.pdf").write_text("pdf content")
    result = vault.move_file("paper.pdf", bibtex_key="smithML2025")
    assert result.get("moved") is True
    assert "smithML2025.pdf" in result["to"]


def test_move_file_dest_exists(vault: Vault):
    attachments = vault.root / "knowledge" / "resources" / "attachments"
    attachments.mkdir(parents=True, exist_ok=True)
    (attachments / "conflict.pdf").write_text("existing")
    (vault.root / "conflict.pdf").write_text("new")
    result = vault.move_file("conflict.pdf")
    assert "error" in result
    assert "exists" in result["error"].lower()


def test_move_file_not_found(vault: Vault):
    result = vault.move_file("nonexistent.pdf")
    assert "error" in result


# ── commit (with git) ────────────────────────────────────────────────


@pytest.fixture
def git_vault(vault: Vault) -> Vault:
    """A vault with git initialized."""
    import subprocess
    subprocess.run(["git", "init"], cwd=vault.root, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=vault.root, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=vault.root, capture_output=True, check=True)
    subprocess.run(["git", "add", "-A"], cwd=vault.root, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=vault.root, capture_output=True, check=True)
    return vault


def test_commit(git_vault: Vault):
    git_vault.create_page(page_type="concept", title="Committed", metadata={"status": "draft", "tags": ["t"]})
    result = git_vault.commit("Add committed page")
    assert result.get("committed") is True
    assert "Add committed page" in result["message"]


def test_commit_specific_files(git_vault: Vault):
    """Only specified files should be committed."""
    git_vault.create_page(page_type="concept", title="Included", metadata={"status": "draft", "tags": ["t"]})
    git_vault.create_page(page_type="concept", title="Excluded", metadata={"status": "draft", "tags": ["t"]})
    result = git_vault.commit("Selective commit", files=["knowledge/concepts/included.md"])
    assert result.get("committed") is True
    # Excluded should still be untracked
    import subprocess
    status = subprocess.run(["git", "status", "--porcelain"], cwd=git_vault.root, capture_output=True, text=True)
    assert "excluded.md" in status.stdout


def test_commit_nothing(git_vault: Vault):
    result = git_vault.commit("Empty commit")
    assert result.get("committed") is False


# ── duplicates and stubs ─────────────────────────────────────────────


def test_health_duplicates(vault: Vault):
    vault.create_page(page_type="concept", title="Thing", metadata={"status": "draft", "tags": ["a"]})
    # Manually create a second page with overlapping alias (bypass duplicate check)
    import frontmatter as fm
    dup_path = vault.root / "knowledge" / "tools" / "other-thing.md"
    dup_path.parent.mkdir(parents=True, exist_ok=True)
    post = fm.Post("", type="tool", title="Other Thing", status="draft", tags=["a"], aliases=["Thing"])
    dup_path.write_text(fm.dumps(post))
    report = vault.health(checks=["duplicates"])
    assert len(report["duplicate_suspects"]) > 0


def test_health_stubs(vault: Vault):
    vault.create_page(page_type="concept", title="Stubby", metadata={"status": "draft", "tags": ["a"]}, body="short")
    report = vault.health(checks=["stubs"])
    assert "Stubby" in report["stubs"]


# ── create_thread ────────────────────────────────────────────────────


def test_create_thread(vault: Vault):
    vault.create_page(page_type="project", title="Thread Project", metadata={"status": "active", "goal": "test", "tags": ["t"]})
    result = vault.create_thread("Thread Project", "My Research Question", description="Can we do X?")
    assert result.get("created") is True
    assert result["thread"] == "my-research-question"

    # Landing page exists
    landing = vault.root / result["landing_page"]
    assert landing.exists()
    content = landing.read_text()
    assert "My Research Question" in content
    assert "Can we do X?" in content
    assert "exploring" in content

    # Index updated
    index = vault.root / result["path"].rsplit("/", 1)[0] / "index.md"
    index_content = index.read_text()
    assert "my-research-question/my-research-question" in index_content
    assert "Can we do X?" in index_content


def test_create_thread_duplicate(vault: Vault):
    vault.create_page(page_type="project", title="Dup Thread Proj", metadata={"status": "active", "goal": "test", "tags": ["t"]})
    vault.create_thread("Dup Thread Proj", "First Thread")
    result = vault.create_thread("Dup Thread Proj", "First Thread")
    assert "error" in result
    assert "already exists" in result["error"].lower()


def test_create_thread_project_not_found(vault: Vault):
    result = vault.create_thread("Nonexistent Project", "Some Thread")
    assert "error" in result


def test_create_thread_creates_index(vault: Vault):
    """If threads/index.md doesn't exist yet, create_thread should create it."""
    vault.create_page(page_type="project", title="Fresh Project", metadata={"status": "active", "goal": "test", "tags": ["t"]})
    result = vault.create_thread("Fresh Project", "First Thread")
    assert result.get("created") is True
    index = vault.root / "work" / "projects" / "fresh-project" / "threads" / "index.md"
    assert index.exists()
    assert "## Active" in index.read_text()


# ── links ────────────────────────────────────────────────────────────


def test_get_links_outlinks(vault: Vault):
    vault.create_page(
        page_type="concept", title="Hub",
        metadata={"status": "draft", "tags": ["test"]},
        body="See [[spoke-a|Spoke A]] and [[spoke-b|Spoke B]].",
    )
    result = vault.get_links("Hub", direction="out")
    assert "outlinks" in result
    assert "spoke-a" in result["outlinks"]
    assert "spoke-b" in result["outlinks"]
    assert "backlinks" not in result


def test_get_links_backlinks(vault: Vault):
    vault.create_page(
        page_type="concept", title="Center",
        metadata={"status": "draft", "tags": ["test"]},
        body="I am the center.",
    )
    vault.create_page(
        page_type="concept", title="Satellite",
        metadata={"status": "draft", "tags": ["test"]},
        body="Orbiting [[center|Center]].",
    )
    result = vault.get_links("Center", direction="in")
    assert "backlinks" in result
    assert "Satellite" in result["backlinks"]
    assert "outlinks" not in result


def test_get_links_both(vault: Vault):
    vault.create_page(
        page_type="concept", title="Node A",
        metadata={"status": "draft", "tags": ["test"]},
        body="Link to [[node-b|Node B]].",
    )
    vault.create_page(
        page_type="concept", title="Node B",
        metadata={"status": "draft", "tags": ["test"]},
        body="Link to [[node-a|Node A]].",
    )
    result = vault.get_links("Node A", direction="both")
    assert "outlinks" in result
    assert "backlinks" in result
    assert "node-b" in result["outlinks"]
    assert "Node B" in result["backlinks"]


def test_get_links_not_found(vault: Vault):
    result = vault.get_links("Ghost Page")
    assert "error" in result


# ── project ──────────────────────────────────────────────────────────


def test_project_overview(vault: Vault):
    vault.create_page(
        page_type="project", title="My Project",
        metadata={"status": "active", "goal": "Build something", "tags": ["test"]},
    )
    vault.create_page(
        page_type="decision", title="Use Postgres",
        metadata={
            "status": "accepted",
            "project": "[[my-project|My Project]]",
            "date": "2026-01-01", "decision": "Use PG", "rationale": "Battle tested",
            "tags": ["test"],
        },
    )
    vault.create_page(
        page_type="task", title="Setup CI",
        metadata={
            "status": "todo",
            "project": "[[my-project|My Project]]",
            "due": "2026-02-01",
            "tags": ["test"],
        },
    )
    result = vault.project_overview("My Project")
    assert result["title"] == "My Project"
    assert result["goal"] == "Build something"
    assert "decision" in result["children"]
    assert "task" in result["children"]
    assert any(c["title"] == "Use Postgres" for c in result["children"]["decision"])
    assert any(c["title"] == "Setup CI" for c in result["children"]["task"])


def test_project_overview_not_found(vault: Vault):
    result = vault.project_overview("Nonexistent")
    assert "error" in result


def test_project_overview_not_a_project(vault: Vault):
    vault.create_page(page_type="concept", title="Not A Project", metadata={"status": "draft", "tags": ["x"]})
    result = vault.project_overview("Not A Project")
    assert "error" in result
    assert "not a project" in result["error"].lower()


# ── provenance ───────────────────────────────────────────────────────


def test_provenance_set_and_get(vault: Vault):
    vault.create_page(page_type="concept", title="Sourced", metadata={"status": "draft", "tags": ["test"]})
    sources = [
        {"type": "paper", "ref": "arxiv:1234.5678"},
        {"type": "context", "ref": "conversation with user"},
    ]
    set_result = vault.set_provenance("Sourced", sources)
    assert set_result.get("updated") is True

    get_result = vault.get_provenance("Sourced")
    assert get_result["title"] == "Sourced"
    assert len(get_result["sources_used"]) == 2
    assert get_result["sources_used"][0]["ref"] == "arxiv:1234.5678"


def test_provenance_not_found(vault: Vault):
    result = vault.get_provenance("Ghost")
    assert "error" in result


# ── style guide ──────────────────────────────────────────────────────


def test_style_init_and_read(vault: Vault):
    content = "# Style Guide\n\n## Voice\n\nBe direct.\n\n## Formatting\n\nUse markdown.\n"
    init_result = vault.init_style_guide(content)
    assert init_result.get("created") is True

    read_result = vault.get_style_guide()
    assert "Be direct" in read_result["content"]


def test_style_init_already_exists(vault: Vault):
    vault.init_style_guide("# Guide\n")
    result = vault.init_style_guide("# New Guide\n")
    assert result.get("exists") is True


def test_style_read_section(vault: Vault):
    content = "# Style Guide\n\n## Voice\n\nBe concise.\n\n## Formatting\n\nUse tables.\n"
    vault.init_style_guide(content)
    result = vault.get_style_guide(section="Voice")
    assert "Be concise" in result["content"]
    assert "Use tables" not in result["content"]


def test_style_read_section_not_found(vault: Vault):
    vault.init_style_guide("# Guide\n\n## Voice\n\nStuff.\n")
    result = vault.get_style_guide(section="Nonexistent")
    assert "error" in result


def test_style_update_full_replace(vault: Vault):
    vault.init_style_guide("# Old\n")
    result = vault.update_style_guide(content="# New\n\nFresh content.\n")
    assert result.get("updated") is True
    read = vault.get_style_guide()
    assert "Fresh content" in read["content"]


def test_style_update_section_patch(vault: Vault):
    vault.init_style_guide("# Guide\n\n## Voice\n\nOld voice.\n\n## Formatting\n\nOld formatting.\n")
    result = vault.update_style_guide(section="Voice", section_content="New voice rules.")
    assert result.get("updated") is True
    assert result["mode"] == "section_patch"

    read = vault.get_style_guide()
    assert "New voice rules" in read["content"]
    assert "Old voice" not in read["content"]
    assert "Old formatting" in read["content"]


def test_style_read_no_guide(vault: Vault):
    result = vault.get_style_guide()
    assert "error" in result


# ── bibtex parsing ───────────────────────────────────────────────────


def test_bibtex_normalize_last_first():
    n = bibtex.normalize_name("Smith, John")
    assert n["full"] == "John Smith"
    assert n["first"] == "John"
    assert n["last"] == "Smith"
    # Alias variants include initial form, comma form, and bare last name
    assert "J. Smith" in n["aliases"]
    assert "Smith, J." in n["aliases"]
    assert "Smith, John" in n["aliases"]
    assert "Smith" in n["aliases"]


def test_bibtex_normalize_first_last():
    n = bibtex.normalize_name("Jane Doe")
    assert n["full"] == "Jane Doe"
    assert n["first"] == "Jane"
    assert n["last"] == "Doe"
    assert "J. Doe" in n["aliases"]


def test_bibtex_normalize_multi_first_name():
    n = bibtex.normalize_name("Ada Lovelace King")
    # Last whitespace token is the family name
    assert n["last"] == "King"
    assert n["first"] == "Ada Lovelace"
    assert "A. L. King" in n["aliases"]


def test_bibtex_normalize_single_token():
    n = bibtex.normalize_name("Plato")
    assert n["full"] == "Plato"
    assert n["last"] == "Plato"
    assert n["first"] == ""
    assert n["aliases"] == []


def test_bibtex_parse_entry_and_authors(tmp_path: Path):
    bib_path = tmp_path / "references.bib"
    bib_path.write_text(
        "@article{smith2024,\n"
        "  author = {Smith, John and Doe, Jane},\n"
        "  title = {A Paper},\n"
        "  year = {2024},\n"
        "}\n"
        "@book{otherkey,\n"
        "  author = {Alone, Only},\n"
        "}\n",
        encoding="utf-8",
    )
    authors = bibtex.extract_authors(bib_path, "smith2024")
    assert authors is not None
    assert [a["full"] for a in authors] == ["John Smith", "Jane Doe"]


def test_bibtex_parse_missing_key(tmp_path: Path):
    bib_path = tmp_path / "references.bib"
    bib_path.write_text("@article{foo,\n  author = {Bar, Baz},\n}\n", encoding="utf-8")
    assert bibtex.extract_authors(bib_path, "nonexistent") is None


def test_bibtex_parse_missing_file(tmp_path: Path):
    assert bibtex.extract_authors(tmp_path / "does-not-exist.bib", "any") is None


def test_bibtex_handles_nested_braces_in_title(tmp_path: Path):
    """Titles commonly contain nested braces like `{EU}` for casing protection.
    The entry parser must not choke on them."""
    bib_path = tmp_path / "references.bib"
    bib_path.write_text(
        "@article{nested2024,\n"
        "  author = {Glencross, Andrew},\n"
        "  title  = {The Geopolitics of Supply Chains: {EU} Efforts to Ensure Security of Supply},\n"
        "  year   = {2024},\n"
        "}\n",
        encoding="utf-8",
    )
    authors = bibtex.extract_authors(bib_path, "nested2024")
    assert authors is not None
    assert [a["full"] for a in authors] == ["Andrew Glencross"]


def test_bibtex_handles_firstlast_form(tmp_path: Path):
    bib_path = tmp_path / "references.bib"
    bib_path.write_text(
        "@article{mixedforms,\n"
        '  author = "John Smith and Jane Doe",\n'
        "}\n",
        encoding="utf-8",
    )
    authors = bibtex.extract_authors(bib_path, "mixedforms")
    assert authors is not None
    assert [a["full"] for a in authors] == ["John Smith", "Jane Doe"]


# ── person schema ────────────────────────────────────────────────────


def test_person_schema_accepts_aliases_and_sources_used(vault: Vault):
    """The person schema should accept both fields (added 2026-04-18)."""
    result = vault.create_page(
        page_type="person",
        title="Test Author",
        metadata={
            "role": "author",
            "aliases": ["T. Author"],
            "sources_used": [{"type": "context", "ref": "test"}],
        },
    )
    assert result.get("created") is True
    read = vault.read_page("Test Author")
    assert read["metadata"]["aliases"] == ["T. Author"]
    assert read["metadata"]["sources_used"] == [{"type": "context", "ref": "test"}]


def test_person_alias_resolves_to_title(vault: Vault):
    """_title_to_path should resolve via an alias."""
    vault.create_page(
        page_type="person",
        title="Jane Doe",
        metadata={"role": "author", "aliases": ["J. Doe", "Doe, J."]},
    )
    found = vault._title_to_path("J. Doe")
    assert found is not None
    assert vault._parse_page(found).title == "Jane Doe"


# ── ingest_authors ───────────────────────────────────────────────────


def _make_resource_with_bibtex(vault: Vault, tmp_path: Path, bibtex_body: str, key: str = "smith2024") -> None:
    """Helper: write references.bib and create a resource page pointing at it."""
    (tmp_path / "references.bib").write_text(bibtex_body, encoding="utf-8")
    vault.create_page(
        page_type="resource",
        title="Test Paper",
        metadata={
            "resource_type": "paper",
            "status": "unread",
            "bibtex_key": key,
        },
        body="# Test Paper\n\nSome notes.\n",
    )


def test_ingest_authors_errors_when_resource_missing(vault: Vault):
    result = vault.ingest_authors(resource="Nonexistent Resource")
    assert "error" in result
    assert "not found" in result["error"].lower()


def test_ingest_authors_errors_on_non_resource(vault: Vault):
    vault.create_page(
        page_type="concept",
        title="Not A Resource",
        metadata={"status": "draft", "tags": ["x"]},
    )
    result = vault.ingest_authors(resource="Not A Resource")
    assert "error" in result
    assert "not a resource" in result["error"].lower()


def test_ingest_authors_errors_when_bibtex_key_missing(vault: Vault, tmp_path: Path):
    _make_resource_with_bibtex(
        vault,
        tmp_path,
        "@article{nope,\n  author = {A, B},\n}\n",
        key="wrongkey",
    )
    result = vault.ingest_authors(resource="Test Paper")
    assert "error" in result
    assert "BibTeX entry not found" in result["error"]


def test_ingest_authors_dry_run_returns_candidates(vault: Vault, tmp_path: Path):
    _make_resource_with_bibtex(
        vault,
        tmp_path,
        "@article{smith2024,\n  author = {Smith, John and Doe, Jane},\n}\n",
    )
    result = vault.ingest_authors(resource="Test Paper")
    assert result["status"] == "pending"
    assert [c["full"] for c in result["new_candidates"]] == ["John Smith", "Jane Doe"]
    # No existing matches — nothing created
    assert result["existing_matches"] == []


def test_ingest_authors_dedupes_via_existing_alias(vault: Vault, tmp_path: Path):
    """If a person exists with an alias that matches a BibTeX author, reuse them."""
    vault.create_page(
        page_type="person",
        title="John Smith",
        metadata={"role": "author", "aliases": ["J. Smith", "Smith, J."]},
    )
    _make_resource_with_bibtex(
        vault,
        tmp_path,
        "@article{smith2024,\n  author = {Smith, John and Doe, Jane},\n}\n",
    )
    result = vault.ingest_authors(resource="Test Paper")
    assert result["status"] == "pending"
    existing_names = [m["page"] for m in result["existing_matches"]]
    assert "John Smith" in existing_names
    # Jane Doe is still a new candidate
    assert [c["full"] for c in result["new_candidates"]] == ["Jane Doe"]


def test_ingest_authors_commit_creates_stubs_and_links_resource(vault: Vault, tmp_path: Path):
    _make_resource_with_bibtex(
        vault,
        tmp_path,
        "@article{smith2024,\n  author = {Smith, John and Doe, Jane},\n}\n",
    )
    result = vault.ingest_authors(
        resource="Test Paper",
        confirmed_names=["John Smith", "Jane Doe"],
    )
    assert result["status"] == "done"
    assert len(result["created"]) == 2
    assert result["linked"] == ["John Smith", "Jane Doe"]

    # Person pages exist with expected aliases
    js = vault.read_page("John Smith")
    assert js["metadata"]["role"] == "author"
    assert "J. Smith" in js["metadata"]["aliases"]
    assert js["metadata"]["sources_used"][0]["ref"].endswith("Test Paper")

    # Resource page body includes Authors line below the H1
    resource = vault.read_page("Test Paper")
    body_lines = resource["body"].split("\n")
    assert body_lines[0] == "# Test Paper"
    authors_line = next(l for l in body_lines if l.startswith("**Authors:**"))
    assert "[[john-smith|John Smith]]" in authors_line
    assert "[[jane-doe|Jane Doe]]" in authors_line

    # Resource metadata.authors updated
    assert resource["metadata"]["authors"] == ["John Smith", "Jane Doe"]


def test_ingest_authors_commit_links_existing_plus_new(vault: Vault, tmp_path: Path):
    """Existing person + new person both land in the resource's Authors line."""
    vault.create_page(
        page_type="person",
        title="John Smith",
        metadata={"role": "author", "aliases": ["J. Smith"]},
    )
    _make_resource_with_bibtex(
        vault,
        tmp_path,
        "@article{smith2024,\n  author = {Smith, John and Doe, Jane},\n}\n",
    )
    result = vault.ingest_authors(
        resource="Test Paper",
        confirmed_names=["Jane Doe"],  # Only confirm the new one
    )
    assert result["status"] == "done"
    assert [c["name"] for c in result["created"]] == ["Jane Doe"]
    assert result["linked"] == ["John Smith", "Jane Doe"]


def test_ingest_authors_is_idempotent_on_authors_line(vault: Vault, tmp_path: Path):
    """Re-running ingest_authors on a committed resource should replace, not duplicate."""
    _make_resource_with_bibtex(
        vault,
        tmp_path,
        "@article{smith2024,\n  author = {Smith, John},\n}\n",
    )
    vault.ingest_authors(resource="Test Paper", confirmed_names=["John Smith"])
    # Second pass (dedup says existing, still updates the Authors line)
    vault.ingest_authors(resource="Test Paper", confirmed_names=[])
    resource = vault.read_page("Test Paper")
    authors_lines = [l for l in resource["body"].split("\n") if l.startswith("**Authors:**")]
    assert len(authors_lines) == 1
    assert "[[john-smith|John Smith]]" in authors_lines[0]


# ── wikilink escapes in markdown tables ──────────────────────────────


def test_outlinks_handles_escaped_pipe_in_table(vault: Vault):
    """Inside a markdown table, `|` is escaped as `\\|`. The outlink
    extractor must treat `[[slug\\|Display]]` the same as `[[slug|Display]]`."""
    vault.create_page(
        page_type="concept",
        title="Target",
        metadata={"status": "draft", "tags": ["x"]},
    )
    vault.create_page(
        page_type="concept",
        title="Table Page",
        metadata={"status": "draft", "tags": ["x"]},
        body=(
            "A table:\n\n"
            "| Col | Link |\n"
            "|---|---|\n"
            "| row | [[target\\|Target]] |\n"
        ),
    )
    page = vault._parse_page(vault._title_to_path("Table Page"))
    outlinks = page.outlinks()
    # The slug should be captured without a trailing backslash
    assert "target" in outlinks
    assert "target\\" not in outlinks


def test_table_escaped_wikilink_not_flagged_as_broken(vault: Vault):
    """health(broken_links) must not flag `[[slug\\|Display]]` as broken."""
    vault.create_page(
        page_type="concept",
        title="Real Page",
        metadata={"status": "draft", "tags": ["x"]},
    )
    vault.create_page(
        page_type="concept",
        title="Linker",
        metadata={"status": "draft", "tags": ["x"]},
        body="| A | B |\n|---|---|\n| see | [[real-page\\|Real Page]] |\n",
    )
    report = vault.health(checks=["broken_links"])
    broken_targets = [bl["to"] for bl in report["broken_links"]]
    assert "real-page\\" not in broken_targets
    assert "real-page" not in broken_targets  # It resolved — not broken


def test_backlinks_find_table_escaped_references(vault: Vault):
    """_find_backlinks must recognize a page that links via `\\|` escape."""
    vault.create_page(
        page_type="concept",
        title="Target",
        metadata={"status": "draft", "tags": ["x"]},
    )
    vault.create_page(
        page_type="concept",
        title="Referrer",
        metadata={"status": "draft", "tags": ["x"]},
        body="| A | B |\n|---|---|\n| row | [[target\\|Target]] |\n",
    )
    backlinks = vault._find_backlinks("Target")
    assert "Referrer" in backlinks


def test_normalize_wikilink_escapes_is_surgical():
    """normalize_wikilink_escapes should only replace `\\|` \u2014 not other backslashes."""
    from obsidian_wiki_mcp.models import normalize_wikilink_escapes
    assert normalize_wikilink_escapes("[[foo\\|Foo]]") == "[[foo|Foo]]"
    # A backslash that isn't before a pipe is left alone.
    assert normalize_wikilink_escapes("path\\to\\file") == "path\\to\\file"
    # Bare text unaffected.
    assert normalize_wikilink_escapes("no pipes here") == "no pipes here"


# ── meeting schema ───────────────────────────────────────────────────


def test_meeting_schema_requires_participants(vault: Vault):
    """Creating a meeting without participants must fail validation."""
    result = vault.create_page(
        page_type="meeting",
        title="Meeting Stefan 2026-04-20",
        metadata={},
    )
    assert "error" in result
    assert any("participants" in d.get("field", "") for d in result.get("details", []))


def test_meeting_creation_lands_in_work_meetings(vault: Vault):
    """A meeting with participants creates a file under work/meetings/."""
    # Create the participant stub first (required for validation — the schema
    # lists participants as a list of wikilinks but the validator doesn't
    # resolve them, so raw names work fine for the schema layer).
    vault.create_page(
        page_type="person",
        title="Stefan",
        metadata={"role": "collaborator"},
    )
    result = vault.create_page(
        page_type="meeting",
        title="Meeting Stefan 2026-04-20",
        metadata={"participants": ["[[stefan|Stefan]]"]},
        body="Discussion of prediction figures.\n",
    )
    assert result.get("created") is True
    # Path should be under work/meetings/ (flat folder per schema)
    assert "work/meetings" in result["path"]
    assert result["path"].endswith("meeting-stefan-2026-04-20.md")


def test_meeting_is_readable_and_has_participants_field(vault: Vault):
    vault.create_page(page_type="person", title="Stefan", metadata={"role": "collaborator"})
    vault.create_page(
        page_type="meeting",
        title="Meeting Stefan 2026-04-20",
        metadata={"participants": ["[[stefan|Stefan]]"]},
    )
    read = vault.read_page("Meeting Stefan 2026-04-20")
    assert read["type"] == "meeting"
    assert read["metadata"]["participants"] == ["[[stefan|Stefan]]"]


def test_meeting_accepts_optional_project(vault: Vault):
    vault.create_page(page_type="person", title="Stefan", metadata={"role": "collaborator"})
    result = vault.create_page(
        page_type="meeting",
        title="Meeting Stefan About X 2026-04-20",
        metadata={
            "participants": ["[[stefan|Stefan]]"],
            "project": "[[wiki-infrastructure/wiki-infrastructure|Wiki Infrastructure]]",
            "tags": ["sync"],
        },
    )
    assert result.get("created") is True
    read = vault.read_page("Meeting Stefan About X 2026-04-20")
    assert "Wiki Infrastructure" in read["metadata"]["project"]
    assert read["metadata"]["tags"] == ["sync"]


def test_meeting_multiple_participants(vault: Vault):
    vault.create_page(page_type="person", title="Stefan", metadata={"role": "collaborator"})
    vault.create_page(page_type="person", title="Viola", metadata={"role": "collaborator"})
    result = vault.create_page(
        page_type="meeting",
        title="Meeting Stefan, Viola 2026-04-20",
        metadata={"participants": ["[[stefan|Stefan]]", "[[viola|Viola]]"]},
    )
    assert result.get("created") is True
    # Comma gets stripped by slugify
    assert "meeting-stefan-viola-2026-04-20" in result["path"]


def test_ingest_authors_extra_people_included(vault: Vault, tmp_path: Path):
    """extra_people (e.g. LLM-scanned mentions) appear alongside BibTeX authors."""
    _make_resource_with_bibtex(
        vault,
        tmp_path,
        "@article{smith2024,\n  author = {Smith, John},\n}\n",
    )
    result = vault.ingest_authors(
        resource="Test Paper",
        extra_people=[{"full": "Ada Lovelace", "aliases": ["A. Lovelace"], "role": "collaborator"}],
    )
    new_names = [c["full"] for c in result["new_candidates"]]
    assert new_names == ["John Smith", "Ada Lovelace"]
    # Role preserved on the extra
    ada = next(c for c in result["new_candidates"] if c["full"] == "Ada Lovelace")
    assert ada["role"] == "collaborator"
