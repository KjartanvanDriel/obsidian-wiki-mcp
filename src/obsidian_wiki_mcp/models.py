"""Data models for the wiki system."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


_RE_CODE_BLOCK = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_RE_INLINE_CODE = re.compile(r"`[^`]+`")


def strip_code(text: str) -> str:
    """Remove fenced code blocks and inline code from text."""
    text = _RE_CODE_BLOCK.sub("", text)
    text = _RE_INLINE_CODE.sub("", text)
    return text


@dataclass
class WikiPage:
    """A parsed wiki page."""

    title: str
    path: Path
    page_type: str
    metadata: dict[str, Any]
    body: str
    created: date | None = None

    @property
    def slug(self) -> str:
        return self.path.stem

    @property
    def project(self) -> str | None:
        """Extract project wikilink if present."""
        return self.metadata.get("project", None)

    @property
    def tags(self) -> list[str]:
        return self.metadata.get("tags", [])

    @property
    def aliases(self) -> list[str]:
        return self.metadata.get("aliases", [])

    @property
    def status(self) -> str | None:
        return self.metadata.get("status", None)

    def outlinks(self) -> list[str]:
        """Extract all [[wikilinks]] from body and metadata."""
        links = set()
        # Links in body (excluding code blocks and inline code)
        body_text = strip_code(self.body)
        links.update(re.findall(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", body_text))
        # Links in metadata values
        _extract_links_from_value(self.metadata, links)
        return sorted(links)


def _extract_links_from_value(value: Any, links: set[str]) -> None:
    """Recursively extract [[wikilinks]] from metadata values."""
    if isinstance(value, str):
        links.update(re.findall(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", value))
    elif isinstance(value, list):
        for item in value:
            _extract_links_from_value(item, links)
    elif isinstance(value, dict):
        for v in value.values():
            _extract_links_from_value(v, links)


@dataclass
class ValidationError:
    """A schema validation error on a page."""

    page_title: str
    field: str
    message: str
    severity: str = "error"  # error | warning


@dataclass
class HealthReport:
    """Results of a vault health check."""

    orphans: list[str] = field(default_factory=list)
    stubs: list[str] = field(default_factory=list)
    broken_links: list[dict[str, str]] = field(default_factory=list)
    validation_errors: list[ValidationError] = field(default_factory=list)
    duplicate_suspects: list[dict[str, list[str]]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "orphans": self.orphans,
            "stubs": self.stubs,
            "broken_links": self.broken_links,
            "validation_errors": [
                {"page": e.page_title, "field": e.field, "message": e.message, "severity": e.severity}
                for e in self.validation_errors
            ],
            "duplicate_suspects": self.duplicate_suspects,
            "summary": {
                "orphan_count": len(self.orphans),
                "stub_count": len(self.stubs),
                "broken_link_count": len(self.broken_links),
                "validation_error_count": len(self.validation_errors),
                "duplicate_count": len(self.duplicate_suspects),
            },
        }
