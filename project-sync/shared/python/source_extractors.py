"""Source code extractors for Odoo modules.

Parses Odoo Python and XML files to extract components (fields, views, server
actions, etc.) for feature detection, similar to API-based extraction.
"""

import ast
import re
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


@dataclass
class SourceComponent:
    """A component extracted from source code."""

    id: int  # Generated sequential ID
    name: str
    display_name: str
    component_type: (
        str  # 'field', 'view', 'server_action', 'automation', 'report'
    )
    model: str
    complexity: str  # simple, medium, complex, very_complex
    raw_data: Dict[str, Any]
    file_path: str
    line_number: int
    is_studio: bool = False  # Always False for source code


class BaseSourceExtractor(ABC):
    """Base class for source code extractors."""

    def __init__(self, source_dir: Path):
        self.source_dir = source_dir
        self.components: List[SourceComponent] = []
        self.next_id = 1

    @abstractmethod
    def extract(self) -> List[SourceComponent]:
        """Extract components from source files."""
        pass

    def _get_next_id(self) -> int:
        """Get next sequential ID."""
        id_val = self.next_id
        self.next_id += 1
        return id_val

    def _find_files(self, extensions: List[str]) -> List[Path]:
        """Find all files with given extensions in source directory."""
        files = []
        for ext in extensions:
            files.extend(self.source_dir.rglob(f"*.{ext}"))
        return files


class SourceFieldExtractor(BaseSourceExtractor):
    """Extract field definitions from Python source files."""

    def extract(self) -> List[SourceComponent]:
        """Extract field components from Python files."""
        python_files = self._find_files(["py"])

        for file_path in python_files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                tree = ast.parse(content, filename=str(file_path))

                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        # Check if this is an Odoo model class
                        if self._is_odoo_model(node):
                            model_name = self._get_model_name(node)
                            if model_name:
                                fields = self._extract_fields_from_class(
                                    node, model_name, file_path
                                )
                                self.components.extend(fields)

            except (SyntaxError, UnicodeDecodeError) as e:
                print(f"Warning: Could not parse {file_path}: {e}")
                continue

        return self.components

    def _is_odoo_model(self, class_node: ast.ClassDef) -> bool:
        """Check if class inherits from Odoo Model."""
        for base in class_node.bases:
            if isinstance(base, ast.Attribute):
                # models.Model
                if (
                    isinstance(base.value, ast.Name)
                    and base.value.id == "models"
                    and base.attr
                    in ("Model", "TransientModel", "AbstractModel")
                ):
                    return True
            elif isinstance(base, ast.Name):
                # Could be aliased import
                pass
        return False

    def _get_model_name(self, class_node: ast.ClassDef) -> Optional[str]:
        """Extract model name from _name or _inherit attribute."""
        for node in class_node.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "_name":
                        if isinstance(
                            node.value, ast.Constant
                        ) and isinstance(node.value.value, str):
                            return node.value.value
                    elif (
                        isinstance(target, ast.Name)
                        and target.id == "_inherit"
                    ):
                        if isinstance(
                            node.value, ast.Constant
                        ) and isinstance(node.value.value, str):
                            return node.value.value
                        elif isinstance(node.value, ast.List):
                            # For multiple inheritance, take the first one
                            if (
                                node.value.elts
                                and isinstance(
                                    node.value.elts[0], ast.Constant
                                )
                                and isinstance(node.value.elts[0].value, str)
                            ):
                                return node.value.elts[0].value
        return None

    def _extract_fields_from_class(
        self, class_node: ast.ClassDef, model_name: str, file_path: Path
    ) -> List[SourceComponent]:
        """Extract field definitions from a model class."""
        fields = []

        for node in class_node.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        field_name = target.id
                        if field_name.startswith("_"):
                            continue  # Skip private attributes

                        if isinstance(node.value, ast.Call):
                            field_type = self._get_field_type(node.value)
                            if field_type:
                                complexity = self._infer_field_complexity(
                                    field_type, node.value
                                )
                                
                                # Extract string parameter for display name
                                display_name = self._extract_string_parameter(node.value)
                                if not display_name:
                                    display_name = field_name

                                component = SourceComponent(
                                    id=self._get_next_id(),
                                    name=field_name,
                                    display_name=display_name,
                                    component_type="field",
                                    model=model_name,
                                    complexity=complexity,
                                    raw_data={
                                        "field_type": field_type,
                                        "field_name": field_name,
                                        "model": model_name,
                                        "string": display_name,
                                        "ast_node": ast.dump(node),
                                    },
                                    file_path=str(file_path),
                                    line_number=node.lineno,
                                )
                                fields.append(component)

        return fields

    def _get_field_type(self, call_node: ast.Call) -> Optional[str]:
        """Extract field type from field instantiation."""
        if isinstance(call_node.func, ast.Attribute):
            field_type = call_node.func.attr
            # Common Odoo field types
            odoo_fields = {
                "Char",
                "Text",
                "Integer",
                "Float",
                "Boolean",
                "Date",
                "Datetime",
                "Selection",
                "Many2one",
                "One2many",
                "Many2many",
                "Binary",
                "Html",
                "Monetary",
                "Reference",
            }
            if field_type in odoo_fields:
                return field_type
        return None

    def _extract_string_parameter(self, call_node: ast.Call) -> Optional[str]:
        """Extract the string= parameter from a field definition.
        
        Args:
            call_node: AST Call node representing the field definition
            
        Returns:
            The string parameter value if found, None otherwise
        """
        for kwarg in call_node.keywords:
            if kwarg.arg == "string":
                # Handle string literals
                if isinstance(kwarg.value, ast.Constant) and isinstance(kwarg.value.value, str):
                    return kwarg.value.value
        return None

    def _infer_field_complexity(
        self, field_type: str, call_node: ast.Call
    ) -> str:
        """Infer field complexity based on type and parameters."""
        # Simple fields
        simple_fields = {
            "Char",
            "Integer",
            "Float",
            "Boolean",
            "Date",
            "Datetime",
        }
        if field_type in simple_fields:
            # Check for complex parameters
            for kwarg in call_node.keywords:
                if kwarg.arg in ["compute", "related", "store", "readonly"]:
                    return "medium"
            return "simple"

        # Medium complexity
        medium_fields = {"Text", "Selection", "Binary", "Monetary"}
        if field_type in medium_fields:
            return "medium"

        # Complex fields
        complex_fields = {
            "Many2one",
            "One2many",
            "Many2many",
            "Reference",
            "Html",
        }
        if field_type in complex_fields:
            return "complex"

        return "medium"


