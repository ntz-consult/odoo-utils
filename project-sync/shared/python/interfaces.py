"""Abstract interfaces for Odoo Project Sync components.

Defines contracts for pluggable components to enable dependency injection
and improve testability.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from config import InstanceConfig


class ExtractorInterface(ABC):
    """Abstract interface for data extractors."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Extractor name."""
        pass

    @abstractmethod
    def extract(self, base_filters: List[List[Any]] | None = None) -> Dict[str, Any]:
        """Extract data from Odoo.

        Args:
            base_filters: Additional filters to apply

        Returns:
            Extracted data
        """
        pass


class GeneratorInterface(ABC):
    """Abstract interface for code generators."""

    @abstractmethod
    def generate(self, data: Dict[str, Any], **kwargs) -> str:
        """Generate code from data.

        Args:
            data: Input data
            **kwargs: Additional options

        Returns:
            Generated code
        """
        pass


class OdooClientInterface(ABC):
    """Abstract interface for Odoo client operations."""

    @abstractmethod
    def test_connection(self) -> Dict[str, Any]:
        """Test connection to Odoo instance.

        Returns:
            Connection test results
        """
        pass

    @abstractmethod
    def authenticate(self) -> int:
        """Authenticate and get user ID.

        Returns:
            User ID
        """
        pass

    @abstractmethod
    def search_read(self, model: str, domain: List[List[Any]] | None = None, fields: List[str] | None = None, **kwargs) -> List[Dict[str, Any]]:
        """Search and read records.

        Args:
            model: Model name
            domain: Search domain
            fields: Fields to retrieve
            **kwargs: Additional options

        Returns:
            List of records
        """
        pass

    @abstractmethod
    def create(self, model: str, vals: Dict[str, Any]) -> int:
        """Create a new record.

        Args:
            model: Model name
            vals: Field values

        Returns:
            Created record ID
        """
        pass

    @abstractmethod
    def write(self, model: str, ids: List[int], vals: Dict[str, Any]) -> bool:
        """Update records.

        Args:
            model: Model name
            ids: Record IDs
            vals: Field values

        Returns:
            Success status
        """
        pass

    @abstractmethod
    def unlink(self, model: str, ids: List[int]) -> bool:
        """Delete records.

        Args:
            model: Model name
            ids: Record IDs

        Returns:
            Success status
        """
        pass


class ConfigManagerInterface(ABC):
    """Abstract interface for configuration management."""

    @property
    @abstractmethod
    def config(self) -> Any:
        """Get the loaded configuration."""
        pass

    @property
    @abstractmethod
    def implementation(self) -> InstanceConfig:
        """Get implementation instance config."""
        pass

    @property
    @abstractmethod
    def development(self) -> InstanceConfig:
        """Get development instance config."""
        pass

    @abstractmethod
    def validate(self) -> List[str]:
        """Validate configuration.

        Returns:
            List of validation errors
        """
        pass

    @abstractmethod
    def is_valid(self) -> bool:
        """Check if configuration is valid.

        Returns:
            True if valid
        """
        pass


class TimeEstimationStrategyInterface(ABC):
    """Abstract interface for time estimation strategies."""

    @abstractmethod
    def create_user_stories(self, feature: Any, time_estimator: Any) -> List[Any]:
        """Create user stories for a feature.

        Args:
            feature: Feature to create stories for
            time_estimator: TimeEstimator instance

        Returns:
            List of UserStory objects
        """
        pass