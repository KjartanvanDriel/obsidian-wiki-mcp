"""Tests for vault operations — uses a temporary vault with real schemas."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

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
    """threads.md, todos.md, Landing.md, and attachments/ should not be indexed."""
    # Create files that should be skipped
    (vault.root / "Landing.md").write_text("# Landing\n")
    project_dir = vault.root / "work" / "projects" / "test-proj"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "threads.md").write_text("# Threads\n")
    (project_dir / "todos.md").write_text("# TODOs\n")
    attachments = project_dir / "attachments"
    attachments.mkdir(parents=True, exist_ok=True)
    (attachments / "report.md").write_text("# Raw report\n")

    md_files = vault._all_md_files()
    names = [p.name for p in md_files]
    assert "threads.md" not in names
    assert "todos.md" not in names
    assert "Landing.md" not in names
    assert "report.md" not in names


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
        metadata={"status": "draft", "project": "[[filter-proj|FilterProj]]", "date": "2026-01-01", "decision": "x", "rationale": "y", "tags": ["t"]},
    )
    vault.create_page(
        page_type="decision", title="OtherDec",
        metadata={"status": "draft", "project": "[[other|Other]]", "date": "2026-01-01", "decision": "x", "rationale": "y", "tags": ["t"]},
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
            "status": "draft",
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
