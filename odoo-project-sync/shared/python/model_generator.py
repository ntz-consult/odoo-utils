"""Model Python generator for Odoo Studio customizations.

Generates Python model files for Odoo models with Studio custom fields
and computed methods.
"""

from datetime import datetime
from typing import Any, Dict, List, Tuple

try:
    from .file_manager import FileManager
except ImportError:
    from file_manager import FileManager


class ModelGenerator:
    """Generator for Odoo model Python files."""

    def __init__(self, file_manager: FileManager):
        """Initialize model generator.

        Args:
            file_manager: FileManager instance for file operations
        """
        self.file_manager = file_manager

    def generate_content(self, model: str, fields: List[Dict[str, Any]]) -> str:
        """Generate Python model file content.

        Args:
            model: Model name (e.g., 'sale.order')
            fields: List of field dictionaries

        Returns:
            Python file content as string
        """
        class_name = self._model_to_class_name(model)
        timestamp = datetime.now().strftime("%Y-%m-%d")

        lines = [
            f"# Custom fields for {model}",
            f"# Extracted from Odoo Studio",
            f"# Last Updated: {timestamp}",
            "",
            "from odoo import models, fields, api",
            "",
            "",
            f"class {class_name}(models.Model):",
            f'    """Extended {model} model with Studio customizations."""',
            f"    _inherit = '{model}'",
            "",
        ]

        # Separate computed fields that need methods
        computed_methods = []

        for field in fields:
            field_lines, method_lines = self._generate_field_definition(field)
            lines.extend(field_lines)
            lines.append("")

            if method_lines:
                computed_methods.extend(method_lines)

        # Add computed methods
        if computed_methods:
            lines.extend(computed_methods)

        return "\n".join(lines)

    def _escape_python_string(self, text: str) -> str:
        """Escape special characters in Python string literals.
        
        Args:
            text: Text to escape
            
        Returns:
            Escaped text safe for Python string literals
        """
        if not isinstance(text, str):
            text = str(text)
        # Escape backslashes first, then quotes, then newlines and other special chars
        return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")

    def _generate_field_definition(self, field: Dict[str, Any]) -> Tuple[List[str], List[str]]:
        """Generate field definition lines.

        Args:
            field: Field data dictionary

        Returns:
            Tuple of (field_lines, method_lines)
        """
        field_lines = []
        method_lines = []

        field_name = field.get("name", "unknown_field")
        field_type = field.get("ttype", "char")
        string = field.get("field_description")
        compute_code = field.get("compute", "")  # Extract compute code if present

        # Map Studio field types to Odoo field types
        odoo_field_type = self._map_field_type(field_type)

        # Build field definition
        field_def = f"    {field_name} = fields.{odoo_field_type}("

        # Add parameters
        params = []
        if string:
            params.append(f'string="{self._escape_python_string(string)}"')

        # Add type-specific parameters
        if field_type == "boolean":
            default = field.get("default_value")
            if default is not None:
                params.append(f"default={str(default).lower()}")
        elif field_type in ["integer", "float"]:
            default = field.get("default_value")
            if default is not None:
                params.append(f"default={default}")
        elif field_type == "selection":
            selection = field.get("selection", [])
            if selection:
                params.append(f"selection={selection}")
        elif field_type == "many2one":
            relation = field.get("relation")
            if relation:
                params.append(f"comodel_name='{relation}'")
        elif field_type == "one2many":
            relation = field.get("relation")
            inverse_name = field.get("inverse_name")
            if relation and inverse_name:
                params.append(f"comodel_name='{relation}'")
                params.append(f"inverse_name='{inverse_name}'")
        elif field_type == "many2many":
            relation = field.get("relation")
            if relation:
                params.append(f"comodel_name='{relation}'")

        # Add common parameters
        if field.get("required"):
            params.append("required=True")
        if field.get("readonly"):
            params.append("readonly=True")
        if field.get("store") is False:
            params.append("store=False")
        if field.get("help"):
            params.append(f'help="{self._escape_python_string(field["help"])}"')

        # Handle computed fields
        if compute_code:
            params.append(f"compute='_compute_{field_name}'")
            # Generate compute method
            method_lines.extend(self._generate_compute_method(field_name, field))

        field_def += ", ".join(params)
        field_def += ")"

        field_lines.append(field_def)

        return field_lines, method_lines

    def _generate_compute_method(self, field_name: str, field_data: Dict[str, Any]) -> List[str]:
        """Generate compute method for computed field.

        Args:
            field_name: Field name
            field_data: Field data dictionary containing compute code and optional depends

        Returns:
            List of method lines
        """
        compute_code = field_data.get("compute", "")
        depends = field_data.get("depends", "")
        
        lines = [""]
        
        # Add @api.depends decorator if depends exists
        if depends:
            lines.append(f"    @api.depends('{depends}')")
        
        # Method signature
        lines.append(f"    def _compute_{field_name}(self):")
        lines.append(f'        """Compute {field_name} field."""')
        
        # Method body
        if compute_code and compute_code.strip():
            # Extract and indent the compute code properly
            code_lines = compute_code.split("\n")
            for code_line in code_lines:
                if code_line.strip():
                    lines.append(f"        {code_line.rstrip()}")
                else:
                    lines.append("")
        else:
            # No code - generate TODO placeholder
            lines.append("        for record in self:")
            lines.append(f"            # TODO: Implement computation for {field_name}")
            lines.append(f"            record.{field_name} = False")
        
        lines.append("")
        return lines

    def _map_field_type(self, studio_type: str) -> str:
        """Map Studio field type to Odoo field type.

        Args:
            studio_type: Studio field type

        Returns:
            Odoo field type
        """
        type_mapping = {
            "char": "Char",
            "text": "Text",
            "boolean": "Boolean",
            "integer": "Integer",
            "float": "Float",
            "date": "Date",
            "datetime": "Datetime",
            "selection": "Selection",
            "many2one": "Many2one",
            "one2many": "One2many",
            "many2many": "Many2many",
        }
        return type_mapping.get(studio_type, "Char")

    def _model_to_class_name(self, model: str) -> str:
        """Convert model name to class name.

        Args:
            model: Model name (e.g., 'sale.order')

        Returns:
            Class name (e.g., 'SaleOrder')
        """
        parts = model.split(".")
        return "".join(word.capitalize() for word in parts)
