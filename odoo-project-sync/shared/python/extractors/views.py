"""Views extractor for Odoo Studio customizations.

Uses two-phase extraction for large arch_db fields:
1. First query: Get metadata without arch_db
2. Second query: Fetch arch_db for each view individually
"""

from typing import Any

from .base import BaseExtractor, ExtractionResult


class ViewsExtractor(BaseExtractor):
    """Extract view customizations from Odoo Studio.

    Studio-modified views are identified by:
    - arch_db containing 'studio' or 'x_studio'
    - name containing 'studio'
    - Views inheriting Studio-generated views
    """

    name = "views"
    model = "ir.ui.view"
    output_filename = "views_metadata.json"

    # Metadata fields (first phase)
    metadata_fields = [
        "id",
        "name",
        "model",
        "type",
        "mode",
        "priority",
        "inherit_id",
        "active",
        "arch_fs",
        "key",
    ]

    # Full fields including arch (second phase)
    default_fields = [
        "id",
        "name",
        "model",
        "type",
        "mode",
        "priority",
        "inherit_id",
        "active",
        "arch_db",
        "arch_fs",
        "key",
    ]

    def get_domain(
        self, base_filters: list[list[Any]] | None = None
    ) -> list[Any]:
        """Build domain for Studio-modified views.

        Args:
            base_filters: Required filters from config (e.g., write_uid filter)

        Returns:
            Search domain using the provided filters

        Raises:
            ValueError: If base_filters is not provided
        """
        if not base_filters:
            raise ValueError(
                "extraction_filters for 'views' must be configured in odoo-instances.json.\n"
                "Add filters to control which views to extract, for example:\n"
                '  "extraction_filters": {\n'
                '    "views": "[ (\'create_uid\', \'in\', [5]) ]"\n'
                "  }"
            )

        # Use base_filters as-is
        return list(base_filters)

    def get_fields(self) -> list[str]:
        """Get fields for initial metadata query."""
        return self.metadata_fields

    def extract(
        self,
        base_filters: list[list[Any]] | None = None,
    ) -> ExtractionResult:
        """Two-phase extraction for views.

        Phase 1: Get metadata for all matching views
        Phase 2: Fetch arch_db individually for each view

        This approach handles large arch_db fields that could
        cause memory issues if fetched in bulk.
        """
        domain = self.get_domain(base_filters)

        # Phase 1: Get metadata
        try:
            metadata_records = self.client.search_read(
                model=self.model,
                domain=domain,
                fields=self.metadata_fields,
            )
        except Exception as e:
            self._errors.append(f"Metadata query failed: {e}")
            metadata_records = []

        # Phase 2: Fetch arch_db for each view
        full_records = []
        for meta in metadata_records:
            try:
                view_id = meta["id"]
                arch_data = self.client.read(
                    model=self.model,
                    ids=[view_id],
                    fields=["arch_db"],
                )
                if arch_data:
                    meta["arch_db"] = arch_data[0].get("arch_db", "")
                else:
                    meta["arch_db"] = ""
                full_records.append(self.transform_record(meta))
            except Exception as e:
                self._errors.append(
                    f"Failed to fetch arch for view {meta.get('id')}: {e}"
                )
                meta["arch_db"] = ""
                full_records.append(meta)

        result = ExtractionResult(
            extractor_name=self.name,
            model=self.model,
            record_count=len(full_records),
            records=full_records,
            output_file=self.output_filename,
            dry_run=self.dry_run,
            errors=self._errors.copy(),
        )

        if not self.dry_run:
            self._write_output(result)

        return result

    def transform_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Transform view record for output."""
        record = record.copy()

        # Extract inherit_id name
        inherit_id = record.get("inherit_id")
        if isinstance(inherit_id, (list, tuple)) and len(inherit_id) >= 2:
            record["inherit_view_name"] = inherit_id[1]
            record["inherit_view_id"] = inherit_id[0]
        else:
            record["inherit_view_name"] = None
            record["inherit_view_id"] = None

        # Analyze arch for Studio markers
        arch = record.get("arch_db", "") or ""
        record["has_studio_fields"] = "x_studio_" in arch
        record["has_studio_markers"] = (
            "data-studio" in arch or "studio" in arch.lower()
        )

        # Estimate complexity by arch size
        arch_size = len(arch)
        if arch_size < 1000:
            record["complexity"] = "simple"
        elif arch_size < 5000:
            record["complexity"] = "moderate"
        else:
            record["complexity"] = "complex"

        return record
