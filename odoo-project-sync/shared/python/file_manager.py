"""File I/O operations centralized in a FileManager class.

Provides a centralized interface for all file operations including reading,
writing, directory management, and backups. This abstraction improves
testability and maintainability by isolating file system interactions.
"""

import json
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import tomllib
except ImportError:
    # Python < 3.11
    import tomli as tomllib

try:
    from .error_handling import handle_file_operations
    from .exceptions import FileOperationError
except ImportError:
    from error_handling import handle_file_operations
    from exceptions import FileOperationError


class FileManagerError(FileOperationError):
    """Error raised for file operation failures."""
    pass


class FileManager:
    """Centralized file I/O operations for the Odoo Project Sync application.

    This class provides a clean interface for all file system operations,
    making it easier to test components that interact with the file system
    and ensuring consistent error handling across the application.
    """

    def __init__(self, base_path: Optional[Path] = None):
        """Initialize FileManager with optional base path.

        Args:
            base_path: Base directory for relative operations. If None,
                      operations use absolute paths.
        """
        self.base_path = base_path

    def _resolve_path(self, path: Path) -> Path:
        """Resolve path relative to base_path if set.

        Args:
            path: Path to resolve

        Returns:
            Resolved absolute path
        """
        if self.base_path and not path.is_absolute():
            return self.base_path / path
        return path

    def read_json(self, path: Path) -> Dict[str, Any]:
        """Read and parse a JSON file.

        Args:
            path: Path to the JSON file

        Returns:
            Parsed JSON data as dictionary

        Raises:
            FileManagerError: If file cannot be read or parsed
        """
        try:
            resolved_path = self._resolve_path(path)
            with open(resolved_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, IOError) as e:
            raise FileManagerError(f"Failed to read JSON file {path}: {e}") from e

    def read_toml(self, path: Path) -> Dict[str, Any]:
        """Read and parse a TOML file.

        Args:
            path: Path to the TOML file

        Returns:
            Parsed TOML data as dictionary

        Raises:
            FileManagerError: If file cannot be read or parsed
        """
        try:
            resolved_path = self._resolve_path(path)
            with open(resolved_path, 'rb') as f:
                return tomllib.load(f)
        except (FileNotFoundError, Exception) as e:
            raise FileManagerError(f"Failed to read TOML file {path}: {e}") from e

    def write_text(self, path: Path, content: str) -> None:
        """Write text content to a file.

        Args:
            path: Path to write to
            content: Text content to write

        Raises:
            FileManagerError: If file cannot be written
        """
        try:
            resolved_path = self._resolve_path(path)
            self.ensure_directory(resolved_path.parent)
            resolved_path.write_text(content, encoding='utf-8')
        except IOError as e:
            raise FileManagerError(f"Failed to write file {path}: {e}") from e

    def read_text(self, path: Path) -> str:
        """Read text content from a file.

        Args:
            path: Path to read from

        Returns:
            File content as string

        Raises:
            FileManagerError: If file cannot be read
        """
        try:
            resolved_path = self._resolve_path(path)
            return resolved_path.read_text(encoding='utf-8')
        except (FileNotFoundError, IOError) as e:
            raise FileManagerError(f"Failed to read file {path}: {e}") from e

    def ensure_directory(self, path: Path) -> Path:
        """Ensure a directory exists, creating it if necessary.

        Args:
            path: Directory path to ensure exists

        Returns:
            The path that was ensured
        """
        resolved_path = self._resolve_path(path)
        resolved_path.mkdir(parents=True, exist_ok=True)
        return resolved_path

    def exists(self, path: Path) -> bool:
        """Check if a path exists.

        Args:
            path: Path to check

        Returns:
            True if path exists, False otherwise
        """
        resolved_path = self._resolve_path(path)
        return resolved_path.exists()

    def backup_directory(self, source: Path, backup_dir: Path) -> Path:
        """Create a backup of a directory.

        Args:
            source: Source directory to backup
            backup_dir: Directory to store the backup

        Returns:
            Path to the created backup

        Raises:
            FileManagerError: If backup cannot be created
        """
        try:
            resolved_source = self._resolve_path(source)
            resolved_backup_dir = self._resolve_path(backup_dir)
            self.ensure_directory(resolved_backup_dir)

            # Create backup with timestamp
            timestamp = Path(source).name
            backup_path = resolved_backup_dir / f"{timestamp}_backup"

            if resolved_source.is_dir():
                shutil.copytree(resolved_source, backup_path)
            else:
                # If source is a file, copy it to backup directory
                self.ensure_directory(backup_path)
                shutil.copy2(resolved_source, backup_path / resolved_source.name)

            return backup_path
        except (OSError, IOError) as e:
            raise FileManagerError(f"Failed to create backup of {source}: {e}") from e

    def list_directory(self, path: Path) -> list[Path]:
        """List contents of a directory.

        Args:
            path: Directory path to list

        Returns:
            List of paths in the directory

        Raises:
            FileManagerError: If directory cannot be listed
        """
        try:
            resolved_path = self._resolve_path(path)
            if not resolved_path.is_dir():
                raise FileManagerError(f"Path {path} is not a directory")
            return list(resolved_path.iterdir())
        except OSError as e:
            raise FileManagerError(f"Failed to list directory {path}: {e}") from e