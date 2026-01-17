"""Server actions extractor for Odoo Studio customizations."""

from typing import Any

from .base import BaseExtractor


class ServerActionsExtractor(BaseExtractor):
    """Extract server actions created via Odoo Studio.

    Studio-created server actions are identified by:
    - usage = 'ir_actions_server' (automated actions)
    - name or binding containing 'studio'
    - Code containing x_studio_ references
    """

    name = "server_actions"
    model = "ir.actions.server"
    output_filename = "server_actions_output.json"

    default_fields = [
        "id",
        "name",
        "type",
        "state",
        "model_id",
        "model_name",
        "binding_model_id",
        "binding_type",
        "binding_view_types",
        "code",
        "crud_model_id",
        "crud_model_name",
        "link_field_id",
        "sequence",
        "usage",
    ]

    def get_domain(
        self, base_filters: list[list[Any]] | None = None
    ) -> list[Any]:
        """Build domain for Studio server actions.

        Args:
            base_filters: Required filters from config (e.g., write_uid filter)

        Returns:
            Search domain using the provided filters

        Raises:
            ValueError: If base_filters is not provided
        """
        if not base_filters:
            raise ValueError(
                "extraction_filters for 'server_actions' must be configured in odoo-instances.json.\n"
                "Add filters to control which server actions to extract, for example:\n"
                '  "extraction_filters": {\n'
                '    "server_actions": "[ (\'create_uid\', \'in\', [5]) ]"\n'
                "  }"
            )

        # Use base_filters as-is
        return list(base_filters)

    def get_fields(self) -> list[str]:
        """Get fields to extract for server actions."""
        return self.default_fields

    def transform_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Transform server action record for output."""
        record = record.copy()

        # Extract model info from tuple
        model_id = record.get("model_id")
        if isinstance(model_id, (list, tuple)) and len(model_id) >= 2:
            record["model_display"] = model_id[1]
        else:
            record["model_display"] = record.get("model_name", "")

        # Extract binding model info
        binding_model = record.get("binding_model_id")
        if (
            isinstance(binding_model, (list, tuple))
            and len(binding_model) >= 2
        ):
            record["binding_model_display"] = binding_model[1]
        else:
            record["binding_model_display"] = None

        # Analyze action type
        state = record.get("state", "")
        record["action_type_display"] = self._get_action_type_display(state)

        # Check for Studio references in code
        code = record.get("code", "") or ""
        record["has_studio_fields"] = "x_studio_" in code
        record["has_custom_fields"] = "x_" in code

        # Estimate complexity
        code_lines = len(code.split("\n")) if code else 0
        if code_lines < 10:
            record["complexity"] = "simple"
        elif code_lines < 50:
            record["complexity"] = "moderate"
        else:
            record["complexity"] = "complex"

        return record

    def _get_action_type_display(self, state: str) -> str:
        """Get human-readable action type."""
        type_map = {
            "code": "Execute Python Code",
            "object_create": "Create Record",
            "object_write": "Update Record",
            "multi": "Execute Multiple Actions",
            "email": "Send Email",
            "sms": "Send SMS",
            "followers": "Add Followers",
            "next_activity": "Schedule Activity",
            "webhook": "Call Webhook",
        }
        return type_map.get(state, state)
