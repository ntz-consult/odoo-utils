#!/usr/bin/env python3
"""Odoo Project Sync - Python CLI

Provides command-line interface equivalents for all slash commands.
Enables CI/CD integration, scripting, and IDE-agnostic usage.

Usage:
    ./.odoo-sync/cli.py [command] [options]
    ./.odoo-sync/cli.py --help
    ./.odoo-sync/cli.py [command] --help
"""

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

try:
    from config import ConfigError, load_config
    from config_manager import ConfigManager
    from extractor_factory import ExtractorFactory
    from feature_detector import (
        FeatureDetector,
        FeatureMapping,
        load_extraction_results,
        load_source_components,
    )
    from feature_user_story_map_generator import FeatureUserStoryMapGenerator
    from feature_user_story_mapper import FeatureUserStoryMapper
    from file_manager import FileManager
    from map_generator import MapGenerationResult, ModuleModelMapGenerator
    from module_generator import ModuleGenerator, ModuleGeneratorError
    from module_mapper import ModuleMapper
    from odoo_client import OdooClient
    from sync_engine import SyncEngine
    from task_manager import TaskManager
    from toml_compare import generate_markdown_comparison
    from utils import resolve_env_vars, load_dotenv, find_project_root
    from enricher_config import EnricherConfig
    from user_story_enricher import UserStoryEnricher
    from effort_estimator import EffortEstimator, TimeMetrics
    from ai_providers import get_available_models, validate_model
    from implementation_overview_generator import ImplementationOverviewGenerator
except ImportError:
    # Fallback for direct execution
    import sys
    from pathlib import Path

    # Add this directory to path
    cli_dir = Path(__file__).parent
    sys.path.insert(0, str(cli_dir))

    from config import ConfigError, load_config, update_project_config
    from config_manager import ConfigManager
    from extractor_factory import ExtractorFactory
    from feature_detector import (
        FeatureDetector,
        FeatureMapping,
        load_extraction_results,
        load_source_components,
    )
    from feature_user_story_map_generator import FeatureUserStoryMapGenerator
    from feature_user_story_mapper import FeatureUserStoryMapper
    from file_manager import FileManager
    from map_generator import MapGenerationResult, ModuleModelMapGenerator
    from module_generator import ModuleGenerator, ModuleGeneratorError
    from module_mapper import ModuleMapper
    from odoo_client import OdooClient
    from sync_engine import SyncEngine
    from task_manager import TaskManager
    from toml_compare import generate_markdown_comparison
    from utils import resolve_env_vars, load_dotenv, find_project_root
    from enricher_config import EnricherConfig
    from user_story_enricher import UserStoryEnricher
    from effort_estimator import EffortEstimator, TimeMetrics
    from ai_providers import get_available_models, validate_model
    from implementation_overview_generator import ImplementationOverviewGenerator


# Exit codes
EXIT_SUCCESS = 0
EXIT_GENERAL_ERROR = 1
EXIT_CONFIG_ERROR = 2
EXIT_API_ERROR = 3
EXIT_CONFLICT_ERROR = 4


class CLIError(Exception):
    """Base exception for CLI errors."""

    def __init__(self, message: str, exit_code: int = EXIT_GENERAL_ERROR):
        super().__init__(message)
        self.exit_code = exit_code


class ConfigurationError(CLIError):
    """Configuration error."""

    def __init__(self, message: str):
        super().__init__(message, EXIT_CONFIG_ERROR)


class APIError(CLIError):
    """API/connection error."""

    def __init__(self, message: str):
        super().__init__(message, EXIT_API_ERROR)


class ConflictError(CLIError):
    """Conflict detection error."""

    def __init__(self, message: str):
        super().__init__(message, EXIT_CONFLICT_ERROR)


