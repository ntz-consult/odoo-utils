"""Generate Odoo module-based structure from extraction results (V1.1.2).

Organizes extracted Studio customizations into module-based folders (sales/,
inventory/, etc.) with enhanced generation features including clean XML,
computed methods, and report templates.
"""

import re
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from action_generator import ActionGenerator
from feature_detector import (
    Component,
    ComponentType,
    load_extraction_results,
)
from file_manager import FileManager
from model_generator import ModelGenerator
from module_mapper import ModuleMapper
from odoo_client import OdooClient
from report_generator import ReportGenerator
from utils import ensure_directory
from view_generator import ViewGenerator

try:
    from .qweb_resolver import QWebResolver
except ImportError:
    from qweb_resolver import QWebResolver


class ModuleGeneratorError(Exception):
    """Critical error that halts module generation."""

    pass


class ModuleGenerator:
    """Generate module-based structure from extracted components.

    Creates documentation-focused folder structure organized by Odoo modules:
    - {module}/models/: Python model files with field definitions
    - {module}/views/: XML view customizations
    - {module}/actions/: Server actions (Python) and automations (XML)
    - {module}/reports/: Report definitions and QWeb templates (XML)
    """

    def __init__(
        self,
        project_root: Path,
        model_module_map: Dict[str, str],
        odoo_client: OdooClient | None = None,
        dry_run: bool = False,
        file_manager: Optional[FileManager] = None,
    ):
        """Initialize generator (V1.1.3 - simplified).

        Args:
            project_root: Project root containing .odoo-sync/
            model_module_map: Dict mapping model names to module names (from module_model_map.toml)
            odoo_client: Optional Odoo client for re-fetching incomplete data
            dry_run: If True, log actions without writing files
            file_manager: Optional FileManager instance for file operations
        """
        self.project_root = project_root
        self.output_dir = project_root / "studio"  # Module folders go in studio/ subdirectory
        self.model_module_map = model_module_map  # ONLY truth is module_model_map.toml
        self.odoo_client = odoo_client
        self.dry_run = dry_run
        self.file_manager = file_manager or FileManager(project_root)
        self.model_generator = ModelGenerator(self.file_manager)
        self.view_generator = ViewGenerator(self.file_manager)
        self.action_generator = ActionGenerator(self.file_manager)
        self.report_generator = ReportGenerator(self.file_manager)
        self._errors: List[str] = []
        self._warnings: List[str] = []
        self._debug_logs: List[str] = []
        self._unmapped_views: List[str] = (
            []
        )  # Track views with no model for user input
        self._model_file_cache: Dict[str, Optional[str]] = (
            {}
        )  # Cache for model definition files

        # Initialize QWeb resolver for report template extraction
        self._qweb_resolver = QWebResolver(
            project_root=project_root,
            file_manager=self.file_manager,
            debug_logs=self._debug_logs,
        )
        
        # Path to feature_user_story_map.toml
        self._map_file = self.output_dir / "feature_user_story_map.toml"

    def _update_source_location(self, component: Component, filepath: Path) -> None:
        """Update source_location in feature_user_story_map.toml for a component.
        
        Builds the ref from the component and delegates to _update_source_location_by_ref.
        
        Args:
            component: Component that was just written to file
            filepath: Full path to the generated file
        """
        comp_ref = self._build_component_reference(component)
        self._update_source_location_by_ref(comp_ref, filepath)
    
    def _update_source_location_by_ref(self, comp_ref: str, filepath: Path) -> None:
        """Update source_location in feature_user_story_map.toml by component ref.
        
        Delegates to the shared utility function in utils.py.
        
        Args:
            comp_ref: Component reference string (e.g., "view.studio_customization.name")
            filepath: Full path to the generated file
        """
        if self.dry_run:
            return
            
        from utils import update_component_source_location
        update_component_source_location(
            comp_ref, 
            filepath, 
            self.project_root,
            map_file=self._map_file,
            warnings=self._warnings
        )

    def _build_component_reference(self, component: Component) -> str:
        """Build component reference string matching TOML format.
        
        Args:
            component: Component object
            
        Returns:
            Reference string like "field.sale_order.x_credit_limit"
        """
        type_prefix = component.component_type.value
        name = component.name or component.display_name
        
        if component.model:
            model_part = component.model.replace(".", "_")
            return f"{type_prefix}.{model_part}.{name}"
        
        return f"{type_prefix}.{name}"

    def _check_toml_duplicates(self) -> Dict[str, List[str]]:
        """Check feature_user_story_map.toml for duplicate component refs.
        
        Returns:
            Dict mapping duplicate refs to list of locations (feature/story names).
            Empty dict if no duplicates or TOML doesn't exist.
        """
        if not self._map_file.exists():
            return {}
        
        try:
            map_content = self._map_file.read_text(encoding="utf-8")
            map_data = tomllib.loads(map_content)
            
            ref_locations: Dict[str, List[str]] = {}
            
            for feature_name, feature_def in map_data.get("features", {}).items():
                user_stories = feature_def.get("user_stories", {})
                # Handle both dict format (new) and list format (legacy)
                if isinstance(user_stories, dict):
                    for story_name, story_data in user_stories.items():
                        location = f"{feature_name} / {story_name}"
                        
                        for comp in story_data.get("components", []):
                            if isinstance(comp, dict):
                                ref = comp.get("ref", "")
                            else:
                                ref = comp
                            
                            if ref:
                                ref_locations.setdefault(ref, []).append(location)
                else:
                    # Legacy list format
                    for story in user_stories:
                        story_desc = story.get("description", "Unknown")
                        location = f"{feature_name} / {story_desc}"
                        
                        for comp in story.get("components", []):
                            if isinstance(comp, dict):
                                ref = comp.get("ref", "")
                            else:
                                ref = comp
                            
                            if ref:
                                ref_locations.setdefault(ref, []).append(location)
            
            # Return only duplicates (refs that appear more than once)
            return {ref: locs for ref, locs in ref_locations.items() if len(locs) > 1}
            
        except Exception:
            return {}
    
    def _print_duplicate_error(self, duplicates: Dict[str, List[str]]) -> None:
        """Print a big red error message about duplicate components.
        
        Args:
            duplicates: Dict mapping duplicate refs to their locations
        """
        print("\n" + "=" * 70)
        print("❌ ERROR: DUPLICATE COMPONENTS DETECTED!")
        print("=" * 70)
        print()
        print("The following component refs appear multiple times in")
        print(f"feature_user_story_map.toml ({self._map_file}):")
        print()
        for ref, locations in duplicates.items():
            print(f"  🔴 {ref}")
            for loc in locations:
                print(f"      └─ {loc}")
            print()
        print("=" * 70)
        print("Please remove duplicates before running generate-modules.")
        print("Each component should appear in only ONE user story.")
        print("=" * 70 + "\n")

    def _get_module_for_model(
        self,
        model_name: str,
        custom_mappings: Optional[Dict[str, str]] = None,
    ) -> str:
        """Get module for a model (V1.1.3 with custom mapping support).

        Args:
            model_name: Model name
            custom_mappings: Optional user-provided custom model→module mappings (takes precedence)

        Returns:
            Module name if found, "unknown" otherwise
        """
        # Check custom mappings first (user overrides)
        if custom_mappings and model_name in custom_mappings:
            return custom_mappings[model_name]

        # Fall back to pre-validated map
        module = self.model_module_map.get(model_name)

        return module if module is not None else "unknown"

    def _build_report_name_to_module_mapping(
        self, custom_mappings: Optional[Dict[str, str]] = None
    ) -> Dict[str, Tuple[str, str]]:
        """Build mapping from report_name to (module, model).

        This mapping is used to determine which module a QWeb template
        should be placed in based on the report that uses it.

        Args:
            custom_mappings: Optional custom model→module mappings

        Returns:
            Dictionary mapping report_name to (module_name, model_name) tuples
        """
        # Build model→module map for the resolver
        model_module_map = {}
        for model_name in self.model_module_map.keys():
            model_module_map[model_name] = self._get_module_for_model(
                model_name, custom_mappings
            )
        
        return self._qweb_resolver.build_report_name_to_module_mapping(
            model_module_map
        )

    def _extract_tcall_references(self, arch_db: str) -> Set[str]:
        """Extract t-call template references from QWeb arch_db using regex.

        Args:
            arch_db: The arch_db XML content

        Returns:
            Set of template names referenced via t-call
        """
        return self._qweb_resolver.extract_tcall_references(arch_db)

    def _build_qweb_view_index(self) -> Dict[str, Dict[str, Any]]:
        """Build index of QWeb views by their key/name for quick lookup.

        Returns:
            Dictionary mapping view key/name to view data
        """
        return self._qweb_resolver.build_qweb_view_index()

    def _resolve_all_tcall_dependencies(
        self,
        root_template_key: str,
        qweb_index: Dict[str, Dict[str, Any]],
    ) -> Set[str]:
        """Resolve all transitive t-call dependencies for a template.

        Starting from a root template, finds all templates it calls
        directly and transitively.

        Args:
            root_template_key: The starting template key (e.g., report_name)
            qweb_index: Index of QWeb views by key/name

        Returns:
            Set of all template keys that are dependencies (including root)
        """
        return self._qweb_resolver.resolve_all_tcall_dependencies(
            root_template_key, qweb_index
        )

    def _find_model_from_report(self, view_name: str) -> Optional[str]:
        """Try to find model for a view by matching it to a report.

        Checks various name patterns:
        - View name might contain report_name (e.g., "ropeworx_label_donaghys")
        - View name might have studio_customization prefix

        Args:
            view_name: View name (e.g., "studio_customization.ropeworx_label_donaghys")

        Returns:
            Model name if found, None otherwise
        """
        return self._qweb_resolver.find_model_from_report(view_name)

    def generate_structure(
        self,
        components: List[Component],
        custom_model_mappings: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Main entry point - generate complete module-based structure.

        Args:
            components: List of Component objects from extraction
            custom_model_mappings: Optional user-provided custom model mappings

        Returns:
            Result dict with counts and errors

        Raises:
            ModuleGeneratorError: For critical errors that halt generation
        """
        if custom_model_mappings is None:
            custom_model_mappings = {}

        # Check for duplicate components in the TOML FIRST
        duplicates = self._check_toml_duplicates()
        if duplicates:
            self._print_duplicate_error(duplicates)
            raise ModuleGeneratorError(
                f"Cannot proceed: {len(duplicates)} duplicate component(s) found in feature_user_story_map.toml. "
                "Please remove duplicates before generating modules."
            )

        result = {
            "generated_at": datetime.now().isoformat(),
            "dry_run": self.dry_run,
            "modules": {},
            "files_created": {
                "models": 0,
                "views": 0,
                "server_actions": 0,
                "automations": 0,
                "reports": 0,
            },
            "errors": [],
            "warnings": [],
        }

        try:
            # Create timestamped backup ALWAYS
            backup_path = self._backup_existing_modules()
            if backup_path:
                result["backup_created"] = str(backup_path)

            # Determine required modules
            modules = self._determine_required_modules(
                components, custom_model_mappings
            )
            result["modules"] = list(modules)

            # Generate component files by module (directories created on-demand)
            result["files_created"]["models"] = self._generate_models(
                components, custom_model_mappings
            )
            result["files_created"]["views"] = self._generate_views(
                components, custom_model_mappings
            )
            server_count, auto_count = self._generate_actions(
                components, custom_model_mappings
            )
            result["files_created"]["server_actions"] = server_count
            result["files_created"]["automations"] = auto_count
            result["files_created"]["reports"] = self._generate_reports(
                components, custom_model_mappings
            )

            # Generate reports map documentation
            self._generate_reports_map(components, custom_model_mappings)

            # Cleanup empty directories
            removed_count = self._cleanup_empty_directories()
            if removed_count > 0:
                self._debug_logs.append(
                    f"Cleanup completed: {removed_count} empty directories removed"
                )

        except Exception as e:
            if isinstance(e, ModuleGeneratorError):
                raise
            raise ModuleGeneratorError(
                f"Unexpected error during generation: {e}"
            )

        result["errors"] = self._errors.copy()
        result["warnings"] = self._warnings.copy()
        result["unmapped_views"] = self._unmapped_views.copy()

        return result

    def _backup_existing_modules(self) -> Optional[Path]:
        """Create timestamped backup of existing module structure.

        Creates backup ALWAYS, even if no modules exist yet.
        Checks within the studio/ directory for existing modules.

        Returns:
            Path to backup folder, or None if nothing to backup
        """
        # If studio directory doesn't exist yet, nothing to backup
        if not self.output_dir.exists():
            self._debug_logs.append("No existing studio directory to backup")
            return None

        timestamp = datetime.now().strftime("%Y-%m-%d-%H:%M")
        backup_dir = self.output_dir / f"odoo-history-{timestamp}"

        # Check if there's anything to backup
        has_content = False
        for potential_module in self.output_dir.iterdir():
            if (
                potential_module.is_dir()
                and not potential_module.name.startswith(".")
            ):
                # Check if it looks like a module directory
                if any(
                    (potential_module / subdir).exists()
                    for subdir in ["models", "views", "actions", "reports"]
                ):
                    has_content = True
                    break

        if not has_content:
            self._debug_logs.append("No existing module structure to backup")
            return None

        if not self.dry_run:
            self.file_manager.ensure_directory(backup_dir)

            # Copy existing module directories
            for item in self.output_dir.iterdir():
                if (
                    item.is_dir()
                    and not item.name.startswith(".")
                    and not item.name.startswith("odoo-history-")
                ):
                    # Check if it looks like a module directory
                    if any(
                        (item / subdir).exists()
                        for subdir in ["models", "views", "actions", "reports"]
                    ):
                        self.file_manager.backup_directory(item, backup_dir)

        self._debug_logs.append(f"Created backup: {backup_dir.name}")
        return backup_dir

    def _determine_required_modules(
        self, components: List[Component], custom_mappings: Dict[str, str]
    ) -> Set[str]:
        """Determine which modules are needed based on components.

        Args:
            components: List of all components
            custom_mappings: Custom model→module mappings

        Returns:
            Set of module names needed
        """
        modules = set()

        for component in components:
            model = component.model
            if not model:
                modules.add("base")
                continue

            module = self._get_module_for_model(
                model, custom_mappings=custom_mappings
            )
            modules.add(module)

        return modules

    def _generate_models(
        self, components: List[Component], custom_mappings: Dict[str, str]
    ) -> int:
        """Generate Python model files grouped by module and model.

        Args:
            components: List of all components
            custom_mappings: Custom model→module mappings

        Returns:
            Number of model files generated
        """
        fields = [
            c for c in components if c.component_type == ComponentType.FIELD
        ]

        # Group by module → model → fields
        by_module_model: Dict[str, Dict[str, List[Component]]] = {}

        for field in fields:
            model = field.model
            if not model:
                self._errors.append(
                    f"Field {field.name} has no model, skipping"
                )
                continue

            module = self._get_module_for_model(
                model, custom_mappings=custom_mappings
            )

            by_module_model.setdefault(module, {}).setdefault(
                model, []
            ).append(field)

        # Generate files
        generated = 0
        for module, models_dict in by_module_model.items():
            for model, model_fields in models_dict.items():
                try:
                    filename = self._sanitize_model_name(model) + ".py"
                    filepath = self.output_dir / module / "models" / filename

                    content = self.model_generator.generate_content(
                        model, [field.raw_data for field in model_fields]
                    )

                    if not self.dry_run:
                        self.file_manager.write_text(filepath, content)
                        # Update source_location for each field
                        for field in model_fields:
                            self._update_source_location(field, filepath)

                    generated += 1
                except Exception as e:
                    self._errors.append(
                        f"Failed to generate model file for {model}: {e}"
                    )

        return generated

    def _generate_model_file_content(
        self, model: str, fields: List[Component]
    ) -> str:
        """Generate Python model file content with computed methods.

        Args:
            model: Model name (e.g., 'sale.order')
            fields: List of field components for this model

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
                computed_methods.append("")

        # Add computed methods at the end
        if computed_methods:
            for method_line in computed_methods:
                lines.append(method_line)

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

    def _generate_field_definition(
        self, field: Component
    ) -> Tuple[List[str], List[str]]:
        """Generate Python field definition with properties and optional
        compute method.

        Args:
            field: Field component

        Returns:
            Tuple of (field_lines, method_lines)
        """
        field_data = field.raw_data
        name = field_data.get("name", "")
        ttype = field_data.get("ttype", "char")
        complexity = field.complexity

        # Comment header
        lines = [
            f"    # Field: {name}",
            f"    # Type: {ttype.capitalize()} | Complexity: {complexity.capitalize()}",
        ]

        # Add help if present
        if field_data.get("help"):
            help_text = field_data["help"].replace("\n", " ")[:100]
            lines.append(f"    # Help: {help_text}")

        # Get properties to show
        properties = self._format_field_properties(field_data)

        # Field type mapping
        field_type = self._get_odoo_field_type(ttype)

        # Format field definition
        field_def = f"    {name} = fields.{field_type}("
        lines.append(field_def)

        # Add properties
        method_lines = []
        for prop_name, prop_value in properties.items():
            if isinstance(prop_value, str):
                prop_line = f'        {prop_name}="{self._escape_python_string(prop_value)}",'
            elif isinstance(prop_value, bool):
                prop_line = f"        {prop_name}={prop_value},"
            else:
                prop_line = f"        {prop_name}={repr(prop_value)},"
            lines.append(prop_line)

        # Add compute parameter if field has compute code
        if field_data.get("compute"):
            method_name = self._generate_compute_method_name(name)
            lines.append(f"        compute='{method_name}',")
            # Generate compute method
            method_lines = self._generate_compute_method(name, field_data)

        lines.append("    )")

        return lines, method_lines

    def _generate_compute_method(
        self, field_name: str, field_data: Dict[str, Any]
    ) -> List[str]:
        """Generate compute method with actual code from extraction.

        Args:
            field_name: Field name
            field_data: Field data dictionary

        Returns:
            List of lines for compute method
        """
        method_name = self._generate_compute_method_name(field_name)
        depends = field_data.get("depends", "")
        compute_code = field_data.get("compute", "")  # The actual method code

        lines = []

        # Add @api.depends decorator if depends exists
        if depends:
            lines.append(f"    @api.depends({repr(depends)})")

        # Method signature
        lines.append(f"    def {method_name}(self):")

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
            lines.append(
                f"            # TODO: Implement computation for {field_name}"
            )
            lines.append(f"            record.{field_name} = False")

        return lines

    def _format_field_properties(
        self, field_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract ONLY properties present in extraction data.

        Args:
            field_data: Raw field data from extraction

        Returns:
            Dictionary of properties to show in field definition
        """
        properties = {}

        # Always include string
        if "field_description" in field_data:
            properties["string"] = field_data["field_description"]

        # Only include if explicitly True
        for bool_prop in ["required", "readonly", "store", "copied"]:
            if field_data.get(bool_prop) is True:
                properties[bool_prop] = True

        # Note: 'compute' and 'depends' are excluded from properties
        # They are handled separately: compute= parameter and @api.depends decorator

        # Relational fields
        ttype = field_data.get("ttype")
        if ttype in ("many2one", "one2many", "many2many"):
            if field_data.get("relation"):
                properties["comodel_name"] = field_data["relation"]
            if ttype == "one2many" and field_data.get("relation_field"):
                properties["inverse_name"] = field_data["relation_field"]

        # Related fields
        if field_data.get("related"):
            properties["related"] = field_data["related"]

        # Domain (only if not empty)
        domain = field_data.get("domain")
        if domain and domain != "[]":
            properties["domain"] = domain

        # Help text
        if field_data.get("help"):
            properties["help"] = field_data["help"]

        # Default (if present)
        if "default" in field_data and field_data["default"]:
            properties["default"] = field_data["default"]

        # Monetary specific
        if ttype == "monetary" and field_data.get("currency_field"):
            properties["currency_field"] = field_data["currency_field"]

        # Selection (if present)
        if ttype == "selection" and field_data.get("selection_ids"):
            properties["selection"] = field_data["selection_ids"]

        return properties

    def _get_odoo_field_type(self, ttype: str) -> str:
        """Map Odoo ttype to fields.* class."""
        type_map = {
            "char": "Char",
            "text": "Text",
            "html": "Html",
            "integer": "Integer",
            "float": "Float",
            "monetary": "Monetary",
            "boolean": "Boolean",
            "date": "Date",
            "datetime": "Datetime",
            "binary": "Binary",
            "selection": "Selection",
            "many2one": "Many2one",
            "one2many": "One2many",
            "many2many": "Many2many",
        }
        return type_map.get(ttype, "Char")

    def _generate_views(
        self, components: List[Component], custom_mappings: Dict[str, str]
    ) -> int:
        """Generate XML view files with clean format (no CDATA).

        Note: QWeb views (type='qweb' with model=False) are skipped here
        as they are handled by _generate_reports to ensure proper module
        placement based on their associated report.

        Args:
            components: List of all components
            custom_mappings: Custom model→module mappings

        Returns:
            Number of view files generated
        """
        views = [
            c for c in components if c.component_type == ComponentType.VIEW
        ]

        generated = 0
        for view in views:
            try:
                # Skip QWeb views - they are handled by _generate_reports
                # QWeb views have type='qweb' and model=False (or empty)
                view_type = view.raw_data.get("type", "")
                view_model = view.raw_data.get("model")
                
                if view_type == "qweb" and (view_model is False or view_model == "" or view_model is None):
                    self._debug_logs.append(
                        f"Skipping QWeb view '{view.name}' - handled by report generation"
                    )
                    continue

                # Build component ref BEFORE potentially modifying view.model
                original_ref = self._build_component_reference(view)
                
                model = view.model

                # If no model, try to find it from reports (for module routing only)
                if not model:
                    model = self._find_model_from_report(view.name)
                    # Note: Don't update view.model - keep original for ref matching

                if not model:
                    # No model found, use "orphans" module
                    module = "orphans"
                else:
                    module = self._get_module_for_model(
                        model, custom_mappings=custom_mappings
                    )

                # Ensure complete arch_db
                arch_db = self._ensure_complete_arch_db(view)

                # Use actual Odoo Studio name for filename
                view_name = view.raw_data.get("name", f"view_{view.id}")
                filename = self._sanitize_filename(view_name) + ".xml"
                filepath = self.output_dir / module / "views" / filename

                content = self.view_generator.generate_content(view.raw_data, arch_db)

                if not self.dry_run:
                    self.file_manager.write_text(filepath, content)
                    self._update_source_location_by_ref(original_ref, filepath)

                generated += 1
            except Exception as e:
                self._errors.append(
                    f"Failed to generate view file for {view.name}: {e}"
                )

        return generated

    def _ensure_complete_arch_db(self, view_component: Component) -> str:
        """Ensure view has complete arch_db, re-fetching if needed."""
        arch_db = view_component.raw_data.get("arch_db", "")

        if arch_db and len(arch_db) > 50:
            return arch_db

        if not self.odoo_client:
            raise ModuleGeneratorError(
                f"View {view_component.name} (ID={view_component.id}) has incomplete arch_db "
                f"and no Odoo client available for re-fetching."
            )

        self._warnings.append(
            f"Re-fetching arch_db for view {view_component.name} (ID={view_component.id})"
        )

        try:
            result = self.odoo_client.read(
                model="ir.ui.view", ids=[view_component.id], fields=["arch_db"]
            )

            if not result or not result[0].get("arch_db"):
                raise ModuleGeneratorError(
                    f"Failed to re-fetch arch_db for view {view_component.name} (ID={view_component.id})"
                )

            arch_db = result[0]["arch_db"]
            view_component.raw_data["arch_db"] = arch_db
            return arch_db

        except Exception as e:
            raise ModuleGeneratorError(
                f"Re-fetch failed for view {view_component.name} (ID={view_component.id}): {e}"
            )

    def _generate_actions(
        self, components: List[Component], custom_mappings: Dict[str, str]
    ) -> Tuple[int, int]:
        """Generate server actions and automations.

        Returns:
            Tuple of (server_actions_count, automations_count)
        """
        server_count = self._generate_server_actions(
            components, custom_mappings
        )
        auto_count = self._generate_automations(components, custom_mappings)
        return server_count, auto_count

    def _generate_server_actions(
        self, components: List[Component], custom_mappings: Dict[str, str]
    ) -> int:
        """Generate server action Python files (only state='code')."""
        actions = [
            c
            for c in components
            if c.component_type == ComponentType.SERVER_ACTION
        ]
        generated = 0

        for action in actions:
            state = action.raw_data.get("state", "")

            if state != "code":
                self._debug_logs.append(
                    f"Skipping server action {action.name} (state={state}, not 'code')"
                )
                continue

            code = action.raw_data.get("code", "")
            if not code:
                self._errors.append(
                    f"Server action {action.name} has state='code' but no code content"
                )
                continue

            try:
                model = action.raw_data.get("model_name", "")
                if not model:
                    module = "orphans"
                else:
                    module = self._get_module_for_model(
                        model, custom_mappings=custom_mappings
                    )
                    if module == "unknown":
                        self._errors.append(
                            f"Could not determine module for server action {action.name}"
                        )
                        continue

                filename = self._sanitize_filename(action.name) + ".py"
                filepath = (
                    self.output_dir
                    / module
                    / "actions"
                    / "server_actions"
                    / filename
                )

                content = self.action_generator.generate_server_action_content(action.raw_data)

                if not self.dry_run:
                    self.file_manager.write_text(filepath, content)
                    self._update_source_location(action, filepath)

                generated += 1
            except Exception as e:
                self._errors.append(
                    f"Failed to generate server action file for {action.name}: {e}"
                )

        return generated

    def _generate_server_action_content(self, action: Component) -> str:
        """Generate Python server action file content."""
        action_data = action.raw_data
        timestamp = datetime.now().strftime("%Y-%m-%d")
        code = action_data.get("code", "")
        code_lines = len(code.split("\n"))

        lines = [
            f"# Action: {action_data.get('name', 'Unknown')}",
            f"# Model: {action_data.get('model_name', 'Unknown')}",
            f"# State: {action_data.get('state', 'code')}",
            f"# Complexity: {action.complexity.capitalize()}",
            f"# Extracted from Odoo Studio on {timestamp}",
            "",
            f"# Lines of code: {code_lines}",
            "",
            code,
        ]

        return "\n".join(lines)

    def _generate_automations(
        self, components: List[Component], custom_mappings: Dict[str, str]
    ) -> int:
        """Generate automation XML files with cleaned domains."""
        automations = [
            c
            for c in components
            if c.component_type == ComponentType.AUTOMATION
        ]
        generated = 0

        for automation in automations:
            try:
                model = automation.raw_data.get("model_name", "")
                if not model:
                    module = "orphans"
                else:
                    module = self._get_module_for_model(
                        model, custom_mappings=custom_mappings
                    )
                    if module == "unknown":
                        self._errors.append(
                            f"Could not determine module for automation {automation.name}"
                        )
                        continue

                filename = self._sanitize_filename(automation.name) + ".xml"
                filepath = (
                    self.output_dir
                    / module
                    / "actions"
                    / "automations"
                    / filename
                )

                content = self.action_generator.generate_automation_content(automation.raw_data)

                if not self.dry_run:
                    self.file_manager.write_text(filepath, content)
                    self._update_source_location(automation, filepath)

                generated += 1
            except Exception as e:
                self._errors.append(
                    f"Failed to generate automation file for {automation.name}: {e}"
                )

        return generated

    def _clean_filter_domain(self, domain: str) -> str:
        """Clean filter domain by replacing HTML entities.

        Args:
            domain: Raw domain string

        Returns:
            Cleaned domain string
        """
        # Replace &quot; with '
        return domain.replace("&quot;", "'")

    def _generate_reports(
        self, components: List[Component], custom_mappings: Dict[str, str]
    ) -> int:
        """Generate report XML files and extract all associated QWeb templates.

        This method now handles ALL QWeb template generation, including:
        - Main report templates referenced by report_name
        - All transitively called templates via t-call

        Templates are placed in the same module as their associated report,
        based on the report's model.

        Args:
            components: List of all components
            custom_mappings: Custom model→module mappings

        Returns:
            Number of report files generated (actions + templates)
        """
        reports = [
            c for c in components if c.component_type == ComponentType.REPORT
        ]
        generated = 0

        # Build mapping from report_name to (module, model)
        report_name_to_module = self._build_report_name_to_module_mapping(custom_mappings)

        # Build index of all QWeb views for dependency resolution
        qweb_index = self._build_qweb_view_index()

        # Track which templates have been generated to avoid duplicates
        generated_templates: Set[str] = set()

        for report in reports:
            try:
                model = report.raw_data.get("model", "")
                if not model:
                    module = "orphans"
                else:
                    module = self._get_module_for_model(
                        model, custom_mappings=custom_mappings
                    )
                    if module == "unknown":
                        self._errors.append(
                            f"Could not determine module for report {report.name}"
                        )
                        continue

                # Generate report action file
                filename = self._sanitize_filename(report.name) + ".xml"
                filepath = self.output_dir / module / "reports" / filename

                content = self.report_generator.generate_report_content(report.raw_data)

                if not self.dry_run:
                    self.file_manager.write_text(filepath, content)
                    self._update_source_location(report, filepath)

                generated += 1

                # Extract all QWeb templates for this report (including transitive deps)
                report_name = report.raw_data.get("report_name")
                if report_name:
                    templates_generated = self._extract_all_report_templates(
                        report_name, module, qweb_index, generated_templates
                    )
                    generated += templates_generated

            except Exception as e:
                self._errors.append(
                    f"Failed to generate report file for {report.name}: {e}"
                )

        # Generate orphan QWeb templates (those not referenced by any report)
        orphan_count = self._generate_orphan_qweb_templates(
            qweb_index, generated_templates, custom_mappings
        )
        generated += orphan_count

        return generated

    def _generate_orphan_qweb_templates(
        self,
        qweb_index: Dict[str, Dict[str, Any]],
        already_generated: Set[str],
        custom_mappings: Dict[str, str],
    ) -> int:
        """Generate orphan QWeb templates that are not referenced by any report.

        These are QWeb views (type='qweb', model=False) that exist in Odoo but
        have no report action pointing to them. They are placed in an 'orphans'
        module under the 'reports' subdirectory.

        Args:
            qweb_index: Index of QWeb views by key/name
            already_generated: Set of template keys already generated by reports
            custom_mappings: Custom model→module mappings

        Returns:
            Number of orphan templates generated
        """
        generated_count = 0

        for template_key, template_view in qweb_index.items():
            # Skip if already generated as part of a report
            if template_key in already_generated:
                continue

            # Only process QWeb views (type='qweb' with no model)
            view_type = template_view.get("type", "")
            view_model = template_view.get("model")
            if view_type != "qweb":
                continue
            if view_model and view_model is not False:
                continue

            # Generate to orphans module
            module = "orphans"

            template_name = template_view.get("name", template_key)
            if "." in template_name:
                filename_base = template_name.split(".")[-1]
            else:
                filename_base = template_name

            filename = f"{self._sanitize_filename(filename_base)}_template.xml"
            filepath = self.output_dir / module / "reports" / filename

            try:
                content = self.report_generator.generate_template_content(template_view)

                if not self.dry_run:
                    self.file_manager.write_text(filepath, content)
                    # Build component ref for source_location update
                    view_name = template_view.get("name", "")
                    if view_name:
                        comp_ref = f"view.{view_name}"
                        self._update_source_location_by_ref(comp_ref, filepath)

                already_generated.add(template_key)
                generated_count += 1
                self._debug_logs.append(
                    f"Generated orphan QWeb template '{template_name}' in module '{module}'"
                )
            except Exception as e:
                self._errors.append(
                    f"Failed to generate orphan QWeb template {template_name}: {e}"
                )

        return generated_count

    def _extract_all_report_templates(
        self,
        report_name: str,
        module: str,
        qweb_index: Dict[str, Dict[str, Any]],
        already_generated: Set[str],
    ) -> int:
        """Extract all QWeb templates for a report, including transitive t-call dependencies.

        All templates are placed in the same module as the report, maintaining
        logical organization and preventing module dependency issues.

        Args:
            report_name: Report name (e.g., 'studio_customization.ropeworx_label_packaging_sml')
            module: Module to place templates in (based on report's model)
            qweb_index: Index of QWeb views by key/name
            already_generated: Set of template keys already generated (to avoid duplicates)

        Returns:
            Number of templates generated
        """
        # Find all templates this report needs (including transitive deps)
        all_templates = self._resolve_all_tcall_dependencies(report_name, qweb_index)

        generated_count = 0

        for template_key in all_templates:
            # Skip if already generated (by this or another report)
            if template_key in already_generated:
                continue

            # Get template view data
            template_view = qweb_index.get(template_key)
            if not template_view:
                self._debug_logs.append(
                    f"Template '{template_key}' not found in QWeb index (may be core Odoo template)"
                )
                continue

            # Generate template file
            # Use the name from the template view, falling back to key
            template_name = template_view.get("name", template_key)
            if "." in template_name:
                # Use last part for filename (e.g., "studio_customization.xyz" -> "xyz")
                filename_base = template_name.split(".")[-1]
            else:
                filename_base = template_name

            filename = f"{self._sanitize_filename(filename_base)}_template.xml"
            filepath = self.output_dir / module / "reports" / filename

            content = self.report_generator.generate_template_content(template_view)

            if not self.dry_run:
                self.file_manager.write_text(filepath, content)
                # Build component ref for source_location update
                # QWeb views use format: view.{name}
                view_name = template_view.get("name", "")
                if view_name:
                    comp_ref = f"view.{view_name}"
                    self._update_source_location_by_ref(comp_ref, filepath)

            already_generated.add(template_key)
            generated_count += 1
            self._debug_logs.append(
                f"Generated QWeb template '{template_name}' in module '{module}'"
            )

        return generated_count

    def _generate_reports_map(
        self, components: List[Component], custom_mappings: Dict[str, str]
    ) -> None:
        """Generate reports_map.md showing report-to-QWeb template hierarchy.

        Creates a markdown document in the studio folder that documents all
        reports and their associated QWeb templates with t-call dependencies.

        Args:
            components: List of all components
            custom_mappings: Custom model→module mappings
        """
        reports = [
            c for c in components if c.component_type == ComponentType.REPORT
        ]

        if not reports:
            return

        # Build QWeb view index for dependency resolution
        qweb_index = self._build_qweb_view_index()

        # Group reports by module
        reports_by_module: Dict[str, List[Dict[str, Any]]] = {}

        for report in reports:
            model = report.raw_data.get("model", "")
            if model:
                module = self._get_module_for_model(model, custom_mappings)
                if module == "unknown":
                    module = "orphans"
            else:
                module = "orphans"

            report_info = {
                "name": report.name,
                "display_name": report.display_name,
                "model": model,
                "report_name": report.raw_data.get("report_name", ""),
                "report_type": report.raw_data.get("report_type", ""),
            }

            if module not in reports_by_module:
                reports_by_module[module] = []
            reports_by_module[module].append(report_info)

        # Generate markdown content
        lines = [
            "# Reports Map",
            "",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "This document shows all reports and their associated QWeb templates,",
            "including transitive t-call dependencies.",
            "",
            "---",
            "",
        ]

        # Process each module
        for module in sorted(reports_by_module.keys()):
            module_reports = reports_by_module[module]

            lines.append(f"## {module.upper()}")
            lines.append("")

            for report_info in sorted(module_reports, key=lambda x: x["name"]):
                report_name = report_info["report_name"]
                lines.append(f"### {report_info['name']}")
                lines.append("")
                lines.append(f"- **Model:** `{report_info['model']}`")
                lines.append(f"- **Report Name:** `{report_name}`")
                lines.append(f"- **Type:** {report_info['report_type']}")
                lines.append(f"- **Output Folder:** `studio/{module}/reports/`")
                lines.append("")

                # Build template hierarchy
                if report_name:
                    template_tree = self._build_template_tree(report_name, qweb_index)
                    if template_tree:
                        lines.append("**QWeb Templates:**")
                        lines.append("")
                        lines.extend(self._format_template_tree(template_tree, 0, module))
                        lines.append("")
                    else:
                        lines.append("*No custom QWeb templates (uses Odoo core templates)*")
                        lines.append("")

                lines.append("---")
                lines.append("")

        # Write the file
        filepath = self.output_dir / "reports_map.md"
        content = "\n".join(lines)

        if not self.dry_run:
            self.file_manager.write_text(filepath, content)
            self._debug_logs.append(f"Generated reports_map.md with {len(reports)} reports")

    def _build_template_tree(
        self,
        template_key: str,
        qweb_index: Dict[str, Dict[str, Any]],
        visited: Optional[Set[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Build a tree structure of template dependencies.

        Args:
            template_key: The template key to start from
            qweb_index: Index of QWeb views by key/name
            visited: Set of already visited templates (to prevent cycles)

        Returns:
            Dict with template info and children, or None if not found
        """
        if visited is None:
            visited = set()

        if template_key in visited:
            return None  # Prevent cycles

        visited.add(template_key)

        template_view = qweb_index.get(template_key)
        if not template_view:
            return None  # Not a custom template

        # Get t-call references from this template
        arch_db = template_view.get("arch_db", "")
        tcalls = self._extract_tcall_references(arch_db)

        # Build children recursively
        children = []
        for tcall in sorted(tcalls):
            child_tree = self._build_template_tree(tcall, qweb_index, visited.copy())
            if child_tree:
                children.append(child_tree)

        return {
            "key": template_key,
            "name": template_view.get("name", template_key),
            "children": children,
        }

    def _format_template_tree(
        self,
        tree: Dict[str, Any],
        indent: int,
        module: str,
    ) -> List[str]:
        """Format a template tree as markdown lines.

        Args:
            tree: Template tree dict from _build_template_tree
            indent: Current indentation level
            module: Module name for file path

        Returns:
            List of formatted markdown lines
        """
        lines = []
        prefix = "  " * indent

        # Get filename for this template
        template_name = tree["name"]
        if "." in template_name:
            filename_base = template_name.split(".")[-1]
        else:
            filename_base = template_name
        filename = f"{self._sanitize_filename(filename_base)}_template.xml"

        # Format the line
        if indent == 0:
            lines.append(f"{prefix}- **`{tree['name']}`**")
        else:
            lines.append(f"{prefix}- `{tree['name']}` *(called by parent)*")

        lines.append(f"{prefix}  - File: `studio/{module}/reports/{filename}`")

        # Process children
        for child in tree["children"]:
            lines.extend(self._format_template_tree(child, indent + 1, module))

        return lines

    def _extract_report_template(self, report_name: str, module: str) -> bool:
        """DEPRECATED: Extract QWeb template from views_metadata.json.

        This method is kept for backward compatibility but is no longer used.
        Use _extract_all_report_templates instead.

        Args:
            report_name: Report name (e.g., 'sale.report_custom_quote')
            module: Module to place template in

        Returns:
            True if template was extracted, False otherwise
        """
        # Parse report_name to get template name
        if "." in report_name:
            template_name = report_name.split(".", 1)[1]
        else:
            template_name = report_name

        # Search for matching template in views_metadata
        template_view = None
        for view_data in self._qweb_resolver.views_metadata.values():
            if (
                view_data.get("name") == template_name
                or view_data.get("key") == report_name
            ):
                template_view = view_data
                break

        if not template_view:
            self._debug_logs.append(
                f"Report template '{template_name}' not found in views_metadata"
            )
            return False

        # Generate template file
        filename = f"{template_name}_template.xml"
        filepath = self.output_dir / module / "reports" / filename

        content = self.report_generator.generate_template_content(template_view)

        if not self.dry_run:
            self.file_manager.write_text(filepath, content)

        return True

    def _generate_template_content(self, template_view: Dict[str, Any]) -> str:
        """Generate QWeb template XML content.

        Args:
            template_view: Template view data from views_metadata

        Returns:
            XML file content as string
        """
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            "<odoo>",
            "  <data>",
        ]

        template_id = template_view.get(
            "xml_id", template_view.get("key", "template")
        )
        lines.append(f'    <template id="{template_id}">')

        # Get arch content
        arch = template_view.get("arch_db", "")
        if arch:
            arch_lines = arch.split("\n")
            for arch_line in arch_lines:
                if arch_line.strip():
                    lines.append(f"      {arch_line}")

        lines.append("    </template>")
        lines.append("  </data>")
        lines.append("</odoo>")

        return True

    # Helper methods

    def _sanitize_filename(self, name: str) -> str:
        """Convert name to valid filename."""
        sanitized = name.replace(" ", "_").replace("/", "_")
        sanitized = re.sub(r'[<>:"/\\|?*]', "", sanitized)
        sanitized = sanitized.strip("._")
        sanitized = sanitized.lower()

        if len(sanitized) > 200:
            sanitized = sanitized[:200]

        if not sanitized:
            sanitized = "unnamed"

        return sanitized

    def _sanitize_model_name(self, model: str) -> str:
        """Convert model name to filename (sale.order -> sale_order)."""
        return model.replace(".", "_")

    def _model_to_class_name(self, model: str) -> str:
        """Convert to Python class name (sale.order -> SaleOrder)."""
        parts = model.split(".")
        return "".join(p.capitalize() for p in parts)

    def _generate_xml_id(self, name: str) -> str:
        """Generate XML ID from name."""
        xml_id = self._sanitize_filename(name)
        xml_id = xml_id.replace(".", "_")
        return xml_id

    def _escape_xml(self, text: str) -> str:
        """Escape XML special characters."""
        if not text:
            return text
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    def _find_model_file(self, model_name: str) -> Optional[str]:
        """Find file where model is defined, with caching.

        Uses grep-equivalent regex search to find _name = 'model_name' definition.

        Args:
            model_name: Model name (e.g., 'stock.quant')

        Returns:
            File path where model is defined, or None if not found
        """
        if model_name in self._model_file_cache:
            return self._model_file_cache[model_name]

        # V1.1.3: Model file lookup removed (not needed for simplified workflow)
        result = None
        self._model_file_cache[model_name] = result

        return result

    def _get_module_with_file_info(
        self,
        model_name: str,
        component_desc: str,
        custom_mappings: Optional[Dict[str, str]] = None,
    ) -> str:
        """Get module for model with enhanced error messages including file
        paths.

        Args:
            model_name: Model name to look up
            component_desc: Description of component using this model (for error messages)
            custom_mappings: Optional custom model mappings

        Returns:
            Module name if found, "unknown" otherwise
        """
        return self._get_module_for_model(
            model_name, custom_mappings=custom_mappings
        )

    def _generate_compute_method_name(self, field_name: str) -> str:
        """Generate valid Python method name for computed field.

        Follows Odoo convention: _compute_{field_name}

        Args:
            field_name: Name of the field

        Returns:
            Valid Python method name
        """
        if field_name.startswith("_compute_"):
            return field_name

        method_name = f"_compute_{field_name}"

        # Ensure valid Python identifier
        if not method_name.isidentifier():
            method_name = re.sub(r"[^a-zA-Z0-9_]", "_", method_name)

        return method_name

    def _resolve_inherit_view_xml_id(
        self, inherit_id: int, view_name: str
    ) -> str:
        """Resolve XML ID for inherited view.

        Strategies:
        1. Check views_metadata cache
        2. Query Odoo database if client available
        3. Fallback to 'unknown.view'

        Args:
            inherit_id: Numeric ID of inherited view
            view_name: Name of current view (for logging)

        Returns:
            XML ID string (e.g., 'sale.view_order_form' or 'unknown.view')
        """
        # Strategy 1: Cache
        if inherit_id in self._qweb_resolver.views_metadata:
            cached_view = self._qweb_resolver.views_metadata[inherit_id]
            xml_id = cached_view.get("xml_id")
            if xml_id:
                self._debug_logs.append(
                    f"Resolved inherited view ID {inherit_id} to '{xml_id}' from cache"
                )
                return xml_id

        # Strategy 2: Database query
        if self.odoo_client:
            try:
                self._warnings.append(
                    f"Re-fetching XML ID for inherited view {inherit_id} (view: {view_name})"
                )

                result = self.odoo_client.read(
                    model="ir.ui.view",
                    ids=[inherit_id],
                    fields=["xml_id", "key"],
                )

                if result and len(result) > 0:
                    view_data = result[0]
                    xml_id = view_data.get("xml_id") or view_data.get("key")

                    if xml_id:
                        self._debug_logs.append(
                            f"Resolved inherited view ID {inherit_id} to '{xml_id}' via database"
                        )
                        return xml_id

            except Exception as e:
                self._warnings.append(
                    f"Failed to resolve inherited view ID {inherit_id}: {e}"
                )

        # Strategy 3: Fallback
        self._warnings.append(
            f"Could not resolve inherited view ID {inherit_id} for '{view_name}' - using 'unknown.view'"
        )
        return "unknown.view"

    def _cleanup_empty_directories(self) -> int:
        """Remove empty subdirectories after generation completes.

        Returns:
            Number of directories removed
        """
        removed_count = 0

        for module_dir in self.output_dir.iterdir():
            if not module_dir.is_dir() or module_dir.name.startswith("."):
                continue
            if module_dir.name.startswith("odoo-history-"):
                continue

            # Walk bottom-up to remove empty dirs
            for dirpath in sorted(module_dir.rglob("*"), reverse=True):
                if not dirpath.is_dir():
                    continue

                try:
                    if not any(dirpath.iterdir()):
                        if not self.dry_run:
                            dirpath.rmdir()
                        self._debug_logs.append(
                            f"Cleanup: Removed empty directory {dirpath}"
                        )
                        removed_count += 1
                except OSError:
                    pass

        return removed_count
