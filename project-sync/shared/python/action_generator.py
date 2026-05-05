"""Action XML generator for Odoo Studio customizations.

Generates XML files for Odoo server actions and automations with
clean formatting and proper field handling.
"""

from datetime import datetime
from typing import Any, Dict, List

from xml_generator import XmlGenerator


class ActionGenerator(XmlGenerator):
    """Generator for Odoo action XML files (server actions and automations)."""

    def generate_content(self, data: Dict[str, Any], **kwargs) -> str:
        """Generate content based on action type.

        Args:
            data: Action data dictionary
            **kwargs: Additional arguments

        Returns:
            Content as string (Python or XML)
        """
        if 'code' in data:
            # Server action (Python)
            return self.generate_server_action_content(data)
        else:
            # Automation (XML)
            return self.generate_automation_content(data)

    def generate_server_action_content(self, action_data: Dict[str, Any]) -> str:
        """Generate Python server action file content.

        Args:
            action_data: Server action data dictionary

        Returns:
            Python file content as string
        """
        timestamp = datetime.now().strftime("%Y-%m-%d")
        code = action_data.get("code", "")
        code_lines = len(code.split("\n"))

        lines = [
            f"# Action: {action_data.get('name', 'Unknown')}",
            f"# Model: {action_data.get('model_name', 'Unknown')}",
            f"# State: {action_data.get('state', 'code')}",
            f"# Complexity: {action_data.get('complexity', 'Unknown').capitalize()}",
            f"# Extracted from Odoo Studio on {timestamp}",
            "",
            f"# Lines of code: {code_lines}",
            "",
            code,
        ]

        return "\n".join(lines)

    def generate_automation_content(self, automation_data: Dict[str, Any]) -> str:
        """Generate XML automation file content with cleaned domain.

        Args:
            automation_data: Automation data dictionary

        Returns:
            XML file content as string
        """
        # Use template method for standard record generation
        return self._generate_standard_record_xml(
            automation_data,
            "base.automation",
            "automation",
            [self._generate_automation_fields]
        )

    def _generate_automation_fields(self, automation_data: Dict[str, Any]) -> List[str]:
        """Generate field elements for an automation record.

        Args:
            automation_data: Automation data dictionary

        Returns:
            List of field XML strings
        """
        fields = []

        # Use common fields generation
        fields.extend(self._generate_common_fields(automation_data, {
            'model_name': 'model_name'
        }))

        # Trigger field
        trigger = automation_data.get("trigger", "")
        if trigger:
            fields.append(
                self._generate_field_element("trigger", trigger)
            )

        # Filter domain field
        filter_domain = automation_data.get("filter_domain", "")
        if filter_domain and filter_domain != "[]":
            cleaned_domain = self._clean_filter_domain(filter_domain)
            fields.append(
                self._generate_field_element("filter_domain", self._escape_xml(cleaned_domain))
            )

        return fields

    def _clean_filter_domain(self, domain: str) -> str:
        """Clean filter domain by replacing HTML entities.

        Args:
            domain: Raw domain string

        Returns:
            Cleaned domain string
        """
        # Replace &quot; with '
        cleaned = domain.replace("&quot;", "'")
