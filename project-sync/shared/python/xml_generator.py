"""Base XML generator for Odoo Studio customizations.

Provides common XML generation patterns and utilities for all XML-based
generators (views, actions, reports, etc.).
"""

import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List

try:
    from .file_manager import FileManager
except ImportError:
    from file_manager import FileManager


class XmlGenerator(ABC):
    """Base class for XML content generators.

    Provides common XML generation utilities and enforces a consistent
    interface for all XML generators.
    """

    def __init__(self, file_manager: FileManager):
        """Initialize XML generator.

        Args:
            file_manager: FileManager instance for file operations
        """
        self.file_manager = file_manager

    @abstractmethod
    def generate_content(self, data: Dict[str, Any], **kwargs) -> str:
        """Generate XML content for the specific component type.

        Args:
            data: Component data dictionary
            **kwargs: Additional arguments specific to the generator

        Returns:
            XML content as string
        """
        pass

    def _generate_xml_id(self, name: str) -> str:
        """Generate XML ID from name.

        Args:
            name: Base name for the XML ID

        Returns:
            Valid XML ID string
        """
        xml_id = self._sanitize_filename(name)
        xml_id = xml_id.replace(".", "_")
        return xml_id

    def _escape_xml(self, text: str) -> str:
        """Escape XML special characters.

        Args:
            text: Text to escape

        Returns:
            XML-escaped text
        """
        if not text:
            return text
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    def _sanitize_filename(self, name: str) -> str:
        """Convert name to valid filename.

        Args:
            name: Name to sanitize

        Returns:
            Valid filename string
        """
        sanitized = name.replace(" ", "_").replace("/", "_")
        sanitized = re.sub(r'[<>:"/\\|?*]', "", sanitized)
        sanitized = sanitized.strip("._")
        sanitized = sanitized.lower()

        if len(sanitized) > 200:
            sanitized = sanitized[:200]

        if not sanitized:
            sanitized = "unnamed"

        return sanitized

    def _generate_xml_header(self, timestamp: str = None) -> List[str]:
        """Generate standard XML header lines.

        Args:
            timestamp: Optional timestamp for comments

        Returns:
            List of XML header lines
        """
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d")

        return [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f"<!-- Generated on {timestamp} -->",
            "<odoo>",
            "  <data>",
        ]

    def _generate_xml_footer(self) -> List[str]:
        """Generate standard XML footer lines.

        Returns:
            List of XML footer lines
        """
        return [
            "  </data>",
            "</odoo>",
        ]

    def _generate_record_element(
        self, xml_id: str, model: str, fields: List[str]
    ) -> List[str]:
        """Generate a complete record element.

        Args:
            xml_id: XML ID for the record
            model: Odoo model name
            fields: List of field XML strings

        Returns:
            List of XML lines for the record
        """
        lines = [
            f'    <record id="{xml_id}" model="{model}">',
        ]

        lines.extend(fields)

        lines.append("    </record>")

        return lines

    def _generate_field_element(
        self, name: str, value: str, field_type: str = None
    ) -> str:
        """Generate a field element.

        Args:
            name: Field name
            value: Field value
            field_type: Optional field type

        Returns:
            XML field element string
        """
        if field_type:
            return f'      <field name="{name}" type="{field_type}">{value}</field>'
        else:
            return f'      <field name="{name}">{value}</field>'

    # Template Methods for Common Patterns

    def _generate_standard_record_xml(
        self,
        data: Dict[str, Any],
        model: str,
        xml_id_prefix: str = "",
        field_generators: List[callable] = None
    ) -> str:
        """Template method for generating standard record XML.

        Args:
            data: Component data dictionary
            model: Odoo model name
            xml_id_prefix: Prefix for XML ID generation
            field_generators: List of functions that generate field XML

        Returns:
            Complete XML content as string
        """
        lines = self._generate_xml_header()

        # Generate XML ID
        xml_id = self._generate_xml_id(
            f"{xml_id_prefix}_{data.get('name', data.get('id', 'unknown'))}"
            if xml_id_prefix else
            data.get('name', f"record_{data.get('id', 'unknown')}")
        )

        # Generate field elements
        field_lines = []
        if field_generators:
            for generator in field_generators:
                field_lines.extend(generator(data))

        record_lines = self._generate_record_element(xml_id, model, field_lines)
        lines.extend(record_lines)

        lines.extend(self._generate_xml_footer())

        return "\n".join(lines)

    def _generate_arch_field(
        self,
        arch_content: str,
        indentation: str = "        "
    ) -> List[str]:
        """Template method for generating arch field XML.

        Args:
            arch_content: Raw arch XML content
            indentation: Indentation string for arch content

        Returns:
            List of XML lines for the arch field
        """
        lines = ['      <field name="arch" type="xml">']
        
        arch_lines = arch_content.split("\n")
        for arch_line in arch_lines:
            if arch_line.strip():
                lines.append(f"{indentation}{arch_line}")
        
        lines.append("      </field>")
        return lines

    def _generate_common_fields(
        self,
        data: Dict[str, Any],
        field_mappings: Dict[str, str] = None
    ) -> List[str]:
        """Template method for generating common field elements.

        Args:
            data: Component data dictionary
            field_mappings: Optional mapping of data keys to field names

        Returns:
            List of field XML strings
        """
        fields = []
        mappings = field_mappings or {}

        # Common fields that might exist
        common_fields = ['name', 'model', 'model_name', 'active', 'sequence', 'priority']

        for field_name in common_fields:
            data_key = mappings.get(field_name, field_name)
            value = data.get(data_key)

            if value is not None:
                if isinstance(value, bool):
                    value = str(value).lower()
                elif not isinstance(value, str):
                    value = str(value)

                fields.append(
                    self._generate_field_element(field_name, self._escape_xml(value))
                )

        return fields

    def _generate_ref_field(
        self,
        field_name: str,
        ref_value: str,
        data: Dict[str, Any]
    ) -> str:
        """Template method for generating reference field elements.

        Args:
            field_name: Name of the field
            ref_value: Reference value or key to look up in data
            data: Component data dictionary

        Returns:
            Field XML string
        """
        value = data.get(ref_value) if isinstance(ref_value, str) and ref_value in data else ref_value
        if value:
            return self._generate_field_element(field_name, str(value), "ref")
        return ""
