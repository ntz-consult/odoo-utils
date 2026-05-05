"""Configuration management for Odoo Project Sync."""

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from .utils import (
        find_project_root,
        load_dotenv,
        resolve_env_vars_in_dict,
    )
except ImportError:
    from utils import (
        find_project_root,
        load_dotenv,
        resolve_env_vars_in_dict,
    )


@dataclass
class ProjectConfig:
    """Development instance project configuration."""

    id: int | None = None
    name: str | None = None
    sale_line_id: int | None = None


@dataclass
class InstanceConfig:
    """Configuration for a single Odoo instance."""

    url: str
    database: str
    username: str
    api_key: str
    read_only: bool = True
    description: str = ""
    purpose: str = ""
    implementation_type: str = "studio"  # "studio" | "sh" | "custom"
    odoo_version: str = "19"
    odoo_source: str | None = None
    project: ProjectConfig | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InstanceConfig":
        """Create InstanceConfig from dictionary."""
        project_data = data.pop("project", None)
        project = None
        if project_data:
            project = ProjectConfig(**project_data)

        return cls(project=project, **data)


@dataclass
class SyncConfig:
    """Sync behavior configuration."""

    conflict_resolution: str = "prefer_local"
    time_estimation_strategy: str = "group_by_type"
    preserve_logged_time: bool = True
    auto_move_completed: bool = True
    require_confirmation: bool = False


