"""Odoo component extractors for Studio customizations."""

from .automations import AutomationsExtractor
from .base import BaseExtractor, ExtractionResult
from .fields import FieldsExtractor
from .reports import ReportsExtractor
from .server_actions import ServerActionsExtractor
from .views import ViewsExtractor

__all__ = [
    "BaseExtractor",
    "ExtractionResult",
    "FieldsExtractor",
    "ViewsExtractor",
    "ServerActionsExtractor",
    "AutomationsExtractor",
    "ReportsExtractor",
]
