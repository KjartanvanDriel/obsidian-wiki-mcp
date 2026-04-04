"""Schema loading and validation for wiki page types."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .models import ValidationError, WikiPage


class SchemaRegistry:
    """Loads and validates page schemas."""

    def __init__(self, schemas_dir: Path):
        self.schemas_dir = schemas_dir
        self.schemas: dict[str, dict] = {}
        self._load_schemas()

    def _load_schemas(self) -> None:
        """Load all .yaml schema files from the schemas directory."""
        if not self.schemas_dir.exists():
            return
        for schema_file in self.schemas_dir.glob("*.yaml"):
            with open(schema_file) as f:
                schema = yaml.safe_load(f)
            if schema and "type" in schema:
                self.schemas[schema["type"]] = schema

    def reload(self) -> None:
        """Reload schemas from disk."""
        self.schemas.clear()
        self._load_schemas()

    def get_schema(self, page_type: str) -> dict | None:
        return self.schemas.get(page_type)

    def list_types(self) -> list[str]:
        return sorted(self.schemas.keys())

    def get_folder(self, page_type: str) -> str | None:
        schema = self.get_schema(page_type)
        return schema.get("folder") if schema else None

    def get_layer(self, page_type: str) -> str | None:
        schema = self.get_schema(page_type)
        return schema.get("layer") if schema else None

    def get_required_fields(self, page_type: str) -> list[str]:
        schema = self.get_schema(page_type)
        if not schema:
            return []
        return schema.get("required_fields", [])

    def get_field_def(self, page_type: str, field_name: str) -> dict | None:
        schema = self.get_schema(page_type)
        if not schema:
            return None
        return schema.get("fields", {}).get(field_name)

    def get_default_metadata(self, page_type: str) -> dict[str, Any]:
        """Generate default metadata for a page type."""
        schema = self.get_schema(page_type)
        if not schema:
            return {"type": page_type}

        defaults: dict[str, Any] = {"type": page_type}
        for field_name, field_def in schema.get("fields", {}).items():
            if "default" in field_def:
                defaults[field_name] = field_def["default"]
        return defaults

    def validate_page(self, page: WikiPage) -> list[ValidationError]:
        """Validate a page against its type schema."""
        errors: list[ValidationError] = []
        schema = self.get_schema(page.page_type)

        if not schema:
            errors.append(ValidationError(
                page_title=page.title,
                field="type",
                message=f"Unknown page type: {page.page_type}",
            ))
            return errors

        # Check required fields
        for field_name in schema.get("required_fields", []):
            value = page.metadata.get(field_name)
            if value is None or value == "" or value == []:
                errors.append(ValidationError(
                    page_title=page.title,
                    field=field_name,
                    message=f"Required field '{field_name}' is missing or empty",
                ))

        # Validate field types and enums
        for field_name, field_def in schema.get("fields", {}).items():
            value = page.metadata.get(field_name)
            if value is None or value == "":
                continue  # Skip missing optional fields

            field_errors = self._validate_field(page.title, field_name, field_def, value)
            errors.extend(field_errors)

        # Check for unknown fields (warning, not error)
        known_fields = set(schema.get("fields", {}).keys())
        known_fields.update(["type", "created", "title"])  # Always allowed
        for field_name in page.metadata:
            if field_name not in known_fields:
                errors.append(ValidationError(
                    page_title=page.title,
                    field=field_name,
                    message=f"Unknown field '{field_name}' not in schema for type '{page.page_type}'",
                    severity="warning",
                ))

        return errors

    def _validate_field(
        self, page_title: str, field_name: str, field_def: dict, value: Any
    ) -> list[ValidationError]:
        """Validate a single field value against its definition."""
        errors: list[ValidationError] = []
        field_type = field_def.get("type", "string")

        if field_type == "enum":
            allowed = field_def.get("values", [])
            if value not in allowed:
                errors.append(ValidationError(
                    page_title=page_title,
                    field=field_name,
                    message=f"Value '{value}' not in allowed values: {allowed}",
                ))

        elif field_type == "list":
            if not isinstance(value, list):
                errors.append(ValidationError(
                    page_title=page_title,
                    field=field_name,
                    message=f"Expected list, got {type(value).__name__}",
                ))

        elif field_type == "date":
            if not isinstance(value, (date, str)):
                errors.append(ValidationError(
                    page_title=page_title,
                    field=field_name,
                    message=f"Expected date (YYYY-MM-DD), got {type(value).__name__}",
                ))

        elif field_type == "integer":
            if not isinstance(value, int):
                errors.append(ValidationError(
                    page_title=page_title,
                    field=field_name,
                    message=f"Expected integer, got {type(value).__name__}",
                ))

        return errors
