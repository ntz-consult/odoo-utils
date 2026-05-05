"""Report XML generator for Odoo Studio customizations.

Generates XML files for Odoo reports and QWeb templates with
clean formatting and proper field handling.
"""

from typing import Any, Dict, List

from xml_generator import XmlGenerator


class ReportGenerator(XmlGenerator):
    """Generator for Odoo report XML files and QWeb templates."""

    def generate_content(self, data: Dict[str, Any], **kwargs) -> str:
        """Generate content based on report type.

        Args:
            data: Report data dictionary
            **kwargs: Additional arguments

        Returns:
            XML content as string
        """
        if 'arch_db' in data:
            # QWeb template
            return self.generate_template_content(data)
        else:
            # Report
            return self.generate_report_content(data)

    def generate_report_content(self, report_data: Dict[str, Any]) -> str:
        """Generate XML report file content.

        Args:
            report_data: Report data dictionary

        Returns:
            XML file content as string
        """
        # Use template method for standard record generation
        return self._generate_standard_record_xml(
            report_data,
            "ir.actions.report",
            "report",
            [self._generate_report_fields]
        )

    def generate_template_content(self, template_data: Dict[str, Any]) -> str:
        """Generate QWeb template XML content.

        Args:
            template_data: Template data dictionary

        Returns:
            XML file content as string
        """
        lines = self._generate_xml_header()

        # Generate template element
        template_id = template_data.get(
            "xml_id", template_data.get("key", "template")
        )

        lines.append(f'    <template id="{template_id}">')

        # Get arch content
        arch = template_data.get("arch_db", "")
        if arch:
            arch_lines = self._format_arch_content(arch)
            lines.extend(arch_lines)

        lines.append("    </template>")

        lines.extend(self._generate_xml_footer())

        return "\n".join(lines)

    def _generate_report_fields(self, report_data: Dict[str, Any]) -> List[str]:
        """Generate field elements for a report record.

        Args:
            report_data: Report data dictionary

        Returns:
            List of field XML strings
        """
        fields = []

        # Use common fields generation
        fields.extend(self._generate_common_fields(report_data, {
            'model': 'model'
        }))

        # Report type field
        report_type = report_data.get("report_type", "")
        if report_type:
            fields.append(
                self._generate_field_element("report_type", report_type)
            )

        # Report name field
        report_name = report_data.get("report_name")
        if report_name:
            fields.append(
                self._generate_field_element("report_name", report_name)
            )

        # Paperformat field
        paperformat_id = report_data.get("paperformat_id")
        if paperformat_id:
            fields.append(
                self._generate_ref_field("paperformat_id", paperformat_id, report_data)
            )

        return fields

    def _format_arch_content(self, arch: str) -> List[str]:
        """Format arch content with proper indentation.

        Args:
            arch: Raw arch XML content

        Returns:
            List of indented XML lines
        """
        lines = []
        arch_lines = arch.split("\n")
        for arch_line in arch_lines:
            if arch_line.strip():
                lines.append(f"      {arch_line}")

        return lines