@dataclass
class ExtractionFilters:
    """Extraction filter configuration.
    
    Filters can be provided as:
    1. Lists of lists (legacy format): [["field", "op", value]]
    2. Strings with Python domain syntax: "['field', 'op', value]" or "[('field', 'op', value)]"
    
    String format is preferred when using Python boolean values (True/False) that don't
    translate directly to JSON booleans (true/false) but are required by Odoo's domain format.
    
    ALL filters must be explicitly defined in odoo-instances.json - no defaults are provided.
    """

    custom_fields: list[list[Any]] = field(default_factory=list)
    server_actions: list[list[Any]] = field(default_factory=list)
    automations: list[list[Any]] = field(default_factory=list)
    views: list[list[Any]] = field(default_factory=list)
    reports: list[list[Any]] = field(default_factory=list)

    @staticmethod
    def _parse_filter(filter_value: Any) -> list[list[Any]]:
        """Parse a filter value that can be string or list format.
        
        Args:
            filter_value: Filter as string (Python syntax) or list
            
        Returns:
            Filter as list format
            
        Raises:
            ConfigError: If string parsing fails
        """
        if isinstance(filter_value, str):
            try:
                # Parse string as Python literal
                parsed = ast.literal_eval(filter_value)
                # Ensure result is a list
                if not isinstance(parsed, list):
                    raise ConfigError(
                        f"Parsed filter must be a list, got {type(parsed).__name__}"
                    )
                return parsed
            except (ValueError, SyntaxError) as e:
                raise ConfigError(
                    f"Failed to parse filter string '{filter_value}': {e}"
                )
        elif isinstance(filter_value, list):
            return filter_value
        else:
            raise ConfigError(
                f"Filter must be string or list, got {type(filter_value).__name__}"
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExtractionFilters":
        """Create ExtractionFilters from dictionary.
        
        No defaults are provided - all filters must be explicitly defined in odoo-instances.json.
        """
        return cls(
            custom_fields=cls._parse_filter(data.get("custom_fields", [])),
            server_actions=cls._parse_filter(data.get("server_actions", [])),
            automations=cls._parse_filter(data.get("automations", [])),
            views=cls._parse_filter(data.get("views", [])),
            reports=cls._parse_filter(data.get("reports", [])),
        )


@dataclass
class Config:
    """Main configuration container."""

    instances: dict[str, InstanceConfig]
    active_instance: str | None = None
    sync: SyncConfig = field(default_factory=SyncConfig)
    extraction_filters: ExtractionFilters = field(
        default_factory=ExtractionFilters
    )

    def get_instance(self, name: str) -> InstanceConfig:
        """Get instance configuration by name.

        Args:
            name: Instance name ('implementation' or 'development')

        Returns:
            InstanceConfig for the named instance

        Raises:
            KeyError: If instance not found
        """
        if name not in self.instances:
            raise KeyError(f"Instance '{name}' not found in configuration")
        return self.instances[name]

    @property
    def implementation(self) -> InstanceConfig:
        """Get implementation instance (read-only, for extraction)."""
        return self.get_instance("implementation")

    @property
    def development(self) -> InstanceConfig:
        """Get development instance (read/write, for sync)."""
        return self.get_instance("development")


class ConfigError(Exception):
    """Configuration error."""

    pass


def load_config(project_root: Path | None = None) -> Config:
    """Load configuration from project's .odoo-sync directory.

    Args:
        project_root: Path to project root (auto-detected if not provided)

    Returns:
        Loaded Config object

    Raises:
        ConfigError: If configuration is missing or invalid
    """
    if project_root is None:
        project_root = find_project_root()
        if project_root is None:
            raise ConfigError(
                "Could not find project root. "
                "Ensure you're in a project with a .odoo-sync directory."
            )

    # Load .env file first
    load_dotenv(project_root)

    config_path = project_root / ".odoo-sync" / "odoo-instances.json"
    if not config_path.exists():
        raise ConfigError(
            f"Configuration file not found: {config_path}\n"
            "Run /odoo-sync:init to create configuration."
        )

    try:
        with open(config_path) as f:
            raw_config = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in configuration file: {e}")

    # Quick check: is this an unconfigured template?
    if "instances" in raw_config:
        impl = raw_config.get("instances", {}).get("implementation", {})
        if not impl.get("url") or not impl.get("database"):
            raise ConfigError(
                f"Configuration file found but not configured.\n"
                f"The file at {config_path} appears to be a template.\n"
                f"Run: ./.odoo-sync/cli.py init"
            )

    # Resolve environment variables
    try:
        resolved = resolve_env_vars_in_dict(raw_config)
    except ValueError as e:
        raise ConfigError(str(e))

    return _parse_config(resolved)


def _parse_config(data: dict[str, Any]) -> Config:
    """Parse configuration dictionary into Config object.

    Args:
        data: Raw configuration dictionary

    Returns:
        Parsed Config object

    Raises:
        ConfigError: If required fields are missing
    """
    if "instances" not in data:
        raise ConfigError("Configuration must contain 'instances' key")

    instances = {}
    for name, instance_data in data["instances"].items():
        _validate_instance(name, instance_data)
        instances[name] = InstanceConfig.from_dict(instance_data.copy())

    sync_data = data.get("sync", {})
    sync = SyncConfig(
        conflict_resolution=sync_data.get(
            "conflict_resolution", "prefer_local"
        ),
        preserve_logged_time=sync_data.get("preserve_logged_time", True),
        auto_move_completed=sync_data.get("auto_move_completed", True),
        require_confirmation=sync_data.get("require_confirmation", False),
    )

    extraction_filters = ExtractionFilters.from_dict(
        data.get("extraction_filters", {})
    )

    return Config(
        instances=instances,
        active_instance=data.get("active_instance"),
        sync=sync,
        extraction_filters=extraction_filters,
    )


def _validate_instance(name: str, data: dict[str, Any]) -> None:
    """Validate instance configuration has required fields.

    Args:
        name: Instance name for error messages
        data: Instance configuration dictionary

    Raises:
        ConfigError: If required fields are missing or empty
    """
    required = ["url", "database", "username", "api_key"]
    missing = []
    empty = []

    for field in required:
        value = data.get(field)
        if value is None:
            missing.append(field)
        elif isinstance(value, str) and not value.strip():
            empty.append(field)

    if missing:
        raise ConfigError(
            f"Instance '{name}' missing required fields: {', '.join(missing)}\n"
            f"Run: ./.odoo-sync/cli.py init"
        )

    if empty:
        raise ConfigError(
            f"Instance '{name}' has empty values for: {', '.join(empty)}\n"
            f"The configuration file exists but hasn't been filled in.\n"
            f"Run: ./.odoo-sync/cli.py init"
        )

    # Validate odoo_source path if provided
    odoo_source = data.get("odoo_source")
    if odoo_source:
        odoo_source_path = Path(odoo_source).expanduser()
        if not odoo_source_path.exists():
            raise ConfigError(
                f"Instance '{name}' has invalid odoo_source path: {odoo_source}\n"
                f"The path does not exist. Please verify the path is correct."
            )


def save_config(config_data: dict[str, Any], project_root: Path) -> Path:
    """Save configuration to project's .odoo-sync directory.

    Args:
        config_data: Configuration dictionary to save
        project_root: Path to project root

    Returns:
        Path to saved configuration file
    """
    sync_dir = project_root / ".odoo-sync"
    sync_dir.mkdir(parents=True, exist_ok=True)

    config_path = sync_dir / "odoo-instances.json"
    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=2)

    return config_path



