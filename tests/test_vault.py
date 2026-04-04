"""Tests for vault operations — uses a temporary vault with real schemas."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from obsidian_wiki_mcp.schemas import SchemaRegistry
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
