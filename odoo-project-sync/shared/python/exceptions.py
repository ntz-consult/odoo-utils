"""Exception hierarchy for Odoo Project Sync.

Provides comprehensive error handling with categorized exceptions.
"""

from typing import Any


class OdooProjectSyncError(Exception):
    """Base exception for all Odoo Project Sync errors."""

    def __init__(self, message: str, details: Any = None):
        """Initialize exception.

        Args:
            message: Error message
            details: Additional error details
        """
        super().__init__(message)
        self.details = details


class ConfigError(OdooProjectSyncError):
    """Configuration-related errors."""
    pass


class ValidationError(OdooProjectSyncError):
    """Data validation errors."""
    pass


class ConnectionError(OdooProjectSyncError):
    """Network and connection errors."""
    pass


class AuthenticationError(ConnectionError):
    """Authentication and authorization errors."""
    pass


class OdooAPIError(ConnectionError):
    """Odoo API interaction errors."""
    pass


class SyncError(OdooProjectSyncError):
    """Synchronization operation errors."""
    pass


class ConflictError(SyncError):
    """Sync conflict resolution errors."""
    pass


class FileOperationError(OdooProjectSyncError):
    """File system operation errors."""
    pass


class ParsingError(OdooProjectSyncError):
    """Data parsing and processing errors."""
    pass


class GenerationError(OdooProjectSyncError):
    """Code and file generation errors."""
    pass


class ExtractionError(OdooProjectSyncError):
    """Data extraction errors."""
    pass


class TaskError(OdooProjectSyncError):
    """Task management errors."""
    pass


class KnowledgeError(OdooProjectSyncError):
    """Knowledge base management errors."""
    pass


class CLIError(OdooProjectSyncError):
    """Command-line interface errors."""
    pass