class SourceViewExtractor(BaseSourceExtractor):
    """Extract view definitions from XML files."""

    def extract(self) -> List[SourceComponent]:
        """Extract view components from XML files."""
        xml_files = self._find_files(["xml"])

        for file_path in xml_files:
            try:
                tree = ET.parse(file_path)
                root = tree.getroot()

                # Find all view elements
                for view_elem in root.findall(
                    ".//record[@model='ir.ui.view']"
                ):
                    view_data = self._parse_view_record(view_elem, file_path)
                    if view_data:
                        self.components.append(view_data)

            except ET.ParseError as e:
                print(f"Warning: Could not parse XML {file_path}: {e}")
                continue

        return self.components

    def _parse_view_record(
        self, view_elem: ET.Element, file_path: Path
    ) -> Optional[SourceComponent]:
        """Parse a view record element."""
        record_id = view_elem.get("id", "")
        view_type = "form"  # Default

        # Find field elements to determine model and complexity
        field_elements = view_elem.findall(".//field")
        if not field_elements:
            return None

        # Try to determine model from field names or context
        model_name = self._infer_model_from_view(view_elem)
        
        # Get the view name from the 'name' field (this is what matches TOML refs)
        view_name_elem = view_elem.find(".//field[@name='name']")
        view_name = view_name_elem.text if view_name_elem is not None and view_name_elem.text else record_id

        # Count fields and complexity indicators
        field_count = len(field_elements)
        has_groups = len(view_elem.findall(".//group")) > 0
        has_notebook = len(view_elem.findall(".//notebook")) > 0
        has_buttons = len(view_elem.findall(".//button")) > 0

        complexity = self._infer_view_complexity(
            field_count, has_groups, has_notebook, has_buttons
        )

        return SourceComponent(
            id=self._get_next_id(),
            name=view_name,  # Use view name for matching, not record ID
            display_name=view_name,  # Use same name for display (no prefix for matching)
            component_type="view",
            model=model_name,
            complexity=complexity,
            raw_data={
                "view_type": view_type,
                "record_id": record_id,
                "field_count": field_count,
                "has_groups": has_groups,
                "has_notebook": has_notebook,
                "has_buttons": has_buttons,
                "xml_content": ET.tostring(view_elem, encoding="unicode"),
            },
            file_path=str(file_path),
            line_number=0,  # XML doesn't have line numbers easily
        )

    def _infer_model_from_view(self, view_elem: ET.Element) -> str:
        """Try to infer model name from view content."""
        # Look for model field in the view record
        model_field = view_elem.find(".//field[@name='model']")
        if model_field is not None and model_field.text:
            return model_field.text

        # Look for field elements with model attribute (for relational fields)
        for field in view_elem.findall(".//field"):
            model = field.get("model")
            if model:
                return model

        # Look for ref attribute that might indicate model
        ref = view_elem.get("ref")
        if ref and "." in ref:
            return ref.split(".")[0]

        return "unknown"

    def _infer_view_complexity(
        self,
        field_count: int,
        has_groups: bool,
        has_notebook: bool,
        has_buttons: bool,
    ) -> str:
        """Infer view complexity."""
        score = field_count

        if has_groups:
            score += 5
        if has_notebook:
            score += 10
        if has_buttons:
            score += 3

        if score <= 10:
            return "simple"
        elif score <= 25:
            return "medium"
        elif score <= 50:
            return "complex"
        else:
            return "very_complex"


