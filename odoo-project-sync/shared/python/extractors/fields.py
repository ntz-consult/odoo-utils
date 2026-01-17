"""Custom fields extractor for Odoo Studio customizations."""

from typing import Any

from .base import BaseExtractor


class FieldsExtractor(BaseExtractor):
    """Extract custom fields created via Odoo Studio.

    Studio-created fields are identified by:
    - state = 'manual' (user-created fields)
    - name starting with 'x_' or 'x_studio_'
    """

    name = "custom_fields"
    model = "ir.model.fields"
    output_filename = "custom_fields_output.json"

    # Fields relevant for custom field documentation
    default_fields = [
        "id",
        "name",
        "field_description",
        "model",
        "model_id",
        "ttype",
        "state",
        "required",
        "readonly",
        "store",
        "index",
        "copied",
        "relation",
        "relation_field",
        "relation_table",
        "domain",
        "selection_ids",
        "compute",
        "depends",
        "help",
        "groups",
    ]

    def get_domain(
        self, base_filters: list[list[Any]] | None = None
    ) -> list[Any]:
        """Build domain for custom Studio fields.

        Args:
            base_filters: Required filters from config (e.g., [["state", "=", "manual"]])

        Returns:
            Search domain using the provided filters

        Raises:
            ValueError: If base_filters is not provided
        """
        if not base_filters:
            raise ValueError(
                "extraction_filters for 'custom_fields' must be configured in odoo-instances.json.\n"
                "Add filters to control which fields to extract, for example:\n"
                '  "extraction_filters": {\n'
                '    "custom_fields": "[ (\'create_uid\', \'in\', [5]) ]"\n'
                "  }"
            )

        # Use base_filters as-is
        return list(base_filters)

    def get_fields(self) -> list[str]:
        """Get fields to extract for custom fields."""
        return self.default_fields

    def transform_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Transform field record for output.

        Enriches with:
        - is_studio: True if x_studio_ prefix
        - field_type_display: Human-readable type
        """
        record = record.copy()

        # Identify Studio vs regular custom fields
        name = record.get("name", "")
        record["is_studio"] = name.startswith("x_studio_")

        # Add human-readable field type
        ttype = record.get("ttype", "")
        record["field_type_display"] = self._get_type_display(ttype, record)

        # Extract model name from model_id tuple
        model_id = record.get("model_id")
        if isinstance(model_id, (list, tuple)) and len(model_id) >= 2:
            record["model_name"] = model_id[1]
        else:
            record["model_name"] = record.get("model", "")

        return record

    def _get_type_display(self, ttype: str, record: dict[str, Any]) -> str:
        """Get human-readable field type description."""
        type_map = {
            "char": "Text",
            "text": "Long Text",
            "html": "HTML",
            "integer": "Integer",
            "float": "Decimal",
            "monetary": "Monetary",
            "boolean": "Checkbox",
            "date": "Date",
            "datetime": "Date & Time",
            "binary": "Binary/File",
            "selection": "Selection",
            "many2one": f"Many2One → {record.get('relation', '?')}",
            "one2many": f"One2Many → {record.get('relation', '?')}",
            "many2many": f"Many2Many → {record.get('relation', '?')}",
            "reference": "Reference",
        }
        return type_map.get(ttype, ttype)
