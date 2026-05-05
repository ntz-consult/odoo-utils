"""Reports extractor for Odoo Studio customizations."""

from typing import Any

from .base import BaseExtractor


class ReportsExtractor(BaseExtractor):
    """Extract report actions from Odoo Studio.

    Studio-customized reports are identified by:
    - name containing 'studio'
    - Report name containing 'studio'
    - Reports bound to Studio-customized models
    """

    name = "reports"
    model = "ir.actions.report"
    output_filename = "reports_output.json"

    default_fields = [
        "id",
        "name",
        "model",
        "report_type",
        "report_name",
        "report_file",
        "binding_model_id",
        "binding_type",
        "print_report_name",
        "multi",
        "attachment_use",
        "attachment",
        "paperformat_id",
    ]

    def get_domain(
        self, base_filters: list[list[Any]] | None = None
    ) -> list[Any]:
        """Build domain for Studio reports.

        Args:
            base_filters: Additional filters from config

        Returns:
            Search domain targeting Studio-customized reports
        """
        if not base_filters:
            raise ValueError(
                "extraction_filters for 'reports' must be configured in odoo-instances.json.\n"
                "Add filters to control which reports to extract, for example:\n"
                '  "extraction_filters": {\n'
                '    "reports": "[ (\'create_uid\', \'in\', [5]) ]"\n'
                "  }"
            )

        # Use base_filters as-is
        return list(base_filters)

    def get_fields(self) -> list[str]:
        """Get fields to extract for reports."""
        return self.default_fields

    def transform_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Transform report record for output."""
        record = record.copy()

        # Extract binding model info
        binding_model = record.get("binding_model_id")
        if (
            isinstance(binding_model, (list, tuple))
            and len(binding_model) >= 2
        ):
            record["binding_model_display"] = binding_model[1]
        else:
            record["binding_model_display"] = None

        # Extract paperformat info
        paperformat = record.get("paperformat_id")
        if isinstance(paperformat, (list, tuple)) and len(paperformat) >= 2:
            record["paperformat_display"] = paperformat[1]
        else:
            record["paperformat_display"] = None

        # Human-readable report type
        report_type = record.get("report_type", "")
        record["report_type_display"] = self._get_report_type_display(
            report_type
        )

        # Check for Studio markers
        name = record.get("name", "") or ""
        report_name = record.get("report_name", "") or ""
        model = record.get("model", "") or ""

        record["is_studio_report"] = (
            "studio" in name.lower() or "studio" in report_name.lower()
        )
        record["is_custom_model"] = model.startswith("x_")

        # Complexity based on configuration
        has_attachment = bool(record.get("attachment"))
        has_custom_name = bool(record.get("print_report_name"))
        has_groups = bool(record.get("groups_id"))

        complexity_score = sum([has_attachment, has_custom_name, has_groups])
        if complexity_score == 0:
            record["complexity"] = "simple"
        elif complexity_score == 1:
            record["complexity"] = "moderate"
        else:
            record["complexity"] = "complex"

        return record

    def _get_report_type_display(self, report_type: str) -> str:
        """Get human-readable report type."""
        type_map = {
            "qweb-pdf": "PDF Report",
            "qweb-html": "HTML Report",
            "qweb-text": "Text Report",
            "xlsx": "Excel Report",
        }
        return type_map.get(report_type, report_type)