class SourceServerActionExtractor(BaseSourceExtractor):
    """Extract server action definitions from Python/XML files."""

    def extract(self) -> List[SourceComponent]:
        """Extract server action components."""
        # Server actions can be in Python methods or XML records
        python_files = self._find_files(["py"])
        xml_files = self._find_files(["xml"])

        # Extract from Python files
        for file_path in python_files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                tree = ast.parse(content, filename=str(file_path))

                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        if self._is_server_action_method(node):
                            component = self._parse_server_action_method(
                                node, file_path
                            )
                            if component:
                                self.components.append(component)

            except (SyntaxError, UnicodeDecodeError) as e:
                print(f"Warning: Could not parse {file_path}: {e}")
                continue

        # Extract from XML files (ir.actions.server records)
        for file_path in xml_files:
            try:
                tree = ET.parse(file_path)
                root = tree.getroot()

                for action_elem in root.findall(
                    ".//record[@model='ir.actions.server']"
                ):
                    component = self._parse_server_action_xml(
                        action_elem, file_path
                    )
                    if component:
                        self.components.append(component)

            except ET.ParseError as e:
                print(f"Warning: Could not parse XML {file_path}: {e}")
                continue

        return self.components

    def _is_server_action_method(self, func_node: ast.FunctionDef) -> bool:
        """Check if method looks like a server action."""
        # Look for decorators or naming patterns
        for decorator in func_node.decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id == "api.model":
                return True
            elif (
                isinstance(decorator, ast.Attribute)
                and decorator.attr == "model"
            ):
                return True

        # Check method name patterns
        if func_node.name.startswith(("action_", "server_action_")):
            return True

        return False

    def _parse_server_action_method(
        self, func_node: ast.FunctionDef, file_path: Path
    ) -> Optional[SourceComponent]:
        """Parse a server action method."""
        # Estimate complexity based on method length and constructs
        line_count = func_node.end_lineno - func_node.lineno
        has_loops = any(
            isinstance(n, (ast.For, ast.While)) for n in ast.walk(func_node)
        )
        has_conditionals = any(
            isinstance(n, ast.If) for n in ast.walk(func_node)
        )

        complexity = "simple"
        if line_count > 20 or has_loops or has_conditionals:
            complexity = "medium"
        if line_count > 50:
            complexity = "complex"

        return SourceComponent(
            id=self._get_next_id(),
            name=func_node.name,
            display_name=func_node.name,  # Use same name (no prefix for matching)
            component_type="server_action",
            model="ir.actions.server",  # Python methods don't have target model info
            complexity=complexity,
            raw_data={
                "method_name": func_node.name,
                "line_count": line_count,
                "has_loops": has_loops,
                "has_conditionals": has_conditionals,
                "ast_node": ast.dump(func_node),
            },
            file_path=str(file_path),
            line_number=func_node.lineno,
        )

    def _parse_server_action_xml(
        self, action_elem: ET.Element, file_path: Path
    ) -> Optional[SourceComponent]:
        """Parse server action from XML."""
        action_id = action_elem.get("id", "")
        action_name = action_elem.findtext(".//field[@name='name']", "")
        
        # Extract target model - try model_name first (standard field), then model_id
        target_model = "ir.actions.server"  # Default fallback
        
        # Try model_name field first (this is the standard Odoo field)
        model_name_elem = action_elem.find(".//field[@name='model_name']")
        if model_name_elem is not None and model_name_elem.text:
            target_model = model_name_elem.text.strip()
        else:
            # Fallback to model_id field (ref format)
            model_id_elem = action_elem.find(".//field[@name='model_id']")
            if model_id_elem is not None:
                model_ref = model_id_elem.get("ref", "")
                if model_ref:
                    # Extract model from ref like "model_res_partner" or "base.model_res_partner"
                    if "." in model_ref:
                        model_ref = model_ref.split(".", 1)[1]
                    if model_ref.startswith("model_"):
                        target_model = model_ref[6:].replace("_", ".")
                elif model_id_elem.text:
                    target_model = model_id_elem.text.strip()

        # Estimate complexity based on XML content
        xml_content = ET.tostring(action_elem, encoding="unicode")
        complexity = "medium" if len(xml_content) > 500 else "simple"

        return SourceComponent(
            id=self._get_next_id(),
            name=action_name or action_id,  # Prefer action name for matching
            display_name=action_name or action_id,  # Use same name (no prefix for matching)
            component_type="server_action",
            model=target_model,  # Use TARGET model, not ir.actions.server
            complexity=complexity,
            raw_data={
                "action_id": action_id,
                "action_name": action_name,
                "target_model": target_model,
                "xml_content": xml_content,
            },
            file_path=str(file_path),
            line_number=0,
        )


