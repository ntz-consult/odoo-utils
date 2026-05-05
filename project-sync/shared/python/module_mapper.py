"""
Module Mapper - Load module-model mappings from TOML file

V1.1.3 simplified version - reads from module_model_map.toml instead of scanning source.
"""

import tomllib
from pathlib import Path
from typing import Dict, List, Optional


class ModuleMapper:
    """Load module-model mappings from TOML file."""

    def __init__(self, map_file: Path):
        """Initialize ModuleMapper.

        Args:
            map_file: Path to module_model_map.toml file
        """
        self.map_file = Path(map_file)
        self._map_data: Optional[Dict] = None
        self._model_to_module: Optional[Dict[str, str]] = None

    def load_map(self) -> Dict[str, str]:
        """Load model→module mapping from TOML file.

        Returns:
            Dict mapping model names to module names

        Raises:
            ValueError: If map file doesn't exist
            tomllib.TOMLDecodeError: If map file is invalid TOML
        """
        if not self.map_file.exists():
            raise ValueError(
                f"Module-model map not found: {self.map_file}\n"
                f"Run './.odoo-sync/cli.py extract --execute' to generate it."
            )

        # Return cached if already loaded
        if self._model_to_module is not None:
            return self._model_to_module

        # Load TOML file
        with open(self.map_file, "rb") as f:
            self._map_data = tomllib.load(f)

        # Build flat model→module map from [modules.*] sections
        self._model_to_module = {}

        if "modules" in self._map_data:
            for module_name, module_data in self._map_data["modules"].items():
                if isinstance(module_data, dict) and "models" in module_data:
                    for model in module_data["models"]:
                        self._model_to_module[model] = module_name

        return self._model_to_module

    def build_model_map(self, force_rebuild: bool = False) -> Dict[str, str]:
        """Build model→module mapping.

        DEPRECATED: Use load_map() instead.
        Kept for backward compatibility with tests.

        Args:
            force_rebuild: Whether to force rebuild (ignored)

        Returns:
            Dict mapping model names to module names
        """
        return self.load_map()

    def validate_map(self) -> List[str]:
        """Validate map has no TO_BE_PROVIDED or DEPRECATED entries.

        Returns:
            List of error messages (empty list if valid)
        """
        map_data = self.load_map()

        errors = []
        for model, module in map_data.items():
            if module == "TO_BE_PROVIDED":
                errors.append(
                    f"Model '{model}' needs module assignment (currently: TO_BE_PROVIDED)"
                )
            elif module == "DEPRECATED":
                errors.append(
                    f"Model '{model}' is marked as DEPRECATED but still in map"
                )

        return errors

    def get_module_for_model(self, model_name: str) -> Optional[str]:
        """Get module for model (simple lookup).

        Args:
            model_name: Model name (e.g., "sale.order")

        Returns:
            Module name if found, None otherwise
        """
        map_data = self.load_map()
        return map_data.get(model_name)

    def get_all_models(self) -> List[str]:
        """Get list of all models in the map.

        Returns:
            List of model names
        """
        map_data = self.load_map()
        return list(map_data.keys())

    def get_models_by_module(self, module_name: str) -> List[str]:
        """Get all models assigned to a specific module.

        Args:
            module_name: Module name

        Returns:
            List of model names
        """
        if self._map_data is None:
            self.load_map()

        if "modules" not in self._map_data:
            return []

        module_data = self._map_data["modules"].get(module_name, {})
        return module_data.get("models", [])

    def get_all_modules(self) -> List[str]:
        """Get list of all modules in the map (excluding special modules).

        Returns:
            List of module names (excluding TO_BE_PROVIDED and DEPRECATED)
        """
        if self._map_data is None:
            self.load_map()

        if "modules" not in self._map_data:
            return []

        # Exclude special modules
        return [
            m
            for m in self._map_data["modules"].keys()
            if m not in ["TO_BE_PROVIDED", "DEPRECATED"]
        ]

    def get_statistics(self) -> Dict[str, int]:
        """Get mapping statistics from TOML file.

        Returns:
            Dict with total_models, mapped_models, unmapped_models, deprecated_models
        """
        if self._map_data is None:
            self.load_map()

        if "statistics" in self._map_data:
            return self._map_data["statistics"]

        # Fallback: calculate from data
        map_data = self.load_map()
        stats = {
            "total_models": len(
                [m for m, mod in map_data.items() if mod != "DEPRECATED"]
            ),
            "mapped_models": len(
                [
                    m
                    for m, mod in map_data.items()
                    if mod not in ["TO_BE_PROVIDED", "DEPRECATED"]
                ]
            ),
            "unmapped_models": len(
                [m for m, mod in map_data.items() if mod == "TO_BE_PROVIDED"]
            ),
            "deprecated_models": len(
                [m for m, mod in map_data.items() if mod == "DEPRECATED"]
            ),
        }
        return stats

    # Backward compatibility methods (deprecated in V1.1.3)
    # These methods are kept for gradual migration but will be removed in V2.0

    @staticmethod
    def is_custom_model(model_name: str) -> bool:
        """Check if a model is a custom model (Studio-created).

        DEPRECATED: This method is kept for backward compatibility.
        In V1.1.3, all models are treated equally.

        Args:
            model_name: Odoo model name

        Returns:
            True if model starts with x_studio_ or x_
        """
        return model_name.startswith(("x_studio_", "x_"))

    def find_model_definition(self, model_name: str) -> Optional[str]:
        """Find which module originally defines a model.

        DEPRECATED: Use get_module_for_model() instead.
        Kept for backward compatibility.

        Args:
            model_name: Odoo model name

        Returns:
            Module name if found, None otherwise
        """
        return self.get_module_for_model(model_name)
