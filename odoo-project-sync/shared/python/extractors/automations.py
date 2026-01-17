"""Automations extractor for Odoo Studio customizations."""

from typing import Any

from .base import BaseExtractor


class AutomationsExtractor(BaseExtractor):
    """Extract automated actions (automations) from Odoo Studio.

    Studio-created automations are identified by:
    - name containing 'studio'
    - Actions referencing x_studio_ fields
    - Triggers on Studio-customized models
    """

    name = "automations"
    model = "base.automation"
    output_filename = "auto_actions_output.json"

    default_fields = [
        "id",
        "name",
        "active",
        "model_id",
        "model_name",
        "trigger",
        "trigger_field_ids",
        "trg_selection_field_id",
        "trg_date_id",
        "trg_date_range",
        "trg_date_range_type",
        "filter_pre_domain",
        "filter_domain",
        "on_change_field_ids",
        "action_server_ids",
        "last_run",
        "record_getter",
        "url",
    ]

    def get_domain(
        self, base_filters: list[list[Any]] | None = None
    ) -> list[Any]:
        """Build domain for Studio automations.

        Args:
            base_filters: Required filters from config (e.g., write_uid filter)

        Returns:
            Search domain using the provided filters

        Raises:
            ValueError: If base_filters is not provided
        """
        if not base_filters:
            raise ValueError(
                "extraction_filters for 'automations' must be configured in odoo-instances.json.\n"
                "Add filters to control which automations to extract, for example:\n"
                '  "extraction_filters": {\n'
                '    "automations": "[ (\'create_uid\', \'in\', [5]) ]"\n'
                "  }"
            )

        # Use base_filters as-is, with active=True filter
        domain: list[Any] = [["active", "=", True]] + list(base_filters)

        return domain

    def get_fields(self) -> list[str]:
        """Get fields to extract for automations."""
        return self.default_fields

    def transform_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Transform automation record for output."""
        record = record.copy()

        # Extract model info
        model_id = record.get("model_id")
        if isinstance(model_id, (list, tuple)) and len(model_id) >= 2:
            record["model_display"] = model_id[1]
        else:
            record["model_display"] = record.get("model_name", "")

        # Human-readable trigger type
        trigger = record.get("trigger", "")
        record["trigger_display"] = self._get_trigger_display(trigger)

        # Extract trigger field info
        trigger_fields = record.get("trigger_field_ids", [])
        record["trigger_field_count"] = (
            len(trigger_fields) if trigger_fields else 0
        )

        # Check for Studio references in domains
        filter_domain = record.get("filter_domain", "") or ""
        filter_pre_domain = record.get("filter_pre_domain", "") or ""
        record["has_studio_fields"] = (
            "x_studio_" in filter_domain or "x_studio_" in filter_pre_domain
        )
        record["has_custom_fields"] = (
            "x_" in filter_domain or "x_" in filter_pre_domain
        )

        # Count linked server actions
        action_ids = record.get("action_server_ids", [])
        record["action_count"] = len(action_ids) if action_ids else 0

        # Estimate complexity based on configuration
        complexity_score = 0
        if filter_domain:
            complexity_score += 1
        if filter_pre_domain:
            complexity_score += 1
        if record["action_count"] > 1:
            complexity_score += 1
        if record["trigger_field_count"] > 1:
            complexity_score += 1

        if complexity_score <= 1:
            record["complexity"] = "simple"
        elif complexity_score <= 2:
            record["complexity"] = "moderate"
        else:
            record["complexity"] = "complex"

        return record

    def _get_trigger_display(self, trigger: str) -> str:
        """Get human-readable trigger type."""
        trigger_map = {
            "on_create": "On Creation",
            "on_write": "On Update",
            "on_create_or_write": "On Creation or Update",
            "on_unlink": "On Deletion",
            "on_change": "On Field Change",
            "on_time": "Based on Date Field",
            "on_time_created": "After Creation",
            "on_time_updated": "After Update",
            "on_state_set": "On Stage Set",
            "on_tag_set": "On Tag Set",
            "on_priority_set": "On Priority Set",
            "on_user_set": "On User Set",
            "on_webhook": "On Webhook",
            "on_message_received": "On Message Received",
            "on_message_sent": "On Message Sent",
        }
        return trigger_map.get(trigger, trigger)
