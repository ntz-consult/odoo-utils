"""
Module-Model Map Generator - Generate and maintain module_model_map.toml.

Part of V1.1.3 - Simplified module-model mapping system.
"""

import logging
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from file_manager import FileManager


@dataclass
class MapGenerationResult:
    """Result of map generation/update."""

    total_models: int
    mapped_models: int
    unmapped_models: int
    deprecated_models: int
    new_models: int
    preserved_mappings: int


class ModuleModelMapGenerator:
    """Generate and maintain module_model_map.toml file."""

    def __init__(
        self, project_root: Path, odoo_source: Path, verbose: bool = True
    ):
        """Initialize generator.

        Args:
            project_root: Project root directory
            odoo_source: Path to Odoo source
            verbose: Show progress messages
        """
        self.project_root = Path(project_root)
        self.map_file = self.project_root / "studio" / "module_model_map.toml"
        self.odoo_source = Path(odoo_source).expanduser().resolve()
        self.verbose = verbose
        self.logger = logging.getLogger(__name__)
        self.file_manager = FileManager(project_root)

    def generate_or_update_map(
        self,
        extracted_models: List[str],
        component_stats: Dict[str, Dict[str, int]],
        model_usage_hints: Optional[Dict[str, List[str]]] = None,
    ) -> MapGenerationResult:
        """Generate or update map file with incremental logic.

        Args:
            extracted_models: List of model names from extraction
            component_stats: Dict of model → {field_count, view_count, ...}
            model_usage_hints: Optional dict of model → [component descriptions]

        Returns:
            MapGenerationResult with statistics
        """
        if self.verbose:
            self.logger.info("\n" + "=" * 70)
            self.logger.info("MODULE-MODEL MAP GENERATION")
            self.logger.info("=" * 70)

        # Load existing map if present
        existing_map = (
            self._load_existing_map() if self.map_file.exists() else None
        )

        if existing_map and self.verbose:
            self.logger.info(f"\nFound existing map: {self.map_file}")
            self.logger.info(f"  Previous models: {len(existing_map['model_to_module'])}")

        # Build Odoo source model map (auto-detection)
        from odoo_source_scanner import OdooSourceScanner

        scanner = OdooSourceScanner(self.odoo_source, verbose=self.verbose)
        odoo_model_map = scanner.build_model_map()

        # Build new map with incremental update logic
        new_map_data = self._build_map(
            extracted_models,
            component_stats,
            existing_map,
            odoo_model_map,
            model_usage_hints,
        )

        # Calculate statistics
        stats = self._calculate_stats(
            new_map_data, existing_map, extracted_models
        )

        # Write TOML file
        self._write_toml(new_map_data)

        if self.verbose:
            self.logger.info("\n" + "=" * 70)
            self.logger.info("MAP GENERATION COMPLETE")
            self.logger.info("=" * 70)
            self.logger.info(f"\nMap file: {self.map_file}")

        return stats

    def _load_existing_map(self) -> Optional[Dict]:
        """Load existing TOML map file."""
        try:
            data = self.file_manager.read_toml(self.map_file)

            # Build flat model_to_module map from [modules.*] sections
            model_to_module = {}
            if "modules" in data:
                for module_name, module_data in data["modules"].items():
                    if "models" in module_data:
                        for model in module_data["models"]:
                            model_to_module[model] = module_name

            return {
                "metadata": data.get("metadata", {}),
                "modules": data.get("modules", {}),
                "model_to_module": model_to_module,
            }
        except Exception as e:
            if self.verbose:
                self.logger.warning(f"Could not load existing map: {e}")
            return None

    def _build_map(
        self,
        extracted_models: List[str],
        component_stats: Dict[str, Dict[str, int]],
        existing_map: Optional[Dict],
        odoo_model_map: Dict[str, str],
        model_usage_hints: Optional[Dict[str, List[str]]],
    ) -> Dict:
        """Build map with incremental update logic.

        Returns:
            Dict with metadata, statistics, and modules sections
        """
        model_to_module = {}
        new_models = set()
        preserved_models = set()

        # Process each extracted model
        for model in extracted_models:
            # Check if model already mapped by user
            if existing_map and model in existing_map["model_to_module"]:
                existing_module = existing_map["model_to_module"][model]

                # Preserve user mappings (except TO_BE_PROVIDED and DEPRECATED)
                if existing_module not in ["TO_BE_PROVIDED", "DEPRECATED"]:
                    model_to_module[model] = existing_module
                    preserved_models.add(model)
                    continue

            # Try auto-assignment from Odoo source
            if model in odoo_model_map:
                model_to_module[model] = odoo_model_map[model]
            else:
                # Mark as needing user input
                model_to_module[model] = "TO_BE_PROVIDED"
                new_models.add(model)

        # Mark deprecated models (in old map but not in current extraction)
        deprecated_models = set()
        if existing_map:
            for model, module in existing_map["model_to_module"].items():
                if model not in extracted_models and module not in [
                    "DEPRECATED",
                    "TO_BE_PROVIDED",
                ]:
                    model_to_module[model] = "DEPRECATED"
                    deprecated_models.add(model)

        # Group by module
        modules = self._group_by_module(
            model_to_module, component_stats, model_usage_hints
        )

        # Build metadata
        metadata = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "odoo_source": str(self.odoo_source),
            "extraction_count": sum(
                sum(stats.values()) for stats in component_stats.values()
            ),
            "last_extract": datetime.now().isoformat(timespec="seconds"),
        }

        # Build statistics
        statistics = {
            "total_models": len(
                [
                    m
                    for m, mod in model_to_module.items()
                    if mod != "DEPRECATED"
                ]
            ),
            "mapped_models": len(
                [
                    m
                    for m, mod in model_to_module.items()
                    if mod not in ["TO_BE_PROVIDED", "DEPRECATED"]
                ]
            ),
            "unmapped_models": len(
                [
                    m
                    for m, mod in model_to_module.items()
                    if mod == "TO_BE_PROVIDED"
                ]
            ),
            "deprecated_models": len(deprecated_models),
        }

        return {
            "metadata": metadata,
            "statistics": statistics,
            "modules": modules,
            "_internal": {
                "new_models": new_models,
                "preserved_models": preserved_models,
                "deprecated_models": deprecated_models,
            },
        }

    def _group_by_module(
        self,
        model_to_module: Dict[str, str],
        component_stats: Dict[str, Dict[str, int]],
        model_usage_hints: Optional[Dict[str, List[str]]],
    ) -> Dict[str, Dict]:
        """Group models by module with component counts.

        Returns:
            Dict of module_name → {models: [...], component_counts: {...}}
        """
        modules = {}

        # Group models by their assigned module
        for model, module in model_to_module.items():
            if module not in modules:
                modules[module] = {
                    "models": [],
                    "component_counts": {
                        "fields": 0,
                        "views": 0,
                        "server_actions": 0,
                        "automations": 0,
                        "reports": 0,
                    },
                }

            modules[module]["models"].append(model)

            # Add component counts for this model
            if model in component_stats:
                for comp_type, count in component_stats[model].items():
                    if comp_type in modules[module]["component_counts"]:
                        modules[module]["component_counts"][comp_type] += count

        # Sort models within each module
        for module_data in modules.values():
            module_data["models"].sort()

        # Add hints for TO_BE_PROVIDED section
        if "TO_BE_PROVIDED" in modules and model_usage_hints:
            hints = []
            for model in modules["TO_BE_PROVIDED"]["models"]:
                if model in model_usage_hints:
                    hints.append(
                        f"{model}: {', '.join(model_usage_hints[model][:3])}"
                    )
            if hints:
                modules["TO_BE_PROVIDED"]["_hints"] = hints

        return modules

    def _calculate_stats(
        self,
        new_map_data: Dict,
        existing_map: Optional[Dict],
        extracted_models: List[str],
    ) -> MapGenerationResult:
        """Calculate generation statistics."""
        internal = new_map_data["_internal"]

        return MapGenerationResult(
            total_models=new_map_data["statistics"]["total_models"],
            mapped_models=new_map_data["statistics"]["mapped_models"],
            unmapped_models=new_map_data["statistics"]["unmapped_models"],
            deprecated_models=new_map_data["statistics"]["deprecated_models"],
            new_models=len(internal["new_models"]),
            preserved_mappings=len(internal["preserved_models"]),
        )

    def _write_toml(self, map_data: Dict) -> None:
        """Write map data to TOML file.

        Uses manual formatting for better readability.
        """
        lines = []

        # Header comment
        lines.append("# Module-Model Mapping for Odoo Studio Customizations")
        lines.append("# Generated by odoo-project-sync v1.1.3")
        lines.append("#")
        lines.append("# INSTRUCTIONS:")
        lines.append(
            "# 1. Review models marked in [modules.TO_BE_PROVIDED] section"
        )
        lines.append("# 2. Move models to appropriate module sections")
        lines.append(
            "# 3. Standard Odoo modules: sale, stock, account, purchase, crm, project, etc."
        )
        lines.append(
            "# 4. Models in [modules.DEPRECATED] are no longer in extraction"
        )
        lines.append("")

        # Metadata section
        lines.append("[metadata]")
        for key, value in map_data["metadata"].items():
            if isinstance(value, str):
                lines.append(f'{key} = "{value}"')
            else:
                lines.append(f"{key} = {value}")
        lines.append("")

        # Statistics section
        lines.append("# Mapping statistics")
        lines.append("[statistics]")
        for key, value in map_data["statistics"].items():
            lines.append(f"{key} = {value}")
        lines.append("")

        # Modules sections
        lines.append("# Module-based grouping")
        lines.append("")

        # Sort modules: standard modules first, then TO_BE_PROVIDED, then DEPRECATED
        special_modules = ["TO_BE_PROVIDED", "DEPRECATED"]
        standard_modules = sorted(
            [m for m in map_data["modules"].keys() if m not in special_modules]
        )
        all_modules = standard_modules + [
            m for m in special_modules if m in map_data["modules"]
        ]

        for module in all_modules:
            module_data = map_data["modules"][module]

            lines.append(f"[modules.{module}]")

            # Models array
            if module_data["models"]:
                lines.append("models = [")
                for model in module_data["models"]:
                    lines.append(f'    "{model}",')
                lines.append("]")
            else:
                lines.append("models = []")

            # Component counts (not for special modules)
            if module not in special_modules:
                counts = module_data["component_counts"]
                lines.append(
                    f"component_counts = {{ "
                    + f"fields = {counts['fields']}, "
                    + f"views = {counts['views']}, "
                    + f"server_actions = {counts['server_actions']}, "
                    + f"automations = {counts['automations']}, "
                    + f"reports = {counts['reports']}"
                    + " }"
                )

            # Add hints for TO_BE_PROVIDED
            if module == "TO_BE_PROVIDED" and "_hints" in module_data:
                lines.append("# HINT: Used by these components:")
                for hint in module_data["_hints"]:
                    lines.append(f"# - {hint}")

            # Add message for DEPRECATED
            if module == "DEPRECATED" and module_data["models"]:
                lines.append(
                    "# ACTION REQUIRED: Remove these entries if no longer needed"
                )

            lines.append("")

        # Write to file
        content = "\n".join(lines)
        self.file_manager.write_text(self.map_file, content)

        if self.verbose:
            self.logger.info(f"\n✓ Map file written: {self.map_file}")