class OdooSyncCLI:
    """Main CLI class."""

    def __init__(self):
        self.debug = False
        self.config_path = None
        self.project_root = None
        self.logger = logging.getLogger(__name__)
        self._file_manager = None
        self._config_manager = None

    @property
    def file_manager(self) -> FileManager:
        """Get the FileManager instance, creating it if necessary."""
        if self._file_manager is None:
            self._file_manager = FileManager(self.project_root)
        return self._file_manager

    @property
    def config_manager(self) -> ConfigManager:
        """Get the ConfigManager instance, creating it if necessary."""
        if self._config_manager is None:
            self._config_manager = ConfigManager(self.project_root)
        return self._config_manager

    def log(self, message: str):
        """Log a message."""
        self.logger.info(message)

    def log_error(self, message: str):
        """Log an error message."""
        self.logger.error(message)

    def log_warning(self, message: str):
        """Log a warning message."""
        self.logger.warning(message)

    def _load_existing_config_raw(self, project_root: Path) -> dict | None:
        """Load existing config as raw JSON (preserves env var placeholders).

        Returns:
            Raw config dict or None if config doesn't exist
        """
        config_path = project_root / ".odoo-sync" / "odoo-instances.json"
        if not self.file_manager.exists(config_path):
            return None

        try:
            return self.file_manager.read_json(config_path)
        except Exception:
            self.log_warning("Could not read existing config, starting fresh")
            return None

    def _get_nested_value(
        self, data: dict, path: str, default: str = ""
    ) -> str:
        """Extract nested value from config dict using dot notation.

        Args:
            data: Config dictionary
            path: Dot-separated path (e.g., "instances.implementation.url")
            default: Default value if path not found

        Returns:
            Value at path or default
        """
        keys = path.split(".")
        current = data

        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default

        # Convert None to empty string for display
        return str(current) if current is not None else default

    def _prompt_with_default(self, prompt: str, default: str = "") -> str:
        """Prompt user with a default value shown in brackets.

        Args:
            prompt: Prompt text (without trailing colon/space)
            default: Default value to show and return if user presses Enter

        Returns:
            User input or default value
        """
        if default:
            full_prompt = f"{prompt} [{default}]: "
        else:
            full_prompt = f"{prompt}: "

        value = input(full_prompt).strip()
        return value if value else default

    def _backup_config(self, config_path: Path) -> Path | None:
        """Create backup of existing config file.

        Args:
            config_path: Path to config file to backup

        Returns:
            Path to backup file or None if backup failed
        """
        if not config_path.exists():
            return None

        backup_path = config_path.with_suffix(".json.backup")
        try:
            import shutil

            shutil.copy2(config_path, backup_path)
            return backup_path
        except IOError as e:
            self.log_warning(f"Could not create backup: {e}")
            return None

    def cmd_init(self, args):
        """Initialize configuration (interactive setup)."""
        try:
            self.log("Odoo Project Sync - Initialize\n")
            self.log(
                "This wizard will guide you through setting up both Odoo instances.\n"
            )

            # Load existing configuration if present
            project_root = self.project_root or Path.cwd()
            existing_config = self._load_existing_config_raw(project_root)

            if existing_config:
                self.log(
                    "Existing configuration detected. Current values shown in [brackets]."
                )
                self.log(
                    "Press Enter to keep current value, or type new value to update.\n"
                )

            # Extract defaults from existing config (empty string if none)
            impl_url_default = ""
            impl_db_default = ""
            impl_user_default = ""
            impl_key_var_default = "ODOO_IMPL_API_KEY"
            dev_url_default = ""
            dev_db_default = ""
            dev_user_default = ""
            dev_key_var_default = "ODOO_DEV_API_KEY"
            dev_project_id_default = ""
            dev_project_name_default = ""
            dev_sale_line_id_default = ""

            if existing_config:
                impl_url_default = self._get_nested_value(
                    existing_config, "instances.implementation.url", ""
                )
                impl_db_default = self._get_nested_value(
                    existing_config, "instances.implementation.database", ""
                )
                impl_user_default = self._get_nested_value(
                    existing_config, "instances.implementation.username", ""
                )

                # Extract API key variable name (strip ${} if present)
                impl_api_key_raw = self._get_nested_value(
                    existing_config,
                    "instances.implementation.api_key",
                    "${ODOO_IMPL_API_KEY}",
                )
                if impl_api_key_raw.startswith(
                    "${"
                ) and impl_api_key_raw.endswith("}"):
                    impl_key_var_default = impl_api_key_raw[2:-1]
                else:
                    impl_key_var_default = impl_api_key_raw

                dev_url_default = self._get_nested_value(
                    existing_config, "instances.development.url", ""
                )
                dev_db_default = self._get_nested_value(
                    existing_config, "instances.development.database", ""
                )
                dev_user_default = self._get_nested_value(
                    existing_config, "instances.development.username", ""
                )

                dev_api_key_raw = self._get_nested_value(
                    existing_config,
                    "instances.development.api_key",
                    "${ODOO_DEV_API_KEY}",
                )
                if dev_api_key_raw.startswith(
                    "${"
                ) and dev_api_key_raw.endswith("}"):
                    dev_key_var_default = dev_api_key_raw[2:-1]
                else:
                    dev_key_var_default = dev_api_key_raw

                dev_project_id_default = self._get_nested_value(
                    existing_config, "instances.development.project.id", ""
                )
                dev_project_name_default = self._get_nested_value(
                    existing_config, "instances.development.project.name", ""
                )
                dev_sale_line_id_default = self._get_nested_value(
                    existing_config,
                    "instances.development.project.sale_line_id",
                    "",
                )

            # Prompt for Implementation Odoo
            self.log("=" * 50)
            self.log("IMPLEMENTATION ODOO (Read-Only)")
            self.log("=" * 50)
            impl_url = self._prompt_with_default(
                "URL (e.g., https://client.odoo.com)", impl_url_default
            )
            impl_db = self._prompt_with_default(
                "Database name", impl_db_default
            )
            impl_user = self._prompt_with_default(
                "Username (email)", impl_user_default
            )
            impl_key_var = self._prompt_with_default(
                "API key environment variable", impl_key_var_default
            )

            # Prompt for Development Odoo
            self.log("\n" + "=" * 50)
            self.log("DEVELOPMENT ODOO (Read/Write)")
            self.log("=" * 50)
            dev_url = self._prompt_with_default(
                "URL (e.g., https://dev.odoo.com)", dev_url_default
            )
            dev_db = self._prompt_with_default("Database name", dev_db_default)
            dev_user = self._prompt_with_default(
                "Username (email)", dev_user_default
            )
            dev_key_var = self._prompt_with_default(
                "API key environment variable", dev_key_var_default
            )
            dev_project_id = self._prompt_with_default(
                "Project ID (from project.project)", dev_project_id_default
            )
            dev_project_name = (
                self._prompt_with_default(
                    "Project name (optional)", dev_project_name_default
                )
                or None
            )
            dev_sale_line_id = self._prompt_with_default(
                "Sale order line ID (optional)", dev_sale_line_id_default
            )

            # Check if values changed (only validate if changed)
            impl_changed = False
            dev_changed = False

            if existing_config:
                impl_changed = (
                    impl_url != impl_url_default
                    or impl_db != impl_db_default
                    or impl_user != impl_user_default
                    or impl_key_var != impl_key_var_default
                )
                dev_changed = (
                    dev_url != dev_url_default
                    or dev_db != dev_db_default
                    or dev_user != dev_user_default
                    or dev_key_var != dev_key_var_default
                )
            else:
                # First run, always validate
                impl_changed = True
                dev_changed = True

            # Validate connections
            self.log("\nValidating connections...")

            if impl_changed:
                impl_api_key = resolve_env_vars(f"${{{impl_key_var}}}")
                if not impl_api_key:
                    raise ConfigurationError(
                        f"Environment variable {impl_key_var} not set. Please set it in .env"
                    )

                impl_client = OdooClient(
                    url=impl_url,
                    database=impl_db,
                    username=impl_user,
                    api_key=impl_api_key,
                    read_only=True,
                )
                impl_result = impl_client.test_connection()
                if not impl_result.get("success"):
                    raise APIError(
                        f"Implementation Odoo connection failed: {impl_result.get('error')}"
                    )
                self.log(
                    f"✓ Implementation Odoo: {impl_result['user_name']} ({impl_result['server_version']})"
                )
            else:
                self.log(
                    f"✓ Implementation Odoo: Using existing configuration (not changed)"
                )

            if dev_changed:
                dev_api_key = resolve_env_vars(f"${{{dev_key_var}}}")
                if not dev_api_key:
                    raise ConfigurationError(
                        f"Environment variable {dev_key_var} not set. Please set it in .env"
                    )

                dev_client = OdooClient(
                    url=dev_url,
                    database=dev_db,
                    username=dev_user,
                    api_key=dev_api_key,
                    read_only=False,
                )
                dev_result = dev_client.test_connection()
                if not dev_result.get("success"):
                    raise APIError(
                        f"Development Odoo connection failed: {dev_result.get('error')}"
                    )
                self.log(
                    f"✓ Development Odoo: {dev_result['user_name']} ({dev_result['server_version']})"
                )
            else:
                self.log(
                    f"✓ Development Odoo: Using existing configuration (not changed)"
                )

            # Build configuration (preserve existing structure if present)
            if existing_config and "instances" in existing_config:
                # Merge with existing config
                config_data = existing_config

                # Update instances
                config_data["instances"]["implementation"].update(
                    {
                        "url": impl_url,
                        "database": impl_db,
                        "username": impl_user,
                        "api_key": f"${{{impl_key_var}}}",
                        "read_only": True,
                    }
                )

                config_data["instances"]["development"].update(
                    {
                        "url": dev_url,
                        "database": dev_db,
                        "username": dev_user,
                        "api_key": f"${{{dev_key_var}}}",
                        "read_only": False,
                    }
                )

                # Update project info
                if "project" not in config_data["instances"]["development"]:
                    config_data["instances"]["development"]["project"] = {}

                config_data["instances"]["development"]["project"].update(
                    {
                        "id": int(dev_project_id) if dev_project_id else None,
                        "name": dev_project_name,
                        "sale_line_id": (
                            int(dev_sale_line_id) if dev_sale_line_id else None
                        ),
                    }
                )
            else:
                # First run - create full structure from template
                config_data = {
                    "instances": {
                        "implementation": {
                            "description": "Client Production - READ ONLY",
                            "url": impl_url,
                            "database": impl_db,
                            "username": impl_user,
                            "api_key": f"${{{impl_key_var}}}",
                            "read_only": True,
                            "purpose": "extraction",
                            "odoo_version": "19",
                        },
                        "development": {
                            "description": "Development - READ/WRITE",
                            "url": dev_url,
                            "database": dev_db,
                            "username": dev_user,
                            "api_key": f"${{{dev_key_var}}}",
                            "read_only": False,
                            "purpose": "development",
                            "odoo_version": "19",
                            "project": {
                                "id": (
                                    int(dev_project_id)
                                    if dev_project_id
                                    else None
                                ),
                                "name": dev_project_name,
                                "sale_line_id": (
                                    int(dev_sale_line_id)
                                    if dev_sale_line_id
                                    else None
                                ),
                            },
                        },
                    },
                    "active_instance": "development",
                    "sync": {
                        "conflict_resolution": "prefer_local",
                        "preserve_logged_time": True,
                        "auto_move_completed": True,
                        "require_confirmation": False,
                    },
                    "extraction_filters": {
                        "custom_fields": [["state", "=", "manual"]],
                        "server_actions": [],
                        "automations": [["active", "=", True]],
                        "views": [],
                        "reports": [],
                    },
                }

            # Create configuration files
            sync_dir = project_root / ".odoo-sync"
            sync_dir.mkdir(exist_ok=True)

            config_path = sync_dir / "odoo-instances.json"

            # Backup existing config if present
            if config_path.exists():
                backup_path = self._backup_config(config_path)
                if backup_path:
                    self.log(
                        f"✓ Backed up existing config to {backup_path.name}"
                    )

            # Write new config
            with open(config_path, "w") as f:
                json.dump(config_data, f, indent=2)
            self.log(f"✓ Configuration saved to {config_path}")

            # Create directories
            (sync_dir / "data" / "extraction-results").mkdir(
                parents=True, exist_ok=True
            )
            (sync_dir / "data" / "audit").mkdir(parents=True, exist_ok=True)
            (sync_dir / "config").mkdir(parents=True, exist_ok=True)
            self.log("✓ Directory structure created")

            # Create .env.example if needed
            env_example = project_root / ".env.example"
            if not env_example.exists():
                with open(env_example, "w") as f:
                    f.write(f"{impl_key_var}=\n{dev_key_var}=\n")
                self.log(f"✓ Created {env_example}")

            self.log("\n" + "=" * 50)
            self.log("SETUP COMPLETE")
            self.log("=" * 50)
            self.log(f"Next steps:")
            self.log(f"1. Add API keys to .env:")
            self.log(f"   echo '{impl_key_var}=<key>' >> .env")
            self.log(f"   echo '{dev_key_var}=<key>' >> .env")
            self.log(f"2. Verify status: ./.odoo-sync/cli.py status")
            self.log(
                f"3. Extract customizations: ./.odoo-sync/cli.py extract --execute"
            )

            return EXIT_SUCCESS

        except (ConfigurationError, APIError) as e:
            self.log_error(str(e))
            return e.exit_code
        except KeyboardInterrupt:
            self.log("\nSetup cancelled.")
            return EXIT_SUCCESS
        except Exception as e:
            if self.debug:
                import traceback

                traceback.print_exc()
            self.log_error(f"Unexpected error: {str(e)}")
            return EXIT_GENERAL_ERROR

    def _collect_models_from_extraction(
        self, extraction_dir: Path
    ) -> list[str]:
        """Collect all unique model names from extraction results.

        Args:
            extraction_dir: Path to extraction-results directory

        Returns:
            List of unique model names
        """
        models = set()

        # Map of file patterns to model field names
        file_patterns = {
            "custom_fields_output.json": "model",
            "views_metadata.json": "model",
            "server_actions_output.json": "model_name",
            "auto_actions_output.json": "model_name",
            "reports_output.json": "model",
        }

        for filename, model_field in file_patterns.items():
            file_path = extraction_dir / filename
            if not file_path.exists():
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Extract models from records
                if "records" in data:
                    for record in data["records"]:
                        if model_field in record:
                            model_name = record[model_field]
                            if model_name:
                                models.add(model_name)

            except Exception as e:
                if self.debug:
                    self.log(f"Warning: Could not parse {filename}: {e}")

        return sorted(list(models))

    def _count_components_by_model(
        self, extraction_dir: Path
    ) -> dict[str, dict[str, int]]:
        """Count components by model.

        Args:
            extraction_dir: Path to extraction-results directory

        Returns:
            Dict of model → {fields: N, views: N, server_actions: N, automations: N, reports: N}
        """
        counts = {}

        # Component type mappings
        component_files = {
            "custom_fields_output.json": ("fields", "model"),
            "views_metadata.json": ("views", "model"),
            "server_actions_output.json": ("server_actions", "model_name"),
            "auto_actions_output.json": ("automations", "model_name"),
            "reports_output.json": ("reports", "model"),
        }

        for filename, (component_type, model_field) in component_files.items():
            file_path = extraction_dir / filename
            if not file_path.exists():
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Count by model
                if "records" in data:
                    for record in data["records"]:
                        if model_field in record:
                            model_name = record[model_field]
                            if model_name:
                                if model_name not in counts:
                                    counts[model_name] = {
                                        "fields": 0,
                                        "views": 0,
                                        "server_actions": 0,
                                        "automations": 0,
                                        "reports": 0,
                                    }
                                counts[model_name][component_type] += 1

            except Exception as e:
                if self.debug:
                    self.log(f"Warning: Could not parse {filename}: {e}")

        return counts

    def cmd_extract(self, args):
        """Extract Studio customizations."""
        try:
            config = self._load_config()
            project_root = self.project_root or Path.cwd()

            # Connect to implementation instance
            client = self._connect_to_implementation_odoo(required=True)

            self.log("Extracting from Implementation Odoo...\n")

            dry_run = not args.execute
            output_dir = (
                project_root / ".odoo-sync" / "data" / "extraction-results"
            )
            output_dir.mkdir(parents=True, exist_ok=True)

            # Run extractors
            extractors = ExtractorFactory.create_all_extractors(
                client, output_dir, dry_run=dry_run
            ).values()

            results = {}
            total_extractors = len(extractors)
            for idx, extractor in enumerate(extractors, 1):
                self.log(
                    f"[{idx}/{total_extractors}] Extracting {extractor.name}..."
                )
                filters = getattr(
                    self.config_manager.extraction_filters, extractor.name, []
                )
                result = extractor.extract(
                    base_filters=filters if filters else None
                )
                results[extractor.name] = result

            # Display summary
            self.log("\nFound:")
            for name, result in results.items():
                count = result.record_count if result else 0
                status = "✓" if result and not result.errors else "✗"
                self.log(f"  {status} {name}: {count}")

            if dry_run:
                self.log(
                    f"\nNo changes applied (dry-run mode). Use --execute to write files."
                )
            else:
                self.log(f"\nExtraction results saved to {output_dir}")
                self.log(
                    f"\n→ Next step: ./.odoo-sync/cli.py generate-modules --execute"
                )

                # Generate/update module-model map (V1.1.3)
                try:
                    # Collect models from extraction results
                    extracted_models = self._collect_models_from_extraction(
                        output_dir
                    )

                    if extracted_models:
                        # Count components by model
                        component_stats = self._count_components_by_model(
                            output_dir
                        )

                        # Verify odoo_source is configured
                        odoo_source = self.config_manager.implementation.odoo_source
                        if not odoo_source:
                            self.log("\n⚠ Warning: odoo_source not configured")
                            self.log(
                                "  Module-model map will mark all models as TO_BE_PROVIDED"
                            )
                            self.log(
                                "  Configure odoo_source in .odoo-sync/config/odoo-instances.json for auto-mapping"
                            )
                            # Use a dummy path that will fail validation
                            odoo_source = Path("/invalid/path")
                        else:
                            odoo_source = Path(odoo_source).expanduser()

                        # Generate or update map
                        map_generator = ModuleModelMapGenerator(
                            project_root=project_root,
                            odoo_source=odoo_source,
                            verbose=True,
                        )

                        map_result = map_generator.generate_or_update_map(
                            extracted_models=extracted_models,
                            component_stats=component_stats,
                        )

                        # Report results
                        self.log(f"\n{'=' * 70}")
                        self.log("MODULE-MODEL MAP SUMMARY")
                        self.log(f"{'=' * 70}")
                        self.log(
                            f"\nMap file: {project_root / 'studio' / 'module_model_map.toml'}"
                        )
                        self.log(f"  Total models: {map_result.total_models}")
                        self.log(f"  Mapped: {map_result.mapped_models}")

                        if map_result.new_models > 0:
                            self.log(f"  New models: {map_result.new_models}")

                        if map_result.preserved_mappings > 0:
                            self.log(
                                f"  Preserved user mappings: {map_result.preserved_mappings}"
                            )

                        if map_result.unmapped_models > 0:
                            self.log(
                                f"\n⚠ Action required: {map_result.unmapped_models} model(s) need assignment"
                            )
                            self.log(
                                f"  → Edit studio/module_model_map.toml to assign TO_BE_PROVIDED models"
                            )
                            self.log(
                                f"  → Then run: ./.odoo-sync/cli.py generate-modules --execute"
                            )

                        if map_result.deprecated_models > 0:
                            self.log(
                                f"\n  Deprecated: {map_result.deprecated_models} (not in latest extraction)"
                            )

                except Exception as e:
                    # Don't fail extraction if map generation fails
                    self.log(
                        f"\n⚠ Warning: Module-model map generation failed: {e}"
                    )
                    if self.debug:
                        import traceback

                        traceback.print_exc()
                    self.log(
                        "  Extraction completed successfully, but map file was not updated"
                    )

            return EXIT_SUCCESS

        except ConfigurationError as e:
            self.log_error(str(e))
            return e.exit_code
        except APIError as e:
            self.log_error(str(e))
            return e.exit_code
        except Exception as e:
            if self.debug:
                import traceback

                traceback.print_exc()
            self.log_error(f"Extraction failed: {str(e)}")
            return EXIT_GENERAL_ERROR

        except ConfigurationError as e:
            self.log_error(str(e))
            return e.exit_code
        except CLIError as e:
            self.log_error(str(e))
            return e.exit_code
        except Exception as e:
            if self.debug:
                import traceback

                traceback.print_exc()
            self.log_error(f"TODO generation failed: {str(e)}")
            return EXIT_GENERAL_ERROR

    def cmd_generate_modules(self, args):
        """Generate module-based structure using pre-validated map (V1.1.3)."""
        try:
            config = self._load_config()
            project_root = self.project_root or Path.cwd()

            dry_run = not args.execute
            self.log("=" * 70)
            self.log("MODULE-BASED STRUCTURE GENERATION (V1.1.3)")
            self.log("=" * 70)

            # Connect to implementation Odoo for re-fetching incomplete data
            self.log("\nConnecting to Implementation Odoo...")
            odoo_client = self._connect_to_implementation_odoo(required=False)
            if odoo_client:
                self.log("✓ Connected (will re-fetch incomplete view data if needed)")
            else:
                self.log("  Continuing without Odoo client (may fail on incomplete data)")

            # Load map file
            self.log("\nLoading module-model map...")
            map_file = project_root / "studio" / "module_model_map.toml"
            if not map_file.exists():
                raise CLIError(
                    "Module-model map not found: studio/module_model_map.toml\n"
                    "Run './.odoo-sync/cli.py extract --execute' first to generate it."
                )

            self.log(f"✓ Found map file: {map_file}")

            # Load and validate map
            try:
                mapper = ModuleMapper(map_file)
                validation_errors = mapper.validate_map()

                if validation_errors:
                    error_msg = "Module-model map has validation errors:\n\n"
                    for i, error in enumerate(validation_errors, 1):
                        error_msg += f"{i}. {error}\n"
                    error_msg += (
                        f"\nEdit {map_file} to fix these issues:\n"
                        f"  - Move models from [modules.TO_BE_PROVIDED] to appropriate module sections\n"
                        f"  - Remove or reassign models in [modules.DEPRECATED]\n"
                        f"\nThen re-run: ./.odoo-sync/cli.py generate-modules --execute"
                    )
                    raise CLIError(error_msg)

                model_module_map = mapper.load_map()
                stats = mapper.get_statistics()
                self.log(
                    f"✓ Map validated: {stats['mapped_models']} models ready"
                )

            except ValueError as e:
                raise CLIError(str(e))
            except Exception as e:
                raise CLIError(f"Failed to load module map: {e}")

            # Check extraction results exist
            extraction_dir = (
                project_root / ".odoo-sync" / "data" / "extraction-results"
            )
            if not extraction_dir.exists():
                raise CLIError(
                    "No extraction results found. Run './.odoo-sync/cli.py extract --execute' first."
                )

            # Load components
            self.log("\nLoading extraction results...")
            try:
                components = load_extraction_results(extraction_dir)
                if not components:
                    self.log("No components found in extraction results.")
                    return EXIT_SUCCESS
            except Exception as e:
                raise CLIError(f"Failed to load extraction results: {e}")

            self.log(f"✓ Loaded {len(components)} components")

            # Initialize generator (V1.1.3 - with map dict, not ModuleMapper)
            generator = ModuleGenerator(
                project_root=project_root,
                model_module_map=model_module_map,
                odoo_client=odoo_client,
                dry_run=dry_run,
                file_manager=self.file_manager,
            )

            # Generate structure (no custom_mappings parameter in V1.1.3)
            self.log("\nGenerating module-based structure...")
            try:
                result = generator.generate_structure(components)
            except ModuleGeneratorError as e:
                raise CLIError(str(e))

            # Handle unmapped views (views with no model)
            unmapped_views = result.get("unmapped_views", [])
            if unmapped_views:
                self.log(
                    f"\n⚠ Found {len(unmapped_views)} view(s) with no model"
                )
                self.log("These views could not be assigned to a module.")
                self.log("\nUnmapped views:")
                for view_name in unmapped_views:
                    self.log(f"  • {view_name}")

            # Display summary
            self.log("\n" + "=" * 70)
            self.log("GENERATION COMPLETE")
            self.log("=" * 70)

            if result.get("backup_created"):
                self.log(
                    f"\nBackup created: {Path(result['backup_created']).name}"
                )

            self.log(f"\nModules generated: {len(result.get('modules', []))}")
            for module in sorted(result.get("modules", [])):
                self.log(f"  • {module}/")

            self.log(f"\nFiles created:")
            self.log(
                f"  Models:          {result['files_created']['models']} files"
            )
            self.log(
                f"  Views:           {result['files_created']['views']} files"
            )
            self.log(
                f"  Server Actions:  {result['files_created']['server_actions']} files"
            )
            self.log(
                f"  Automations:     {result['files_created']['automations']} files"
            )
            self.log(
                f"  Reports:         {result['files_created']['reports']} files"
            )

            if result.get("warnings"):
                self.log(f"\nWarnings: {len(result['warnings'])}")
                for warning in result["warnings"][:5]:
                    self.log_warning(f"  {warning}")
                if len(result["warnings"]) > 5:
                    self.log(
                        f"  ... and {len(result['warnings']) - 5} more warnings"
                    )

            if result.get("errors"):
                self.log(f"\nErrors: {len(result['errors'])}")
                for error in result["errors"][:5]:
                    self.log_error(f"  {error}")
                if len(result["errors"]) > 5:
                    self.log(
                        f"  ... and {len(result['errors']) - 5} more errors"
                    )

            if dry_run:
                self.log(f"\n[DRY-RUN MODE] No files were written.")
                self.log("Run with --execute to generate module structure.")
            else:
                self.log(f"\nModule structure generated successfully!")
                self.log(f"Location: {project_root}")
                self.log(
                    f"\n→ Next step: ./.odoo-sync/cli.py generate-feature-user-story-map --execute"
                )

            return EXIT_SUCCESS

        except (ConfigurationError, CLIError) as e:
            self.log_error(str(e))
            return e.exit_code
        except Exception as e:
            if self.debug:
                import traceback

                traceback.print_exc()
            self.log_error(f"Module generation failed: {e}")
            return EXIT_GENERAL_ERROR

    def cmd_generate_feature_user_story_map(self, args):
        """Generate feature-user story mapping from extraction results or
        source code (V1.1.7)."""
        try:
            source_dir = getattr(args, "source", None)

            # For source-based workflows, we don't need Odoo config
            if not source_dir:
                config = self._load_config()

            project_root = self.project_root or Path.cwd()

            dry_run = not args.execute
            source_dir = getattr(args, "source", None)

            self.log("=" * 70)
            if source_dir:
                self.log(
                    "FEATURE-USER STORY MAP GENERATION FROM SOURCE CODE (V1.1.7)"
                )
            else:
                self.log("FEATURE-USER STORY MAP GENERATION (V1.1.7)")
            self.log("=" * 70)

            # Step 1: Check source or extraction results exist
            if source_dir:
                source_path = Path(source_dir)
                if not source_path.exists() or not source_path.is_dir():
                    raise CLIError(f"Source directory not found: {source_dir}")
                self.log(f"✓ Using source directory: {source_path}")
            else:
                extraction_dir = (
                    project_root / ".odoo-sync" / "data" / "extraction-results"
                )
                if not extraction_dir.exists():
                    raise CLIError(
                        "No extraction results found.\n"
                        "Run './.odoo-sync/cli.py extract --execute' first,\n"
                        "or use --source <directory> for source-based workflow."
                    )
                self.log(f"✓ Using extraction results: {extraction_dir}")

            # Step 2: Load feature mapping
            self.log("\nLoading feature mapping...")
            mapping_path = project_root / ".odoo-sync" / "feature-mapping.json"

            mapping = (
                FeatureMapping.from_file(mapping_path)
                if mapping_path.exists()
                else FeatureMapping.default()
            )

            if mapping_path.exists():
                self.log(f"✓ Using custom feature mapping: {mapping_path}")
            else:
                self.log("  Using default feature mapping (group by model)")

            # Step 3: Load components
            self.log("\nDetecting features...")
            if source_dir:
                components = load_source_components(Path(source_dir))
                self.log(
                    f"✓ Parsed {len(components)} components from source code"
                )
            else:
                components = load_extraction_results(extraction_dir)
                self.log(
                    f"✓ Loaded {len(components)} components from extraction results"
                )

            if not components:
                self.log("No components found.")
                return EXIT_SUCCESS

            detector = FeatureDetector(mapping)
            features = detector.detect_features(components)

            self.log(
                f"✓ Detected {len(features)} features from {len(components)} components"
            )

            if not components:
                self.log("No components found in extraction results.")
                return EXIT_SUCCESS

            detector = FeatureDetector(mapping)
            features = detector.detect_features(components)

            self.log(
                f"✓ Detected {len(features)} features from {len(components)} components"
            )

            # Step 4: Generate/update feature-user story map
            map_generator = FeatureUserStoryMapGenerator(
                project_root=project_root, verbose=True
            )

            if dry_run:
                self.log(
                    "\n[DRY RUN] Would generate feature_user_story_map.toml with:"
                )
                result = map_generator.preview_map(features, len(components))
                self.log(f"  - {result.total_features} features")
                self.log(f"  - {result.total_user_stories} user stories")
                self.log(f"  - {result.total_components} components")
                if result.user_stories_needing_review > 0:
                    self.log(
                        f"  - {result.user_stories_needing_review} features need review"
                    )
                self.log("\nRun with --execute to create the file")
            else:
                result = map_generator.generate_or_update_map(
                    features, len(components)
                )

                self.log(f"\n{'=' * 70}")
                self.log("MAP GENERATION COMPLETE")
                self.log(f"{'=' * 70}")
                self.log(
                    f"\nMap file: {project_root / 'studio' / 'feature_user_story_map.toml'}"
                )
                self.log(f"  Total features: {result.total_features}")
                self.log(f"  Total user stories: {result.total_user_stories}")

                if result.new_features > 0:
                    self.log(f"  New features: {result.new_features}")

                if result.preserved_features > 0:
                    self.log(
                        f"  Preserved features: {result.preserved_features}"
                    )

                if result.user_stories_needing_review > 0:
                    self.log(
                        f"\n⚠ {result.user_stories_needing_review} feature(s) may need review"
                    )
                    self.log(
                        "  Edit studio/feature_user_story_map.toml to customize user story groupings"
                    )
                else:
                    self.log("\n✓ All user stories ready")

            return EXIT_SUCCESS

        except (ConfigurationError, CLIError) as e:
            self.log_error(str(e))
            return e.exit_code
        except Exception as e:
            if self.debug:
                import traceback

                traceback.print_exc()
            self.log_error(f"Feature-user story map generation failed: {e}")
            return EXIT_GENERAL_ERROR

    def cmd_sync(self, args):
        """Sync feature_user_story_map.toml to Odoo tasks."""
        try:
            config = self._load_config()
            project_root = self.project_root or Path.cwd()

            # Validate configuration
            dev = self.config_manager.development
            if dev.read_only:
                raise CLIError(
                    "Development instance is read-only. Cannot sync."
                )
            if not dev.project or not dev.project.id:
                raise CLIError(
                    "project.id not configured. Run './.odoo-sync/cli.py init' first."
                )

            toml_path = project_root / "studio" / "feature_user_story_map.toml"
            if not toml_path.exists():
                raise CLIError(
                    "feature_user_story_map.toml not found. Run './.odoo-sync/cli.py generate-feature-user-story-map --execute' first."
                )

            dry_run = not args.execute
            project_id = dev.project.id

            self.log("Syncing feature_user_story_map.toml → Odoo...\n")

            # Connect to Odoo
            client = OdooClient.from_config(dev)
            connection = client.test_connection()
            if not connection["success"]:
                raise APIError(
                    f"Could not connect to Odoo: {connection.get('error')}"
                )

            self.log(
                f"✓ Connected to {dev.url} as {connection['user_name']}\n"
            )

            # Initialize sync engine
            sync_engine = SyncEngine(
                client=client,
                project_id=project_id,
                project_root=project_root,
            )

            if dry_run:
                # Dry run - just validate connectivity
                result = sync_engine.sync(dry_run=True)
                self.log("✓ Connectivity validated\n")
                self.log("[DRY-RUN MODE] No changes were made.")
                self.log("Run with --execute to create tasks in Odoo.")
                return EXIT_SUCCESS

            # Execute sync
            result = sync_engine.sync(dry_run=False)

            # Display summary
            self.log("\n" + "=" * 50)
            self.log("Sync Complete")
            self.log("=" * 50 + "\n")

            if result.features_created > 0:
                self.log(f"✓ Created {result.features_created} feature task(s)")

            if result.user_stories_created > 0:
                self.log(f"✓ Created {result.user_stories_created} user story subtask(s)")

            if result.features_validated > 0:
                self.log(f"✓ Validated {result.features_validated} existing feature task(s)")

            if result.user_stories_validated > 0:
                self.log(f"✓ Validated {result.user_stories_validated} existing user story task(s)")

            if result.features_recreated > 0:
                self.log(f"⚠ Recreated {result.features_recreated} feature task(s) (task_id was invalid)")

            if result.user_stories_recreated > 0:
                self.log(f"⚠ Recreated {result.user_stories_recreated} user story task(s) (task_id was invalid)")

            if result.user_stories_imported > 0:
                self.log(f"✓ Imported {result.user_stories_imported} user story(s) from Odoo")

            total_changes = (
                result.features_created + result.user_stories_created +
                result.features_recreated + result.user_stories_recreated +
                result.user_stories_imported
            )
            if total_changes == 0 and result.features_validated == 0 and result.user_stories_validated == 0:
                self.log("No tasks to process.")
            elif total_changes == 0:
                self.log("\nAll tasks validated. No changes needed.")

            if result.errors:
                self.log(f"\nWarnings: {len(result.errors)} errors occurred")
                for error in result.errors:
                    self.log(f"  - {error}")

            return EXIT_SUCCESS

        except (ConfigurationError, APIError, CLIError) as e:
            self.log_error(str(e))
            return e.exit_code
        except Exception as e:
            if self.debug:
                import traceback

                traceback.print_exc()
            self.log_error(f"Sync failed: {str(e)}")
            return EXIT_GENERAL_ERROR

    def cmd_status(self, args):
        """Display configuration and connection status."""
        try:
            config = self._load_config()

            self.log("=" * 50)
            self.log("Odoo Project Sync Status")
            self.log("=" * 50 + "\n")

            # Implementation instance
            self.log("Implementation Instance (Read-Only)")
            self.log("-" * 50)
            impl = self.config_manager.implementation
            self.log(f"URL:      {impl.url}")
            self.log(f"Database: {impl.database}")
            self.log(f"Username: {impl.username}")

            try:
                client = OdooClient.from_config(impl)
                result = client.test_connection()
                if result["success"]:
                    self.log(
                        f"Status:   ✓ Connected ({result['server_version']})"
                    )
                else:
                    self.log(f"Status:   ✗ Failed: {result.get('error')}")
            except Exception as e:
                self.log(f"Status:   ✗ Error: {str(e)}")

            # Development instance
            self.log("\nDevelopment Instance (Read/Write)")
            self.log("-" * 50)
            dev = self.config_manager.development
            self.log(f"URL:      {dev.url}")
            self.log(f"Database: {dev.database}")
            self.log(f"Username: {dev.username}")
            if dev.project:
                self.log(
                    f"Project:  {dev.project.name or 'N/A'} (ID: {dev.project.id})"
                )

            try:
                client = OdooClient.from_config(dev)
                result = client.test_connection()
                if result["success"]:
                    self.log(
                        f"Status:   ✓ Connected ({result['server_version']})"
                    )
                else:
                    self.log(f"Status:   ✗ Failed: {result.get('error')}")
            except Exception as e:
                self.log(f"Status:   ✗ Error: {str(e)}")

            # Extraction filters
            self.log("\nExtraction Filters")
            self.log("-" * 50)
            filters = self.config_manager.extraction_filters

            self.log(f"Custom Fields:  {len(filters.custom_fields)} filter(s)")
            self.log(
                f"Server Actions: {len(filters.server_actions)} filter(s)"
            )
            self.log(f"Automations:    {len(filters.automations)} filter(s)")
            self.log(f"Views:          {len(filters.views)} filter(s)")
            self.log(f"Reports:        {len(filters.reports)} filter(s)")

            # Sync settings
            self.log("\nSync Settings")
            self.log("-" * 50)
            sync = self.config_manager.sync_config
            self.log(f"Conflict Resolution: {sync.conflict_resolution}")
            self.log(
                f"Preserve Logged Time: {'Yes' if sync.preserve_logged_time else 'No'}"
            )
            self.log(
                f"Auto-Move Completed:  {'Yes' if sync.auto_move_completed else 'No'}"
            )

            return EXIT_SUCCESS

        except ConfigurationError as e:
            self.log_error(str(e))
            self.log(
                "\nRun './.odoo-sync/cli.py init' to set up configuration."
            )
            return e.exit_code
        except Exception as e:
            if self.debug:
                import traceback

                traceback.print_exc()
            self.log_error(f"Status check failed: {str(e)}")
            return EXIT_GENERAL_ERROR

    def cmd_compare_toml(self, args):
        """Compare two TOML files and write markdown report."""
        try:
            file1 = Path(args.file1)
            file2 = Path(args.file2)
            output = args.output

            if not file1.exists():
                raise CLIError(f"File not found: {file1}")
            if not file2.exists():
                raise CLIError(f"File not found: {file2}")

            # Run comparison
            generate_markdown_comparison(str(file1), str(file2), output)
            self.log(f"✓ Comparison complete: {output}")
            return EXIT_SUCCESS

        except CLIError as e:
            self.log_error(str(e))
            return e.exit_code
        except Exception as e:
            if self.debug:
                import traceback

                traceback.print_exc()
            self.log_error(f"TOML comparison failed: {str(e)}")
            return EXIT_GENERAL_ERROR

    def cmd_enrich_stories(self, args):
        """Enrich stories with AI and write HTML descriptions to Odoo tasks."""
        try:
            project_root = self.project_root
            map_file = project_root / "studio" / "feature_user_story_map.toml"
            
            if not map_file.exists():
                raise CLIError(
                    f"feature_user_story_map.toml not found: {map_file}\n"
                    "Run 'generate-feature-user-story-map --execute' first."
                )
            
            # Load config
            if args.config and Path(args.config).exists():
                config = EnricherConfig.from_file(Path(args.config))
            else:
                config = EnricherConfig.default()
            
            if args.provider:
                config.user_story_enricher.ai_provider = args.provider
            
            dry_run = not args.execute
            
            self.log(f"📝 Enriching user stories with AI...")
            self.log(f"   Source: {map_file}")
            self.log(f"   Provider: {config.user_story_enricher.ai_provider}")
            self.log(f"   Output: Odoo task descriptions (HTML)")
            
            if dry_run:
                self.log("   Mode: Dry run (preview only)")
                # Run dry-run enrichment (no Odoo needed)
                enricher = UserStoryEnricher(config)
                result = enricher.enrich_stories_in_place(project_root, dry_run=True)
                
                self.log(f"\n📋 Dry run results:")
                self.log(f"   Would enrich:")
                self.log(f"     - {result['features_enriched']} features")
                self.log(f"     - {result['user_stories_enriched']} user stories")
                self.log(f"\n   Use --execute to apply changes and write to Odoo")
                return EXIT_SUCCESS
            
            # For non-dry-run, we need Odoo connection
            self.log(f"\n   Connecting to Odoo...")
            
            # Validate Odoo configuration
            odoo_config = self._load_config()
            dev = self.config_manager.development
            if dev.read_only:
                raise CLIError(
                    "Development instance is read-only. Cannot write to Odoo."
                )
            if not dev.project or not dev.project.id:
                raise CLIError(
                    "project.id not configured. Run './.odoo-sync/cli.py init' first."
                )
            
            # Connect to Odoo
            client = OdooClient.from_config(dev)
            connection = client.test_connection()
            if not connection["success"]:
                raise APIError(
                    f"Could not connect to Odoo: {connection.get('error')}"
                )
            
            self.log(f"   ✓ Connected to {dev.url} as {connection['user_name']}")
            
            # Run enrichment with Odoo client
            enricher = UserStoryEnricher(config)
            result = enricher.enrich_stories_in_place(
                project_root, 
                dry_run=False,
                odoo_client=client
            )
            
            # Report results
            self.log(f"\n✅ AI enrichment complete!")
            if result.get("backup_toml"):
                self.log(f"   Backup: {result['backup_toml'].name}")
            self.log(f"   Updated: enrich-status in feature_user_story_map.toml")
            self.log(f"\n   Stats:")
            self.log(f"     - Features enriched: {result['features_enriched']}")
            self.log(f"     - User stories enriched: {result['user_stories_enriched']}")
            self.log(f"     - Odoo tasks updated: {result['odoo_tasks_updated']}")
            
            if result['errors']:
                self.log(f"\n   ⚠ Errors: {len(result['errors'])}")
                for error in result['errors'][:5]:
                    self.log(f"     - {error}")
            
            return EXIT_SUCCESS
            
        except CLIError as e:
            self.log_error(str(e))
            return e.exit_code
        except Exception as e:
            if self.debug:
                import traceback
                traceback.print_exc()
            self.log_error(f"Story enrichment failed: {str(e)}")
            return EXIT_GENERAL_ERROR

    def cmd_estimate_effort(self, args):
        """Estimate effort in-place, update TOML with complexity/time."""
        try:
            project_root = self.project_root
            map_file = project_root / "studio" / "feature_user_story_map.toml"
            
            if not map_file.exists():
                raise CLIError(
                    f"feature_user_story_map.toml not found: {map_file}\n"
                    "Run 'generate-feature-user-story-map --execute' first."
                )
            
            # Load config
            if args.config and Path(args.config).exists():
                config = EnricherConfig.from_file(Path(args.config))
            else:
                config = EnricherConfig.default()
            
            dry_run = not args.execute
            
            self.log(f"📊 Estimating effort (in-place)...")
            self.log(f"   Source: {map_file}")
            
            if dry_run:
                self.log("   Mode: Dry run (preview only)")
            
            # Run estimation using UserStoryEnricher
            enricher = UserStoryEnricher(config)
            result = enricher.estimate_effort_in_place(
                project_root, dry_run=dry_run
            )
            
            # Report results
            if not dry_run:
                self.log(f"\n✅ Effort estimation complete!")
                if result.get("backup_toml"):
                    self.log(f"   Backup: {result['backup_toml'].name}")
                self.log(f"   Updated: feature_user_story_map.toml")
                self.log(f"\n   Stats:")
                self.log(f"     - Components estimated: {result['components_enriched']}")
                self.log(f"     - Total hours: {result['total_hours']:.1f}h")
                
                if result['errors']:
                    self.log(f"\n   ⚠ Errors: {len(result['errors'])}")
                    for error in result['errors'][:5]:
                        self.log(f"     - {error}")
                
                # Create/update Implementation Overview task in Odoo
                self.log(f"\n📋 Creating Implementation Overview task in Odoo...")
                try:
                    self._create_implementation_overview_task(map_file)
                    self.log(f"✅ Implementation Overview task created/updated successfully!")
                except Exception as overview_error:
                    # CRITICAL: Task creation failure should fail the entire command
                    error_msg = f"❌ FAILED TO CREATE IMPLEMENTATION OVERVIEW TASK: {str(overview_error)}"
                    self.log_error(error_msg)
                    if self.debug:
                        import traceback
                        traceback.print_exc()
                    raise CLIError(error_msg, EXIT_GENERAL_ERROR)
            else:
                self.log(f"\n📋 Dry run results:")
                self.log(f"   Would estimate: {result['components_enriched']} components")
                self.log(f"\n   Use --execute to apply changes")
            
            return EXIT_SUCCESS
            
        except CLIError as e:
            self.log_error(str(e))
            return e.exit_code
        except Exception as e:
            if self.debug:
                import traceback
                traceback.print_exc()
            self.log_error(f"Effort estimation failed: {str(e)}")
            return EXIT_GENERAL_ERROR

    def _create_implementation_overview_task(self, map_file: Path):
        """Create or update Implementation Overview task in Odoo.
        
        Args:
            map_file: Path to feature_user_story_map.toml
            
        Raises:
            CLIError: If task creation/update fails
        """
        # Load main config to get Odoo connection details
        config = self._load_config()
        
        # Get target instance (write instance)
        target_instance = None
        for inst_name, inst_config in config.instances.items():
            if not inst_config.read_only:
                target_instance = inst_config
                break
        
        if not target_instance:
            raise CLIError(
                "No write-enabled Odoo instance configured. "
                "Check odoo-instances.json configuration.",
                EXIT_CONFIG_ERROR
            )
        
        # Verify project_id is configured
        project_id = None
        if target_instance.project and target_instance.project.id:
            project_id = target_instance.project.id
        
        if not project_id:
            raise CLIError(
                "No project_id configured in development instance. "
                "Check odoo-instances.json configuration.",
                EXIT_CONFIG_ERROR
            )
        
        # Create Odoo client and task manager
        client = OdooClient.from_config(target_instance)
        task_manager = TaskManager(client, project_id)
        
        # Fetch timesheet data for all tasks in the TOML
        self.log(f"   Fetching timesheet data from Odoo...")
        timesheet_data = {}
        with open(map_file, "rb") as f:
            import tomllib
            toml_data = tomllib.load(f)
            features = toml_data.get("features", {})
            
            for feature_name, feature_def in features.items():
                # Fetch feature task timesheets
                feature_task_id = feature_def.get("task_id")
                if feature_task_id and feature_task_id > 0:
                    try:
                        timesheet_data[feature_task_id] = client.fetch_task_timesheets(feature_task_id)
                    except Exception as e:
                        self.log(f"   ⚠ Failed to fetch timesheets for feature task {feature_task_id}: {e}")
                        timesheet_data[feature_task_id] = 0.0
                
                # Fetch user story task timesheets
                user_stories = feature_def.get("user_stories", [])
                if isinstance(user_stories, dict):
                    story_list = list(user_stories.values())
                else:
                    story_list = user_stories
                    
                for story in story_list:
                    story_task_id = story.get("task_id")
                    if story_task_id and story_task_id > 0:
                        try:
                            timesheet_data[story_task_id] = client.fetch_task_timesheets(story_task_id)
                        except Exception as e:
                            self.log(f"   ⚠ Failed to fetch timesheets for story task {story_task_id}: {e}")
                            timesheet_data[story_task_id] = 0.0
        
        self.log(f"   ✓ Fetched timesheet data for {len(timesheet_data)} tasks")
        
        # Generate HTML description from TOML with timesheet data
        html_description = ImplementationOverviewGenerator.generate_from_toml(map_file, timesheet_data)
        
        # Task details
        task_name = "Implementation Overview"
        stage_name = TaskManager.STAGE_DONE
        tags = ["Stats"]
        
        # Check if task already exists
        existing_task_id = task_manager.find_task_by_name(task_name)
        
        if existing_task_id:
            # Update existing task
            self.log(f"   Found existing task (ID: {existing_task_id}), updating...")
            task_manager.update_task(
                existing_task_id,
                {
                    "description": html_description,
                    "stage_id": task_manager.get_stage_id(stage_name),
                    "tag_ids": [(6, 0, task_manager.ensure_tags(tags, dry_run=False))],
                },
                dry_run=False
            )
        else:
            # Create new task
            self.log(f"   Creating new Implementation Overview task...")
            task_id = task_manager.create_task(
                name=task_name,
                description=html_description,
                stage_name=stage_name,
                tags=tags,
                dry_run=False
            )
            self.log(f"   Task created with ID: {task_id}")

    def cmd_anthropic_models(self, args):
        """List available Anthropic models from the API."""
        print("\n=== Anthropic Models ===")
        print("Querying Anthropic API for available models...\n")
        
        import os
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        
        if not api_key:
            print("Error: ANTHROPIC_API_KEY not found in environment variables")
            print("Please set it in your .odoo-sync/.env file")
            return EXIT_CONFIG_ERROR
        
        try:
            from anthropic import Anthropic
        except ImportError:
            print("Error: anthropic package not installed")
            print("Run: pip install anthropic")
            return EXIT_GENERAL_ERROR
        
        try:
            client = Anthropic(api_key=api_key)
            response = client.models.list()
            
            if hasattr(response, 'data') and response.data:
                print(f"Found {len(response.data)} models:\n")
                for model in response.data:
                    print(f"  • {model.id}")
                    if hasattr(model, 'display_name'):
                        print(f"    Display Name: {model.display_name}")
                    if hasattr(model, 'created_at'):
                        print(f"    Created: {model.created_at}")
                    print()
                
                print("\nUpdate your .env file with one of these models:")
                print("  AI_MODEL=<model-id>")
            else:
                print("No models found or API doesn't support listing models")
                return EXIT_GENERAL_ERROR
                
        except Exception as e:
            print(f"Error querying API: {e}")
            return EXIT_API_ERROR
        
        return EXIT_SUCCESS

    def cmd_update_task_tables(self, args):
        """Update HTML tables in Odoo task descriptions without AI enrichment."""
        try:
            project_root = self.project_root
            map_file = project_root / "studio" / "feature_user_story_map.toml"
            
            if not map_file.exists():
                raise CLIError(
                    f"feature_user_story_map.toml not found: {map_file}\n"
                    "Run 'generate-feature-user-story-map --execute' first."
                )
            
            dry_run = not args.execute
            features_filter = args.features if hasattr(args, 'features') else None
            
            self.log(f"🔄 Updating HTML tables in Odoo tasks...")
            self.log(f"   Source: {map_file}")
            if features_filter:
                self.log(f"   Features: {', '.join(features_filter)}")
            else:
                self.log(f"   Features: All")
            self.log(f"   Output: Odoo task descriptions (HTML)")
            
            if dry_run:
                self.log("   Mode: Dry run (preview only)")
                # Run dry-run (no Odoo needed)
                config = EnricherConfig.default()
                enricher = UserStoryEnricher(config)
                result = enricher.update_task_tables_in_place(
                    project_root, 
                    features_filter=features_filter,
                    dry_run=True
                )
                
                self.log(f"\n📋 Dry run results:")
                self.log(f"   Would update:")
                self.log(f"     - {result['features_updated']} features")
                self.log(f"     - {result['user_stories_updated']} user stories")
                self.log(f"\n   Use --execute to apply changes and write to Odoo")
                return EXIT_SUCCESS
            
            # For non-dry-run, we need Odoo connection
            self.log(f"\n   Connecting to Odoo...")
            
            # Validate Odoo configuration
            odoo_config = self._load_config()
            dev = self.config_manager.development
            if dev.read_only:
                raise CLIError(
                    "Development instance is read-only. Cannot write to Odoo."
                )
            if not dev.project or not dev.project.id:
                raise CLIError(
                    "project.id not configured. Run './.odoo-sync/cli.py init' first."
                )
            
            # Connect to Odoo
            client = OdooClient.from_config(dev)
            connection = client.test_connection()
            if not connection["success"]:
                raise APIError(
                    f"Could not connect to Odoo: {connection.get('error')}"
                )
            
            # Create enricher and run update
            config = EnricherConfig.default()
            enricher = UserStoryEnricher(config)
            result = enricher.update_task_tables_in_place(
                project_root, 
                features_filter=features_filter,
                dry_run=False,
                odoo_client=client
            )
            
            # Report results
            self.log(f"\n✅ HTML table update complete!")
            self.log(f"\n   Stats:")
            self.log(f"     - Features updated: {result['features_updated']}")
            self.log(f"     - User stories updated: {result['user_stories_updated']}")
            self.log(f"     - Odoo tasks updated: {result['odoo_tasks_updated']}")
            
            if result['errors']:
                self.log(f"\n   ⚠ Errors: {len(result['errors'])}")
                for error in result['errors'][:5]:
                    self.log(f"     - {error}")
            
            # Also update Implementation Overview task
            try:
                self.log(f"\n📋 Updating Implementation Overview task in Odoo...")
                self._create_implementation_overview_task(map_file)
                self.log(f"✅ Implementation Overview task updated successfully!")
            except Exception as overview_error:
                error_msg = f"❌ FAILED TO UPDATE IMPLEMENTATION OVERVIEW TASK: {str(overview_error)}"
                self.log_error(error_msg)
                if self.debug:
                    import traceback
                    traceback.print_exc()
            
            return EXIT_SUCCESS
            
        except CLIError as e:
            self.log_error(str(e))
            return e.exit_code
        except Exception as e:
            if self.debug:
                import traceback
                traceback.print_exc()
            self.log_error(f"Table update failed: {str(e)}")
            return EXIT_GENERAL_ERROR

    def cmd_enrich_all(self, args):
        """Run full enrichment: AI stories + effort estimation, update TOML."""
        self.log(f"🚀 Running full enrichment pipeline...")
        self.log(f"   Step 1: AI story enrichment")
        self.log(f"   Step 2: Effort estimation\n")
        
        # Step 1: Run enrich-stories
        self.log("=" * 50)
        self.log("STEP 1: AI Story Enrichment")
        self.log("=" * 50)
        result1 = self.cmd_enrich_stories(args)
        
        if result1 != EXIT_SUCCESS:
            self.log_error("Story enrichment failed, aborting pipeline.")
            return result1
        
        # Step 2: Run estimate-effort
        self.log("\n" + "=" * 50)
        self.log("STEP 2: Effort Estimation")
        self.log("=" * 50)
        result2 = self.cmd_estimate_effort(args)
        
        if result2 != EXIT_SUCCESS:
            self.log_error("Effort estimation failed.")
            return result2
        
        self.log("\n" + "=" * 50)
        self.log("✅ Full enrichment pipeline complete!")
        self.log("=" * 50)
        
        return EXIT_SUCCESS

    def _load_config(self) -> Any:
        """Load configuration from project root."""
        try:
            return self.config_manager.config
        except ConfigError as e:
            raise ConfigurationError(str(e))
        except Exception as e:
            raise ConfigurationError(f"Failed to load configuration: {str(e)}")

    def _connect_to_implementation_odoo(self, required: bool = True) -> Optional[OdooClient]:
        """Connect to implementation Odoo instance.
        
        Args:
            required: If True, raise APIError on connection failure.
                     If False, return None on failure and log warning.
        
        Returns:
            OdooClient instance or None if connection failed and not required.
            
        Raises:
            APIError: If connection fails and required=True.
        """
        try:
            client = OdooClient.from_config(self.config_manager.implementation)
            result = client.test_connection()
            if not result.get("success"):
                error_msg = f"Connection failed: {result.get('error')}"
                if required:
                    raise APIError(error_msg)
                else:
                    self.log(f"⚠ {error_msg}")
                    return None
            return client
        except Exception as e:
            if required:
                raise APIError(f"Failed to connect to Odoo: {e}")
            else:
                self.log(f"⚠ Could not connect to Odoo: {e}")
                return None

    def run(self, argv=None):
        """Main entry point."""
        parser = argparse.ArgumentParser(
            prog="odoo-sync",
            description="Odoo Project Sync - Extract and synchronize Odoo customizations",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  odoo-sync init                                    # Interactive setup wizard
  odoo-sync extract --execute                       # Extract customizations
        odoo-sync generate-modules --execute              # Generate module structure
        odoo-sync generate-feature-user-story-map --execute  # Generate user story map (V1.1.7)
        odoo-sync compare-toml <file1.toml> <file2.toml> --output toml_compare.md  # Compare two TOML files
  odoo-sync sync --execute                          # Sync feature_user_story_map.toml → Odoo
  odoo-sync status                                  # Show configuration status

Workflow:
  1. extract → 2. generate-modules → 3. generate-feature-user-story-map → 4. sync

For help on a specific command:
  odoo-sync [command] --help
            """,
        )

        parser.add_argument(
            "--version", action="version", version="%(prog)s 1.0.0"
        )
        parser.add_argument(
            "--debug",
            "-d",
            action="store_true",
            help="Show stack traces on error",
        )
        parser.add_argument(
            "--config-path",
            "-c",
            type=str,
            help="Override .odoo-sync directory path",
        )

        subparsers = parser.add_subparsers(
            dest="command", help="Command to run"
        )

        # init
        init_parser = subparsers.add_parser(
            "init", help="Initialize configuration (interactive setup)"
        )

        # extract
        extract_parser = subparsers.add_parser(
            "extract", help="Extract Studio customizations"
        )
        extract_parser.add_argument(
            "--execute",
            "-e",
            action="store_true",
            help="Write extraction results to files (default is dry-run)",
        )

        # generate-modules
        modules_parser = subparsers.add_parser(
            "generate-modules",
            help="Generate module structure from extraction results",
        )
        modules_parser.add_argument(
            "--execute",
            "-e",
            action="store_true",
            help="Write module structure to project root (default is dry-run)",
        )

        # generate-feature-user-story-map (V1.1.7)
        map_parser = subparsers.add_parser(
            "generate-feature-user-story-map",
            help="Generate feature-user story mapping (V1.1.7)",
        )
        map_parser.add_argument(
            "--execute",
            "-e",
            action="store_true",
            help="Write feature_user_story_map.toml to studio/ directory (default is dry-run)",
        )
        map_parser.add_argument(
            "--source",
            "-s",
            type=str,
            help="Path to Odoo source directory (for source-based workflow)",
        )

        # sync
        sync_parser = subparsers.add_parser(
            "sync", help="Sync feature_user_story_map.toml → Odoo tasks"
        )
        sync_parser.add_argument(
            "--execute",
            "-e",
            action="store_true",
            help="Create tasks in Odoo (default is dry-run validation)",
        )

        # status
        status_parser = subparsers.add_parser(
            "status", help="Show configuration and connection status"
        )

        # compare-toml
        compare_parser = subparsers.add_parser(
            "compare-toml",
            help="Compare two TOML files and generate markdown report",
        )
        compare_parser.add_argument(
            "file1", type=str, help="First TOML file to compare"
        )
        compare_parser.add_argument(
            "file2", type=str, help="Second TOML file to compare"
        )
        compare_parser.add_argument(
            "--output",
            "-o",
            type=str,
            default="toml_compare.md",
            help="Output markdown file (default: toml_compare.md)",
        )

        # enrich-stories (AI enrichment - writes HTML to Odoo task descriptions)
        enrich_stories_parser = subparsers.add_parser(
            "enrich-stories",
            help="Enrich with AI and write HTML descriptions to Odoo tasks",
        )
        enrich_stories_parser.add_argument(
            "--execute",
            "-e",
            action="store_true",
            help="Execute enrichment (default is dry-run)",
        )
        enrich_stories_parser.add_argument(
            "--provider",
            choices=["openai", "anthropic"],
            help="AI provider to use",
        )
        enrich_stories_parser.add_argument(
            "--config",
            type=str,
            help="Path to enricher configuration TOML file",
        )

        # estimate-effort (Complexity/time estimation - updates TOML in-place)
        estimate_parser = subparsers.add_parser(
            "estimate-effort",
            help="Estimate effort in-place, update TOML with complexity/time",
        )
        estimate_parser.add_argument(
            "--execute",
            "-e",
            action="store_true",
            help="Execute estimation (default is dry-run)",
        )
        estimate_parser.add_argument(
            "--config",
            type=str,
            help="Path to enricher configuration TOML file",
        )

        # update-task-tables (Update HTML tables in Odoo without AI)
        update_tables_parser = subparsers.add_parser(
            "update-task-tables",
            help="Update HTML tables in Odoo task descriptions (no AI, no TOML changes)",
        )
        update_tables_parser.add_argument(
            "--features",
            nargs="+",
            help="Specific features to update (optional, default: all features)",
        )
        update_tables_parser.add_argument(
            "--execute",
            "-e",
            action="store_true",
            help="Execute update (default is dry-run)",
        )

        # anthropic-models (List available Anthropic models)
        models_parser = subparsers.add_parser(
            "anthropic-models",
            help="List available Anthropic models from the API",
        )

        # enrich-all (Full pipeline: AI + effort estimation)
        enrich_all_parser = subparsers.add_parser(
            "enrich-all",
            help="Run full enrichment: AI stories + effort estimation, update TOML",
        )
        enrich_all_parser.add_argument(
            "--execute",
            "-e",
            action="store_true",
            help="Execute enrichment (default is dry-run)",
        )
        enrich_all_parser.add_argument(
            "--provider",
            choices=["openai", "anthropic"],
            help="AI provider for story generation",
        )
        enrich_all_parser.add_argument(
            "--config",
            type=str,
            help="Path to enricher configuration TOML file",
        )

        # Parse arguments
        args = parser.parse_args(argv)

        # Set debug and config path
        self.debug = args.debug
        if args.config_path:
            self.project_root = Path(args.config_path).parent
        
        # Load .env file from project root (where .odoo-sync directory is)
        if not self.project_root:
            self.project_root = find_project_root()
        if self.project_root:
            load_dotenv(self.project_root)

        # Configure logging
        log_level = logging.DEBUG if self.debug else logging.INFO
        logging.basicConfig(
            level=log_level,
            format="%(message)s",
            handlers=[logging.StreamHandler(stream=sys.stdout)],
        )

        # Dispatch to command handler
        if args.command == "init":
            return self.cmd_init(args)
        elif args.command == "extract":
            return self.cmd_extract(args)
        elif args.command == "generate-modules":
            return self.cmd_generate_modules(args)
        elif args.command == "generate-feature-user-story-map":
            return self.cmd_generate_feature_user_story_map(args)
        elif args.command == "sync":
            return self.cmd_sync(args)
        elif args.command == "status":
            return self.cmd_status(args)
        elif args.command == "compare-toml":
            return self.cmd_compare_toml(args)
        elif args.command == "enrich-stories":
            return self.cmd_enrich_stories(args)
        elif args.command == "estimate-effort":
            return self.cmd_estimate_effort(args)
        elif args.command == "update-task-tables":
            return self.cmd_update_task_tables(args)
        elif args.command == "enrich-all":
            return self.cmd_enrich_all(args)
        elif args.command == "anthropic-models":
            return self.cmd_anthropic_models(args)
        else:
            parser.print_help()
            return EXIT_SUCCESS


def main():
    """Command-line entry point."""
    cli = OdooSyncCLI()
    exit_code = cli.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