class SourceAutomationExtractor(BaseSourceExtractor):
    """Extract automation definitions from XML files."""

    def extract(self) -> List[SourceComponent]:
        """Extract automation components from XML files."""
        xml_files = self._find_files(["xml"])

        for file_path in xml_files:
            try:
                tree = ET.parse(file_path)
                root = tree.getroot()

                # Find base.automation records
                for auto_elem in root.findall(
                    ".//record[@model='base.automation']"
                ):
                    component = self._parse_automation_record(
                        auto_elem, file_path
                    )
                    if component:
                        self.components.append(component)

            except ET.ParseError as e:
                print(f"Warning: Could not parse XML {file_path}: {e}")
                continue

        return self.components

    def _parse_automation_record(
        self, auto_elem: ET.Element, file_path: Path
    ) -> Optional[SourceComponent]:
        """Parse an automation record."""
        auto_id = auto_elem.get("id", "")
        auto_name = auto_elem.findtext(".//field[@name='name']", "")

        # Extract target model - try model_name first (standard field), then model_id
        target_model = "base.automation"  # Default fallback
        
        # Try model_name field first (this is the standard Odoo field for automations)
        model_name_elem = auto_elem.find(".//field[@name='model_name']")
        if model_name_elem is not None and model_name_elem.text:
            target_model = model_name_elem.text.strip()
        else:
            # Fallback to model_id field (ref format)
            model_id_elem = auto_elem.find(".//field[@name='model_id']")
            if model_id_elem is not None:
                model_ref = model_id_elem.get("ref", "")
                if model_ref:
                    # Extract model from ref like "model_res_partner" or "base.model_res_partner"
                    if "." in model_ref:
                        model_ref = model_ref.split(".", 1)[1]
                    if model_ref.startswith("model_"):
                        target_model = model_ref[6:].replace("_", ".")
                elif model_id_elem.text:
                    target_model = model_id_elem.text.strip()

        # Estimate complexity
        xml_content = ET.tostring(auto_elem, encoding="unicode")
        complexity = "complex" if len(xml_content) > 1000 else "medium"

        return SourceComponent(
            id=self._get_next_id(),
            name=auto_name or auto_id,  # Prefer automation name for matching
            display_name=auto_name or auto_id,  # Use same name (no prefix for matching)
            component_type="automation",
            model=target_model,  # Use TARGET model, not base.automation
            complexity=complexity,
            raw_data={
                "automation_id": auto_id,
                "automation_name": auto_name,
                "target_model": target_model,
                "xml_content": xml_content,
            },
            file_path=str(file_path),
            line_number=0,
        )


