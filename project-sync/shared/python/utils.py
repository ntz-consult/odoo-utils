"""Shared utilities for Odoo Project Sync."""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING
from urllib.parse import urljoin

import requests

if TYPE_CHECKING:
    from .exceptions import OdooAPIError
    from .odoo_client import OdooClient

try:
    from .exceptions import OdooAPIError
    from .odoo_client import OdooClient
except ImportError:
    OdooAPIError = Exception  # Fallback
    OdooClient = None  # Fallback


def resolve_env_vars(value: str) -> str:
    """Resolve ${ENV_VAR} syntax in a string.

    Args:
        value: String potentially containing ${VAR} patterns

    Returns:
        String with environment variables resolved

    Raises:
        ValueError: If referenced env var is not set
    """
    pattern = r"\$\{([^}]+)\}"

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name)
        if env_value is None:
            raise ValueError(f"Environment variable '{var_name}' is not set")
        return env_value

    return re.sub(pattern, replacer, value)


def resolve_env_vars_in_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively resolve ${ENV_VAR} syntax in a dictionary.

    Args:
        data: Dictionary potentially containing ${VAR} patterns in string values

    Returns:
        New dictionary with environment variables resolved
    """
    result = {}
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = resolve_env_vars(value)
        elif isinstance(value, dict):
            result[key] = resolve_env_vars_in_dict(value)
        elif isinstance(value, list):
            result[key] = [
                (
                    resolve_env_vars_in_dict(item)
                    if isinstance(item, dict)
                    else (
                        resolve_env_vars(item)
                        if isinstance(item, str)
                        else item
                    )
                )
                for item in value
            ]
        else:
            result[key] = value
    return result


def find_project_root(start_path: Path | None = None) -> Path | None:
    """Find the project root by looking for .odoo-sync directory.

    Args:
        start_path: Starting path to search from (defaults to cwd)

    Returns:
        Path to project root, or None if not found
    """
    if start_path is None:
        start_path = Path.cwd()

    current = start_path.resolve()

    while current != current.parent:
        if (current / ".odoo-sync").is_dir():
            return current
        current = current.parent

    # Check root as well
    if (current / ".odoo-sync").is_dir():
        return current

    return None


def ensure_directory(path: Path) -> Path:
    """Ensure a directory exists, creating it if necessary.

    Args:
        path: Directory path to ensure exists

    Returns:
        The path that was ensured
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_dotenv(project_root: Path) -> None:
    """Load .env file from .odoo-sync directory into environment.

    Args:
        project_root: Path to project root containing .odoo-sync directory
    """
    env_file = project_root / ".odoo-sync" / ".env"
    try:
        from .file_manager import FileManager
    except ImportError:
        from file_manager import FileManager
    
    file_manager = FileManager(project_root)
    if not file_manager.exists(env_file):
        return

    content = file_manager.read_text(env_file)
    for line in content.splitlines():
        line = line.strip()
        # Skip comments and empty lines
        if not line or line.startswith("#"):
            continue
        # Parse KEY=value
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Remove surrounding quotes if present
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            # Only set if not already in environment
            if key not in os.environ:
                os.environ[key] = value


# Odoo API Wrappers

def safe_odoo_call(client: "OdooClient", operation: str, *args, **kwargs) -> Any:
    """Safely execute an Odoo operation with error handling.

    Args:
        client: OdooClient instance
        operation: Operation name (search, read, create, etc.)
        *args: Positional arguments for the operation
        **kwargs: Keyword arguments for the operation

    Returns:
        Result of the operation

    Raises:
        OdooAPIError: If the operation fails
    """
    try:
        from .exceptions import OdooAPIError
    except ImportError:
        from exceptions import OdooAPIError
    
    try:
        method = getattr(client, operation)
        return method(*args, **kwargs)
    except Exception as e:
        raise OdooAPIError(f"Odoo {operation} failed: {e}")


def batch_read_records(
    client: "OdooClient",
    model: str,
    ids: List[int],
    fields: Optional[List[str]] = None,
    batch_size: int = 100
) -> List[Dict[str, Any]]:
    """Read records in batches to handle large datasets efficiently.

    Args:
        client: OdooClient instance
        model: Model name
        ids: List of record IDs
        fields: Fields to read (default: all)
        batch_size: Number of records per batch

    Returns:
        List of record dictionaries
    """
    all_records = []
    for i in range(0, len(ids), batch_size):
        batch_ids = ids[i:i + batch_size]
        records = safe_odoo_call(client, 'read', model, batch_ids, fields)
        all_records.extend(records)
    return all_records


