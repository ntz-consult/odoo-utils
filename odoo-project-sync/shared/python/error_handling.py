"""Error handling utilities and decorators for Odoo Project Sync.

Provides standardized error handling patterns and utilities.
"""

import functools
import logging
from typing import Any, Callable

try:
    from .exceptions import (
        AuthenticationError,
        ConnectionError,
        FileOperationError,
        OdooAPIError,
        OdooProjectSyncError,
    )
except ImportError:
    from exceptions import (
        AuthenticationError,
        ConnectionError,
        FileOperationError,
        OdooAPIError,
        OdooProjectSyncError,
    )

logger = logging.getLogger(__name__)


def handle_odoo_api_errors(func: Callable) -> Callable:
    """Decorator to handle Odoo API errors consistently.

    Converts common Odoo API exceptions to custom exceptions
    and logs errors appropriately.

    Args:
        func: Function to decorate

    Returns:
        Decorated function
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AuthenticationError:
            # Re-raise auth errors as-is
            raise
        except ConnectionError:
            # Re-raise connection errors as-is
            raise
        except OdooAPIError:
            # Re-raise API errors as-is
            raise
        except Exception as e:
            # Log unexpected errors and wrap in OdooAPIError
            logger.error(f"Unexpected error in {func.__name__}: {str(e)}")
            raise OdooAPIError(f"API operation failed: {str(e)}") from e

    return wrapper


def handle_file_operations(func: Callable) -> Callable:
    """Decorator to handle file operation errors consistently.

    Converts file system exceptions to FileOperationError
    and logs errors appropriately.

    Args:
        func: Function to decorate

    Returns:
        Decorated function
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except FileOperationError:
            # Re-raise file errors as-is
            raise
        except (OSError, IOError) as e:
            # Convert system errors to FileOperationError
            logger.error(f"File operation failed in {func.__name__}: {str(e)}")
            raise FileOperationError(f"File operation failed: {str(e)}") from e
        except Exception as e:
            # Log unexpected errors and wrap in FileOperationError
            logger.error(f"Unexpected error in {func.__name__}: {str(e)}")
            raise FileOperationError(f"File operation failed: {str(e)}") from e

    return wrapper


def handle_config_errors(func: Callable) -> Callable:
    """Decorator to handle configuration errors consistently.

    Ensures config-related exceptions are properly categorized.

    Args:
        func: Function to decorate

    Returns:
        Decorated function
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except OdooProjectSyncError:
            # Re-raise our custom errors as-is
            raise
        except Exception as e:
            # Log unexpected errors and wrap in ConfigError
            from .exceptions import ConfigError
            logger.error(f"Configuration error in {func.__name__}: {str(e)}")
            raise ConfigError(f"Configuration error: {str(e)}") from e

    return wrapper


class ErrorHandler:
    """Utility class for consistent error handling."""

    @staticmethod
    def log_and_raise(error_class: type[OdooProjectSyncError], message: str, details: Any = None) -> None:
        """Log an error and raise the specified exception.

        Args:
            error_class: Exception class to raise
            message: Error message
            details: Additional error details
        """
        logger.error(message)
        raise error_class(message, details)

    @staticmethod
    def wrap_exception(error_class: type[OdooProjectSyncError], message: str, original_exception: Exception) -> OdooProjectSyncError:
        """Wrap an original exception in a custom exception.

        Args:
            error_class: Exception class to raise
            message: Error message
            original_exception: Original exception to wrap

        Returns:
            Wrapped exception
        """
        logger.error(f"{message}: {str(original_exception)}")
        return error_class(message, original_exception)