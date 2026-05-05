"""View XML generator for Odoo Studio customizations.

Generates XML files for Odoo views (forms, trees, kanban, etc.) with
clean formatting and proper inheritance handling.
"""

from typing import Any, Dict, List

from xml_generator import XmlGenerator


class ViewGenerator(XmlGenerator):
    """Generator for Odoo view XML files."""

    def generate_content(self, view_data: Dict[str, Any], arch_db: str) -> str:
        """Generate XML view file content WITHOUT CDATA wrapper.

        Args:
            view_data: View data dictionary
            arch_db: Complete arch_db XML content

        Returns:
            XML file content as string
        """
        # Use template method for standard record generation
        return self._generate_standard_record_xml(
            view_data,
            "ir.ui.view",
            "view",
            [self._generate_view_fields]
        )

    def _generate_view_fields(self, view_data: Dict[str, Any]) -> List[str]:
        """Generate field elements for a view record.

        Args:
            view_data: View data dictionary

        Returns:
            List of field XML strings
        """
        fields = []

        # Use common fields generation
        fields.extend(self._generate_common_fields(view_data, {
            'model': 'model',
            'priority': 'priority'
        }))

        # Type field
        view_type = view_data.get("type")
        if view_type:
            fields.append(
                self._generate_field_element("type", view_type)
            )

        # Inherit ID field
        inherit_id = view_data.get("inherit_id")
        if inherit_id:
            inherit_ref = view_data.get("inherit_view_xml_id")
            if inherit_ref:
                fields.append(
                    self._generate_ref_field("inherit_id", inherit_ref, view_data)
                )

        # Arch field - use template method
        arch_db = view_data.get("arch_db", "")
        if arch_db:
            fields.extend(self._generate_arch_field(arch_db))

        return fields
