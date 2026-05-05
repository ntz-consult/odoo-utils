"""Configuration manager for centralized config access and validation."""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import Config, InstanceConfig, SyncConfig

try:
    from config import ConfigError, load_config
    from interfaces import ConfigManagerInterface
    from data_validation import (
        validate_instance_config,
        validate_sync_config,
        validate_project_structure,
        raise_if_errors
    )
except ImportError:
    from config import ConfigError, load_config
    from interfaces import ConfigManagerInterface
    from data_validation import (
        validate_instance_config,
        validate_sync_config,
        validate_project_structure,
        raise_if_errors
    )


class ConfigManager(ConfigManagerInterface):
    """Centralized configuration access and validation."""

    def __init__(self, project_root: Path | None = None):
        """Initialize config manager.

        Args:
            project_root: Project root directory (auto-detected if None)
        """
        self._config: Config | None = None
        self._project_root = project_root

    @property
    def config(self) -> "Config":
        """Get the loaded configuration.

        Returns:
            Loaded Config object

        Raises:
            ConfigError: If config not loaded or invalid
        """
        if self._config is None:
            self._config = load_config(self._project_root)
        return self._config

    def reload(self) -> None:
        """Reload configuration from disk."""
        self._config = None

    def get_instance(self, name: str) -> "InstanceConfig":
        """Get instance configuration by name.

        Args:
            name: Instance name

        Returns:
            InstanceConfig for the named instance
        """
        return self.config.get_instance(name)

    @property
    def implementation(self) -> "InstanceConfig":
        """Get implementation instance configuration."""
        return self.config.implementation

    @property
    def development(self) -> "InstanceConfig":
        """Get development instance configuration."""
        return self.config.development

    @property
    def sync_config(self) -> "SyncConfig":
        """Get sync configuration."""
        return self.config.sync

    @property
    def extraction_filters(self) -> "ExtractionFilters":
        """Get extraction filters configuration."""
        return self.config.extraction_filters

    def validate(self) -> list[str]:
        """Validate the current configuration.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Validate project structure
        if self._project_root:
            errors.extend(validate_project_structure(self._project_root))

        # Check required instances
        instances = self.config.instances
        if "implementation" not in instances:
            errors.append("Missing 'implementation' instance configuration")
        if "development" not in instances:
            errors.append("Missing 'development' instance configuration")

        # Validate implementation instance
        if "implementation" in instances:
            errors.extend(validate_instance_config(instances["implementation"], "implementation"))

        # Validate development instance
        if "development" in instances:
            errors.extend(validate_instance_config(instances["development"], "development"))

        # Validate sync config
        errors.extend(validate_sync_config(dict(self.config.sync)))

        return errors

    def validate_and_raise(self) -> None:
        """Validate configuration and raise exception if invalid.

        Raises:
            ValidationError: If configuration is invalid
        """
        errors = self.validate()
        raise_if_errors(errors, "Configuration validation")

    def is_valid(self) -> bool:
        """Check if configuration is valid.

        Returns:
            True if configuration is valid
        """
        return len(self.validate()) == 0