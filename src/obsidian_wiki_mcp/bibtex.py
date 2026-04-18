"""Lightweight BibTeX reader — just enough to extract author names from an entry.

We deliberately avoid a full BibTeX parser dependency. The scope is narrow:
read `references.bib`, find an entry by key, pull the `author` field, split on
`and`, and return a list of normalized names with alias variants.
"""

from __future__ import annotations

import re
from pathlib import Path

_ENTRY_HEADER_RE = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,")


def _find_matching_brace(text: str, start: int) -> int:
    """Return the index of the `}` matching the `{` at `text[start]`.

    Assumes `text[start] == '{'`. Returns -1 if no match.
    """
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _unwrap(value: str) -> str:
    """Strip surrounding braces or quotes from a BibTeX field value."""
    v = value.strip()
    if v.startswith("{") and v.endswith("}"):
        # Strip outer braces only; preserve any inner {...} structure
        v = v[1:-1]
    elif v.startswith('"') and v.endswith('"'):
        v = v[1:-1]
    # Flatten any remaining single braces (e.g. {EU} → EU)
    return v.replace("{", "").replace("}", "").strip()


def _parse_fields(body: str) -> dict[str, str]:
    """Parse `name = value,` pairs from a BibTeX entry body. Handles
    brace-delimited values with arbitrary nesting, quoted values, and
    comma-terminated unquoted values."""
    fields: dict[str, str] = {}
    i = 0
    n = len(body)
    while i < n:
        # Skip whitespace and commas
        while i < n and (body[i].isspace() or body[i] == ","):
            i += 1
        # Read the field name
        name_match = re.match(r"(\w+)\s*=\s*", body[i:])
        if not name_match:
            break
        name = name_match.group(1).lower()
        i += name_match.end()
        # Read the field value
        if i >= n:
            break
        c = body[i]
        if c == "{":
            end = _find_matching_brace(body, i)
            if end < 0:
                break
            value = body[i : end + 1]
            i = end + 1
        elif c == '"':
            end = body.find('"', i + 1)
            if end < 0:
                break
            value = body[i : end + 1]
            i = end + 1
        else:
            # Unquoted: read until next comma or newline
            end = i
            while end < n and body[end] not in ",\n":
                end += 1
            value = body[i:end]
            i = end
        fields[name] = _unwrap(value)
    return fields


def parse_entry(bib_text: str, key: str) -> dict[str, str] | None:
    """Return all fields of a BibTeX entry keyed by `key`, or None if absent."""
    for m in _ENTRY_HEADER_RE.finditer(bib_text):
        if m.group(1) != key:
            continue
        # Find the opening brace of the entry (the one just before the key)
        # and the matching close brace.
        brace_start = bib_text.rfind("{", 0, m.end())
        if brace_start < 0:
            return None
        brace_end = _find_matching_brace(bib_text, brace_start)
        if brace_end < 0:
            return None
        # Body is everything after the key's trailing comma up to the close brace
        body = bib_text[m.end() : brace_end]
        return _parse_fields(body)
    return None


def _split_authors(author_field: str) -> list[str]:
    """Split a BibTeX author field on ' and ' (word boundaries)."""
    return [
        part.strip()
        for part in re.split(r"\s+and\s+", author_field)
        if part.strip()
    ]


def normalize_name(raw: str) -> dict[str, object]:
    """Normalize a single BibTeX author entry.

    Handles both 'Last, First' and 'First Last' forms. Returns:
        {
            "full": "First Last",
            "first": "First",
            "last": "Last",
            "aliases": ["F. Last", "Last, F.", "Last", ...],
        }

    The 'full' name is always in 'First Last' order regardless of input form.
    """
    name = re.sub(r"\s+", " ", raw).strip()
    # Strip any remaining braces (e.g. "{van der Waals}" → "van der Waals")
    name = name.replace("{", "").replace("}", "")

    if "," in name:
        # "Last, First Middle" form
        last, _, first = name.partition(",")
        last = last.strip()
        first = first.strip()
    else:
        parts = name.split(" ")
        if len(parts) == 1:
            last = parts[0]
            first = ""
        else:
            last = parts[-1]
            first = " ".join(parts[:-1])

    full = f"{first} {last}".strip() if first else last

    aliases: list[str] = []
    if first and last:
        first_parts = [p for p in first.split() if p]
        initials = ". ".join(p[0] for p in first_parts) + "."
        aliases.append(f"{initials} {last}")
        aliases.append(f"{last}, {initials}")
        aliases.append(f"{last}, {first}")
    if last and last != full:
        aliases.append(last)
    seen: set[str] = {full}
    unique_aliases: list[str] = []
    for a in aliases:
        if a not in seen:
            seen.add(a)
            unique_aliases.append(a)

    return {
        "full": full,
        "first": first,
        "last": last,
        "aliases": unique_aliases,
    }


def extract_authors(bib_path: Path, key: str) -> list[dict[str, object]] | None:
    """Read `bib_path`, find the entry for `key`, return normalized authors.

    Returns None if the file doesn't exist or the key isn't present.
    Returns an empty list if the entry has no `author` field.
    """
    if not bib_path.exists():
        return None
    text = bib_path.read_text(encoding="utf-8")
    entry = parse_entry(text, key)
    if entry is None:
        return None
    author_field = entry.get("author", "")
    if not author_field:
        return []
    raw_authors = _split_authors(author_field)
    return [normalize_name(r) for r in raw_authors]