def get_related_records(
    client: "OdooClient",
    model: str,
    record_ids: List[int],
    relation_field: str,
    related_fields: Optional[List[str]] = None
) -> Dict[int, List[Dict[str, Any]]]:
    """Get related records for multiple parent records.

    Args:
        client: OdooClient instance
        model: Parent model name
        record_ids: Parent record IDs
        relation_field: Name of the relation field (many2one, one2many, many2many)
        related_fields: Fields to read from related records

    Returns:
        Dictionary mapping parent ID to list of related records
    """
    # Read the relation field from parent records
    parent_records = safe_odoo_call(client, 'read', model, record_ids, [relation_field])
    
    related_map = {}
    for parent in parent_records:
        parent_id = parent['id']
        related_ids = parent.get(relation_field, [])
        
        if isinstance(related_ids, list) and related_ids:
            # Handle different relation types
            if isinstance(related_ids[0], list):
                # many2many/one2many: [[id, name], ...]
                related_ids = [item[0] for item in related_ids if isinstance(item, list)]
            elif isinstance(related_ids[0], int):
                # many2one: [id]
                related_ids = related_ids
            
            if related_ids:
                related_records = batch_read_records(client, relation_field.split('.')[-1] if '.' in relation_field else 'ir.model', related_ids, related_fields)
                related_map[parent_id] = related_records
            else:
                related_map[parent_id] = []
        else:
            related_map[parent_id] = []
    
    return related_map


# Data Transformation Helpers

def transform_record_fields(
    record: Dict[str, Any],
    field_mappings: Dict[str, str],
    transformations: Optional[Dict[str, callable]] = None
) -> Dict[str, Any]:
    """Transform record fields using mappings and optional transformations.

    Args:
        record: Original record dictionary
        field_mappings: Dictionary mapping old field names to new field names
        transformations: Optional dictionary of field_name -> transformation function

    Returns:
        Transformed record dictionary
    """
    transformed = record.copy()
    
    # Apply field mappings
    for old_field, new_field in field_mappings.items():
        if old_field in transformed:
            transformed[new_field] = transformed.pop(old_field)
    
    # Apply transformations
    if transformations:
        for field, transform_func in transformations.items():
            if field in transformed:
                transformed[field] = transform_func(transformed[field])
    
    return transformed


def extract_nested_value(data: Dict[str, Any], path: str, default: Any = None) -> Any:
    """Extract value from nested dictionary using dot notation.

    Args:
        data: Dictionary to extract from
        path: Dot-separated path (e.g., 'user.name')
        default: Default value if path not found

    Returns:
        Extracted value or default
    """
    keys = path.split('.')
    current = data
    
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    
    return current


def merge_dicts(*dicts: Dict[str, Any], deep: bool = False) -> Dict[str, Any]:
    """Merge multiple dictionaries.

    Args:
        *dicts: Dictionaries to merge
        deep: Whether to perform deep merge

    Returns:
        Merged dictionary
    """
    if not deep:
        result = {}
        for d in dicts:
            result.update(d)
        return result
    
    # Deep merge implementation
    result = {}
    for d in dicts:
        for key, value in d.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = merge_dicts(result[key], value, deep=True)
            else:
                result[key] = value
    return result


# Data Validation Functions

def validate_required_fields(data: Dict[str, Any], required_fields: List[str]) -> List[str]:
    """Validate that required fields are present and not empty.

    Args:
        data: Data dictionary to validate
        required_fields: List of required field names

    Returns:
        List of validation error messages
    """
    errors = []
    for field in required_fields:
        value = data.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"Required field '{field}' is missing or empty")
    return errors


def validate_field_types(
    data: Dict[str, Any],
    type_specs: Dict[str, type],
    allow_none: bool = True
) -> List[str]:
    """Validate field types in a dictionary.

    Args:
        data: Data dictionary to validate
        type_specs: Dictionary mapping field names to expected types
        allow_none: Whether None values are allowed

    Returns:
        List of validation error messages
    """
    errors = []
    for field, expected_type in type_specs.items():
        value = data.get(field)
        if value is None and allow_none:
            continue
        if not isinstance(value, expected_type):
            errors.append(f"Field '{field}' must be of type {expected_type.__name__}, got {type(value).__name__}")
    return errors


def validate_enum_values(
    data: Dict[str, Any],
    enum_specs: Dict[str, List[Any]]
) -> List[str]:
    """Validate that field values are within allowed enumerations.

    Args:
        data: Data dictionary to validate
        enum_specs: Dictionary mapping field names to lists of allowed values

    Returns:
        List of validation error messages
    """
    errors = []
    for field, allowed_values in enum_specs.items():
        value = data.get(field)
        if value is not None and value not in allowed_values:
            errors.append(f"Field '{field}' must be one of {allowed_values}, got '{value}'")
    return errors


def sanitize_string(value: str, max_length: Optional[int] = None) -> str:
    """Sanitize a string value.

    Args:
        value: String to sanitize
        max_length: Maximum allowed length

    Returns:
        Sanitized string
    """
    if not isinstance(value, str):
        value = str(value)
    
    # Remove leading/trailing whitespace
    value = value.strip()
    
    # Apply length limit
    if max_length and len(value) > max_length:
        value = value[:max_length]
    
    return value


def normalize_model_name(model: str) -> str:
    """Normalize Odoo model name.

    Args:
        model: Model name to normalize

    Returns:
        Normalized model name
    """
    return model.strip().lower()


