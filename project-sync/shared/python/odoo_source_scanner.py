"""
Odoo Source Scanner - Find model definitions in Odoo source code.

Part of V1.1.3 - Simplified module-model mapping system.
Scans odoo/addons directory to find model definitions.
"""

import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set


class OdooSourceScanner:
    """Simplified Odoo source scanner (no caching, no complex logic)."""

    def __init__(self, odoo_source: Path, verbose: bool = True):
        """Initialize scanner.

        Args:
            odoo_source: Path to Odoo source root (contains odoo/addons)
            verbose: Show progress indicators
        """
        self.odoo_source = Path(odoo_source).expanduser().resolve()
        self.verbose = verbose
        self.addons_dirs = self._find_addons_dirs()
        self.logger = logging.getLogger(__name__)

        # Statistics
        self.modules_scanned = 0
        self.files_scanned = 0
        self.models_found = 0

    def _find_addons_dirs(self) -> List[Path]:
        """Find addons directories in Odoo source.

        Only searches odoo/addons (not enterprise).

        Returns:
            List of addons directory paths

        Raises:
            ValueError: If odoo_source is invalid or addons not found
        """
        if not self.odoo_source.exists():
            raise ValueError(
                f"Odoo source path does not exist: {self.odoo_source}\n"
                f"Please check your odoo_source configuration."
            )

        if not self.odoo_source.is_dir():
            raise ValueError(
                f"Odoo source path is not a directory: {self.odoo_source}"
            )

        # Look for odoo/addons
        addons_dir = self.odoo_source / "odoo" / "addons"

        if not addons_dir.exists():
            # Try direct addons folder (in case odoo_source points to odoo/)
            addons_dir = self.odoo_source / "addons"

        if not addons_dir.exists() or not addons_dir.is_dir():
            raise ValueError(
                f"Could not find addons directory in Odoo source: {self.odoo_source}\n"
                f"Expected: {self.odoo_source}/odoo/addons or {self.odoo_source}/addons"
            )

        return [addons_dir]

    def find_model_module(self, model_name: str) -> Optional[str]:
        """Find module for a model by scanning source.

        Uses simple grep-like search for _name definitions.
        Searches odoo/addons only (not enterprise).

        Args:
            model_name: Model name (e.g., "sale.order")

        Returns:
            Module name if found, None otherwise
        """
        # Pattern matches: _name = 'model.name' or _name = "model.name"
        # Must be at start of line (after whitespace) to avoid false matches
        pattern = re.compile(
            rf'^\s*_name\s*=\s*[\'"]({re.escape(model_name)})[\'"]',
            re.MULTILINE,
        )

        for addons_dir in self.addons_dirs:
            for module_path in addons_dir.iterdir():
                if not module_path.is_dir():
                    continue

                # Skip hidden directories and common non-modules
                if module_path.name.startswith("."):
                    continue

                # Check if it's a valid Odoo module (has __manifest__.py or __openerp__.py)
                if (
                    not (module_path / "__manifest__.py").exists()
                    and not (module_path / "__openerp__.py").exists()
                ):
                    continue

                # Search Python files in module
                for py_file in module_path.rglob("*.py"):
                    try:
                        content = py_file.read_text(
                            encoding="utf-8", errors="ignore"
                        )
                        if pattern.search(content):
                            return module_path.name
                    except Exception:
                        # Skip files that can't be read
                        continue

        return None

    def build_model_map(self) -> Dict[str, str]:
        """Build complete model→module mapping by scanning Odoo source.

        This is used to auto-assign standard Odoo models.
        Shows progress indicators during scan.

        Returns:
            Dict mapping model names to module names
        """
        model_map = {}

        if self.verbose:
            self.logger.info("\nScanning Odoo source for model definitions...")
            self.logger.info(f"Source: {self.odoo_source}")

        # Pattern to find _name definitions
        name_pattern = re.compile(
            r'^\s*_name\s*=\s*[\'"]([a-zA-Z0-9._]+)[\'"]', re.MULTILINE
        )

        for addons_dir in self.addons_dirs:
            if self.verbose:
                self.logger.info(f"Scanning: {addons_dir}")

            modules = [
                m
                for m in addons_dir.iterdir()
                if m.is_dir() and not m.name.startswith(".")
            ]
            total_modules = len(modules)

            for idx, module_path in enumerate(modules, 1):
                # Check if it's a valid Odoo module
                if (
                    not (module_path / "__manifest__.py").exists()
                    and not (module_path / "__openerp__.py").exists()
                ):
                    continue

                self.modules_scanned += 1
                module_name = module_path.name

                # Progress indicator (every 10 modules)
                if self.verbose and idx % 10 == 0:
                    self.logger.info(
                        f"  Progress: {idx}/{total_modules} modules ({len(model_map)} models found)"
                    )

                # Search Python files in models/ directory (optimization)
                models_dir = module_path / "models"
                py_files = []

                if models_dir.exists():
                    py_files.extend(models_dir.rglob("*.py"))
                else:
                    # Fallback: search entire module
                    py_files.extend(module_path.rglob("*.py"))

                for py_file in py_files:
                    self.files_scanned += 1

                    try:
                        content = py_file.read_text(
                            encoding="utf-8", errors="ignore"
                        )
                        matches = name_pattern.findall(content)

                        for model_name in matches:
                            # Only add if not already found (first match wins)
                            if model_name not in model_map:
                                model_map[model_name] = module_name
                                self.models_found += 1

                    except Exception:
                        # Skip files that can't be read
                        continue

            if self.verbose:
                # Clear progress line and show final count
                self.logger.info(
                    f"  Progress: {total_modules}/{total_modules} modules ({len(model_map)} models found)"
                )

        if self.verbose:
            self.logger.info(f"\n✓ Scan complete:")
            self.logger.info(f"  Modules scanned: {self.modules_scanned}")
            self.logger.info(f"  Files scanned: {self.files_scanned}")
            self.logger.info(f"  Models found: {self.models_found}")

        return model_map

    def get_statistics(self) -> Dict[str, int]:
        """Get scanner statistics."""
        return {
            "modules_scanned": self.modules_scanned,
            "files_scanned": self.files_scanned,
            "models_found": self.models_found,
        }
