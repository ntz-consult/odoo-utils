"""QWeb Template Resolver - Resolve QWeb views and their dependencies.

Provides shared functionality for resolving QWeb templates, their transitive
dependencies (via t-call), and mapping them to reports and models.

Used by both module_generator and feature_user_story_map_generator to avoid
code duplication.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from .file_manager import FileManager
except ImportError:
    from file_manager import FileManager


class QWebResolver:
    """Resolve QWeb templates and their dependencies for reports.
    
    This class provides methods to:
    - Load views metadata and reports data from extraction results
    - Build mappings between report names and models
    - Resolve transitive t-call dependencies between QWeb templates
    - Find which report a QWeb view belongs to
    """

    def __init__(
        self,
        project_root: Path,
        file_manager: Optional[FileManager] = None,
        debug_logs: Optional[List[str]] = None,
    ):
        """Initialize QWeb resolver.
        
        Args:
            project_root: Project root directory
            file_manager: Optional FileManager instance
            debug_logs: Optional list to append debug messages to
        """
        self.project_root = Path(project_root)
        self.file_manager = file_manager or FileManager(project_root)
        self.debug_logs = debug_logs if debug_logs is not None else []
        
        # Load data files
        self._views_metadata = self._load_views_metadata()
        self._reports_data = self._load_reports_data()
        self._report_name_to_model = self._build_report_name_mapping()

    def _load_views_metadata(self) -> Dict[int, Dict[str, Any]]:
        """Load views_metadata.json for report template extraction.

        Returns:
            Dictionary mapping view IDs to view data
        """
        metadata_file = (
            self.project_root
            / ".odoo-sync"
            / "data"
            / "extraction-results"
            / "views_metadata.json"
        )
        if not self.file_manager.exists(metadata_file):
            self.debug_logs.append(
                f"Views metadata file not found: {metadata_file}"
            )
            return {}

        try:
            data = self.file_manager.read_json(metadata_file)

            # Handle both formats: {"records": [...]} and {id: {...}}
            views_list = []
            if isinstance(data, dict) and "records" in data:
                views_list = data["records"]
            elif isinstance(data, list):
                views_list = data
            elif isinstance(data, dict):
                # Legacy format: {id: view_data, ...}
                result = {}
                for key, value in data.items():
                    try:
                        int_key = int(key)
                        result[int_key] = value
                    except (ValueError, TypeError):
                        continue
                return result
            
            # Convert list to dict mapping view IDs
            result = {}
            for view_data in views_list:
                view_id = view_data.get("id")
                if view_id:
                    result[view_id] = view_data

            return result
        except Exception as e:
            self.debug_logs.append(f"Error loading views metadata: {e}")
            return {}

    def _load_reports_data(self) -> List[Dict[str, Any]]:
        """Load reports_output.json for view→model resolution.

        Returns:
            List of report records
        """
        # Try extraction-results first, then extracted folder
        possible_locations = [
            self.project_root
            / ".odoo-sync"
            / "data"
            / "extraction-results"
            / "reports_output.json",
            self.project_root
            / ".odoo-sync"
            / "data"
            / "extracted"
            / "reports_output.json",
            self.project_root
            / "tests"
            / "fixtures"
            / "extraction_samples"
            / "reports_output.json",
        ]

        for reports_file in possible_locations:
            if not self.file_manager.exists(reports_file):
                continue

            try:
                data = self.file_manager.read_json(reports_file)

                # Handle both formats: {"records": [...]} and [...]
                if isinstance(data, dict) and "records" in data:
                    self.debug_logs.append(
                        f"Loaded {len(data['records'])} reports from {reports_file.name}"
                    )
                    return data["records"]
                elif isinstance(data, list):
                    self.debug_logs.append(
                        f"Loaded {len(data)} reports from {reports_file.name}"
                    )
                    return data
            except Exception as e:
                self.debug_logs.append(
                    f"Error loading reports from {reports_file}: {e}"
                )
                continue

        self.debug_logs.append(
            "No reports data found - view→model resolution from reports won't be available"
        )
        return []

    def _build_report_name_mapping(self) -> Dict[str, str]:
        """Build mapping from report name patterns to models.

        Creates multiple lookup keys for each report:
        - Full report_name (e.g., "sale.report_custom_quote")
        - Report name without module prefix (e.g., "report_custom_quote")
        - View-style name patterns that might match

        Returns:
            Dictionary mapping report name patterns to models
        """
        mapping = {}

        for report in self._reports_data:
            model = report.get("model")
            report_name = report.get("report_name")

            if not model or not report_name:
                continue

            # Full report_name
            mapping[report_name] = model

            # Report name without module prefix
            if "." in report_name:
                name_without_module = report_name.split(".", 1)[1]
                mapping[name_without_module] = model

            # Also store lowercase versions for flexible matching
            mapping[report_name.lower()] = model
            if "." in report_name:
                mapping[name_without_module.lower()] = model

        self.debug_logs.append(
            f"Built report name mapping with {len(mapping)} entries"
        )
        return mapping

    def build_report_name_to_module_mapping(
        self, model_module_map: Dict[str, str]
    ) -> Dict[str, Tuple[str, str]]:
        """Build mapping from report_name to (module, model).

        This mapping is used to determine which module a QWeb template
        should be placed in based on the report that uses it.

        Args:
            model_module_map: Dictionary mapping model names to module names

        Returns:
            Dictionary mapping report_name to (module_name, model_name) tuples
        """
        mapping: Dict[str, Tuple[str, str]] = {}

        for report in self._reports_data:
            report_name = report.get("report_name")
            model = report.get("model")

            if not report_name or not model:
                continue

            # Determine module for this report based on its model
            module = model_module_map.get(model, "unknown")

            # Store mapping from report_name to (module, model)
            mapping[report_name] = (module, model)

            # Also store without module prefix for flexible lookup
            if "." in report_name:
                name_without_module = report_name.split(".", 1)[1]
                mapping[name_without_module] = (module, model)

        self.debug_logs.append(
            f"Built report_name→module mapping with {len(mapping)} entries"
        )
        return mapping

    def extract_tcall_references(self, arch_db: str) -> Set[str]:
        """Extract t-call template references from QWeb arch_db using regex.

        Args:
            arch_db: The arch_db XML content

        Returns:
            Set of template names referenced via t-call
        """
        if not arch_db:
            return set()

        # Regex pattern to match t-call="template.name" or t-call='template.name'
        pattern = r't-call=["\']([^"\']+)["\']'
        matches = re.findall(pattern, arch_db)

        # Filter out web.* templates (Odoo core templates)
        result = {m for m in matches if not m.startswith("web.")}

        return result

    def build_qweb_view_index(self) -> Dict[str, Dict[str, Any]]:
        """Build index of QWeb views by their key/name for quick lookup.

        Returns:
            Dictionary mapping view key/name to view data
        """
        index: Dict[str, Dict[str, Any]] = {}

        for view_id, view_data in self._views_metadata.items():
            view_type = view_data.get("type")
            if view_type != "qweb":
                continue

            # Index by key (primary)
            key = view_data.get("key")
            if key:
                index[key] = view_data

            # Also index by name for fallback lookup
            name = view_data.get("name")
            if name and name not in index:
                index[name] = view_data

        self.debug_logs.append(
            f"Built QWeb view index with {len(index)} entries"
        )
        return index

    def resolve_all_tcall_dependencies(
        self,
        root_template_key: str,
        qweb_index: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Set[str]:
        """Resolve all transitive t-call dependencies for a template.

        Starting from a root template, finds all templates it calls
        directly and transitively.

        Args:
            root_template_key: The starting template key (e.g., report_name)
            qweb_index: Optional pre-built QWeb index (will build if not provided)

        Returns:
            Set of all template keys that are dependencies (including root)
        """
        if qweb_index is None:
            qweb_index = self.build_qweb_view_index()

        resolved: Set[str] = set()
        to_process: Set[str] = {root_template_key}

        while to_process:
            current = to_process.pop()

            # Skip if already processed
            if current in resolved:
                continue

            resolved.add(current)

            # Find view data for current template
            view_data = qweb_index.get(current)
            if not view_data:
                continue

            # Extract t-call references from this template
            arch_db = view_data.get("arch_db", "")
            tcall_refs = self.extract_tcall_references(arch_db)

            # Add unprocessed references to queue
            for ref in tcall_refs:
                if ref not in resolved:
                    to_process.add(ref)

        return resolved

    def find_model_from_report(self, view_name: str) -> Optional[str]:
        """Try to find model for a view by matching it to a report.

        Checks various name patterns:
        - View name might contain report_name (e.g., "ropeworx_label_donaghys")
        - View name might have studio_customization prefix

        Args:
            view_name: View name (e.g., "studio_customization.ropeworx_label_donaghys")

        Returns:
            Model name if found, None otherwise
        """
        if not self._report_name_to_model:
            return None

        # Extract the meaningful part of the view name
        # E.g., "studio_customization.ropeworx_label_donaghys" -> "ropeworx_label_donaghys"
        name_parts = view_name.split(".")
        search_name = name_parts[-1] if "." in view_name else view_name

        # Try direct lookup
        if search_name in self._report_name_to_model:
            model = self._report_name_to_model[search_name]
            self.debug_logs.append(
                f"Found model {model} for view {view_name} via direct match"
            )
            return model

        # Try partial matches (e.g., view contains report name)
        search_name_lower = search_name.lower()
        for report_pattern, model in self._report_name_to_model.items():
            if (
                report_pattern.lower() in search_name_lower
                or search_name_lower in report_pattern.lower()
            ):
                self.debug_logs.append(
                    f"Found model {model} for view {view_name} via partial match with {report_pattern}"
                )
                return model

        return None

    def find_report_for_qweb_view(self, view_name: str) -> Optional[str]:
        """Find which report uses a QWeb view.
        
        Args:
            view_name: QWeb view name/key
            
        Returns:
            Report name if found, None otherwise
        """
        for report in self._reports_data:
            report_name = report.get("report_name")
            if not report_name:
                continue
                
            # Check if this view is directly referenced by the report
            if report_name == view_name:
                return report_name
            
            # Check if this view is a transitive dependency
            qweb_index = self.build_qweb_view_index()
            all_deps = self.resolve_all_tcall_dependencies(report_name, qweb_index)
            
            if view_name in all_deps:
                return report_name
        
        return None

    def get_qweb_views_for_report(
        self, report_name: str
    ) -> Set[str]:
        """Get all QWeb view keys/names that a report depends on.
        
        This includes the main report template and all transitive dependencies.
        
        Args:
            report_name: Report name (e.g., "sale.report_custom_quote")
            
        Returns:
            Set of QWeb view keys/names
        """
        qweb_index = self.build_qweb_view_index()
        return self.resolve_all_tcall_dependencies(report_name, qweb_index)

    @property
    def views_metadata(self) -> Dict[int, Dict[str, Any]]:
        """Get views metadata dictionary."""
        return self._views_metadata

    @property
    def reports_data(self) -> List[Dict[str, Any]]:
        """Get reports data list."""
        return self._reports_data

    @property
    def report_name_to_model(self) -> Dict[str, str]:
        """Get report name to model mapping."""
        return self._report_name_to_model