def generate_xml_id(base_name: str, prefix: str = "") -> str:
    """Generate a valid XML ID from a base name.

    Args:
        base_name: Base name for the XML ID
        prefix: Optional prefix

    Returns:
        Valid XML ID string
    """
    # Sanitize the base name
    xml_id = re.sub(r'[^\w\-_\.]', '_', base_name)
    xml_id = xml_id.strip('_')
    xml_id = xml_id.lower()
    
    if prefix:
        xml_id = f"{prefix}_{xml_id}"
    
    # Ensure it starts with a letter or underscore
    if xml_id and not xml_id[0].isalpha() and xml_id[0] != '_':
        xml_id = f"_{xml_id}"
    
    return xml_id or "unnamed"


def create_timestamped_backup(file_path: Path, keep: int = 5) -> Optional[Path]:
    """Create a timestamped backup of a file and cleanup old backups.
    
    Args:
        file_path: Path to file to backup
        keep: Number of most recent backups to keep (default: 5)
        
    Returns:
        Path to backup file, or None if file doesn't exist
    """
    if not file_path.exists():
        return None
    
    from datetime import datetime
    import shutil
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = file_path.stem
    suffix = file_path.suffix
    backup_path = file_path.parent / f"{stem}_{timestamp}{suffix}"
    
    shutil.copy2(file_path, backup_path)
    
    # Clean up old backups (keep N most recent)
    pattern = f"{stem}_*{suffix}"
    cleanup_old_backups(file_path.parent, pattern, keep=keep)
    
    return backup_path


def cleanup_old_backups(directory: Path, pattern: str, keep: int = 5) -> None:
    """Remove old backup files, keeping only the most recent N.
    
    Args:
        directory: Directory containing backups
        pattern: Glob pattern to match (e.g., "TODO_*.md")
        keep: Number of most recent backups to keep
    """
    backups = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    for old_backup in backups[keep:]:
        old_backup.unlink()


def update_component_source_location(
    comp_ref: str,
    filepath: Path,
    project_root: Path,
    map_file: Optional[Path] = None,
    warnings: Optional[List[str]] = None
) -> bool:
    """Update source_location in feature_user_story_map.toml for a component reference.
    
    This is a shared utility used by module_generator and other tools to update the
    source_location field after generating a file for a component.
    
    Reads the TOML, finds ALL components matching the ref (case-insensitive), 
    updates their source_location, and writes back.
    
    Args:
        comp_ref: Component reference string (e.g., "view.studio_customization.name")
        filepath: Full path to the generated file
        project_root: Project root directory
        map_file: Optional path to feature_user_story_map.toml (defaults to studio/feature_user_story_map.toml)
        warnings: Optional list to append warning messages to
        
    Returns:
        True if any component was updated, False otherwise
    """
    import tomllib
    
    if map_file is None:
        map_file = project_root / "studio" / "feature_user_story_map.toml"
    
    if not map_file.exists():
        return False
        
    try:
        # Read current TOML
        map_content = map_file.read_text(encoding="utf-8")
        map_data = tomllib.loads(map_content)
        
        # Calculate relative path from project root (includes studio/ prefix)
        relative_path = filepath.relative_to(project_root)
        source_location = str(relative_path)
        
        # Find and update ALL matching components in map (no early breaks)
        updated = False
        for feature_name, feature_def in map_data.get("features", {}).items():
            user_stories = feature_def.get("user_stories", {})
            # Handle both dict format (new) and list format (legacy)
            if isinstance(user_stories, dict):
                for story_name, story_data in user_stories.items():
                    components = story_data.get("components", [])
                    for i, comp in enumerate(components):
                        # Handle both string and dict formats
                        if isinstance(comp, dict):
                            if comp.get("ref") == comp_ref or comp.get("ref", "").lower() == comp_ref.lower():
                                comp["source_location"] = source_location
                                updated = True
                        elif isinstance(comp, str):
                            if comp == comp_ref or comp.lower() == comp_ref.lower():
                                # Convert to dict format
                                components[i] = {"ref": comp, "source_location": source_location}
                                updated = True
            else:
                # Legacy list format
                for story in user_stories:
                    components = story.get("components", [])
                    for i, comp in enumerate(components):
                        if isinstance(comp, dict):
                            if comp.get("ref") == comp_ref or comp.get("ref", "").lower() == comp_ref.lower():
                                comp["source_location"] = source_location
                                updated = True
                        elif isinstance(comp, str):
                            if comp == comp_ref or comp.lower() == comp_ref.lower():
                                components[i] = {"ref": comp, "source_location": source_location}
                                updated = True
        
        if updated:
            # Write back TOML - import the generator to use its write method
            from feature_user_story_map_generator import FeatureUserStoryMapGenerator
            generator = FeatureUserStoryMapGenerator(project_root, verbose=False)
            generator._write_toml(map_data)
            return True
            
        return False
            
    except Exception as e:
        # Don't fail if TOML update fails - just log warning
        if warnings is not None:
            warnings.append(f"Failed to update source_location for {comp_ref}: {e}")
        return False