class SourceReportExtractor(BaseSourceExtractor):
    """Extract report definitions from Python/XML files."""

    def extract(self) -> List[SourceComponent]:
        """Extract report components."""
        python_files = self._find_files(["py"])
        xml_files = self._find_files(["xml"])

        # Extract from Python files (report classes)
        for file_path in python_files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                tree = ast.parse(content, filename=str(file_path))

                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        if self._is_report_class(node):
                            component = self._parse_report_class(
                                node, file_path
                            )
                            if component:
                                self.components.append(component)

            except (SyntaxError, UnicodeDecodeError) as e:
                print(f"Warning: Could not parse {file_path}: {e}")
                continue

        # Extract from XML files (ir.actions.report records)
        for file_path in xml_files:
            try:
                tree = ET.parse(file_path)
                root = tree.getroot()

                for report_elem in root.findall(
                    ".//record[@model='ir.actions.report']"
                ):
                    component = self._parse_report_xml(report_elem, file_path)
                    if component:
                        self.components.append(component)

            except ET.ParseError as e:
                print(f"Warning: Could not parse XML {file_path}: {e}")
                continue

        return self.components

    def _is_report_class(self, class_node: ast.ClassDef) -> bool:
        """Check if class is a report class."""
        for base in class_node.bases:
            if isinstance(base, ast.Attribute):
                if (
                    isinstance(base.value, ast.Name)
                    and base.value.id in ("models", "report")
                    and "report" in base.attr.lower()
                ):
                    return True
        return False

    def _parse_report_class(
        self, class_node: ast.ClassDef, file_path: Path
    ) -> Optional[SourceComponent]:
        """Parse a report class."""
        report_name = class_node.name

        # Estimate complexity based on class size
        line_count = class_node.end_lineno - class_node.lineno
        complexity = "medium" if line_count > 30 else "simple"

        return SourceComponent(
            id=self._get_next_id(),
            name=report_name,
            display_name=report_name,  # Use same name (no prefix for matching)
            component_type="report",
            model="ir.actions.report",
            complexity=complexity,
            raw_data={
                "class_name": report_name,
                "line_count": line_count,
                "ast_node": ast.dump(class_node),
            },
            file_path=str(file_path),
            line_number=class_node.lineno,
        )

    def _parse_report_xml(
        self, report_elem: ET.Element, file_path: Path
    ) -> Optional[SourceComponent]:
        """Parse report from XML."""
        report_id = report_elem.get("id", "")
        report_name = report_elem.findtext(".//field[@name='name']", "")
        
        # Extract target model from model field (for matching with TOML refs)
        model_elem = report_elem.find(".//field[@name='model']")
        target_model = "ir.actions.report"  # Default fallback
        if model_elem is not None and model_elem.text:
            target_model = model_elem.text.strip()

        xml_content = ET.tostring(report_elem, encoding="unicode")
        complexity = "complex" if len(xml_content) > 800 else "medium"

        return SourceComponent(
            id=self._get_next_id(),
            name=report_name or report_id,  # Prefer report name for matching
            display_name=report_name or report_id,  # Use same name (no prefix for matching)
            component_type="report",
            model=target_model,  # Use TARGET model, not ir.actions.report
            complexity=complexity,
            raw_data={
                "report_id": report_id,
                "report_name": report_name,
                "target_model": target_model,
                "xml_content": xml_content,
            },
            file_path=str(file_path),
            line_number=0,
        )


def load_source_components(source_dir: Path) -> List[SourceComponent]:
    """Load all components from source code directory.

    Args:
        source_dir: Directory containing Odoo module source files

    Returns:
        List of SourceComponent objects
    """
    extractors = [
        SourceFieldExtractor(source_dir),
        SourceViewExtractor(source_dir),
        SourceServerActionExtractor(source_dir),
        SourceAutomationExtractor(source_dir),
        SourceReportExtractor(source_dir),
    ]

    all_components = []
    for extractor in extractors:
        components = extractor.extract()
        all_components.extend(components)

    return all_components
