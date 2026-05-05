"""Factory for creating extractor instances.

Provides centralized instantiation of extractors with dependency injection.
"""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BaseExtractor
    from .odoo_client import OdooClient

try:
    from .extractors.automations import AutomationsExtractor
    from .extractors.fields import FieldsExtractor
    from .extractors.reports import ReportsExtractor
    from .extractors.server_actions import ServerActionsExtractor
    from .extractors.views import ViewsExtractor
except ImportError:
    from extractors.automations import AutomationsExtractor
    from extractors.fields import FieldsExtractor
    from extractors.reports import ReportsExtractor
    from extractors.server_actions import ServerActionsExtractor
    from extractors.views import ViewsExtractor


class ExtractorFactory:
    """Factory for creating extractor instances."""

    # Registry of available extractors
    EXTRACTOR_CLASSES = {
        "custom_fields": FieldsExtractor,
        "server_actions": ServerActionsExtractor,
        "automations": AutomationsExtractor,
        "views": ViewsExtractor,
        "reports": ReportsExtractor,
    }

    @classmethod
    def create_extractor(
        cls,
        name: str,
        client: "OdooClient",
        output_dir: Path,
        dry_run: bool = True,
    ) -> "BaseExtractor":
        """Create an extractor instance.

        Args:
            name: Extractor name
            client: Odoo client instance
            output_dir: Output directory
            dry_run: Whether to perform dry run

        Returns:
            Extractor instance

        Raises:
            ValueError: If extractor name is not recognized
        """
        if name not in cls.EXTRACTOR_CLASSES:
            available = list(cls.EXTRACTOR_CLASSES.keys())
            raise ValueError(f"Unknown extractor '{name}'. Available: {available}")

        extractor_class = cls.EXTRACTOR_CLASSES[name]
        return extractor_class(client, output_dir, dry_run)

    @classmethod
    def get_available_extractors(cls) -> list[str]:
        """Get list of available extractor names.

        Returns:
            List of extractor names
        """
        return list(cls.EXTRACTOR_CLASSES.keys())

    @classmethod
    def create_all_extractors(
        cls,
        client: "OdooClient",
        output_dir: Path,
        dry_run: bool = True,
    ) -> dict[str, "BaseExtractor"]:
        """Create all available extractors.

        Args:
            client: Odoo client instance
            output_dir: Output directory
            dry_run: Whether to perform dry run

        Returns:
            Dictionary of extractor instances keyed by name
        """
        return {
            name: cls.create_extractor(name, client, output_dir, dry_run)
            for name in cls.EXTRACTOR_CLASSES.keys()
        }