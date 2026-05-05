"""Data validation utilities for Odoo Project Sync.

Provides centralized validation functions for config and data structures
to ensure consistency and reduce duplication.
"""

from typing import Any, Dict, List, Optional, Union
from pathlib import Path

from exceptions import ValidationError


# Config Validation Functions

def validate_instance_config(instance_config: Dict[str, Any], name: str) -> List[str]:
    """Validate an Odoo instance configuration.

    Args:
        instance_config: Instance configuration dictionary
        name: Instance name for error messages

    Returns:
        List of validation error messages
    """
    errors = []

    required_fields = ['url', 'database', 'username', 'api_key']
    for field in required_fields:
        if not instance_config.get(field):
            errors.append(f"Instance '{name}' missing required field: {field}")

    # Validate URL format
    url = instance_config.get('url', '')
    if url and not (url.startswith('http://') or url.startswith('https://')):
        errors.append(f"Instance '{name}' URL must start with http:// or https://")

    # Validate read_only is boolean
    read_only = instance_config.get('read_only')
    if read_only is not None and not isinstance(read_only, bool):
        errors.append(f"Instance '{name}' read_only must be a boolean")

    return errors


def validate_sync_config(sync_config: Dict[str, Any]) -> List[str]:
    """Validate sync configuration.

    Args:
        sync_config: Sync configuration dictionary

    Returns:
        List of validation error messages
    """
    errors = []

    # Validate conflict_resolution
    conflict_resolution = sync_config.get('conflict_resolution', 'manual')
    valid_resolutions = ['manual', 'prefer_local', 'prefer_remote', 'prefer_newer']
    if conflict_resolution not in valid_resolutions:
        errors.append(f"Invalid conflict_resolution: {conflict_resolution}. Must be one of {valid_resolutions}")

    # Validate extraction_filters
    extraction_filters = sync_config.get('extraction_filters', {})
    if not isinstance(extraction_filters, dict):
        errors.append("extraction_filters must be a dictionary")
    else:
        # Validate filter structure
        for key, value in extraction_filters.items():
            if not isinstance(value, list):
                errors.append(f"extraction_filters['{key}'] must be a list")
            elif value and not all(isinstance(item, list) and len(item) >= 2 for item in value):
                errors.append(f"extraction_filters['{key}'] must contain lists with at least 2 elements")

    return errors


def validate_extraction_filters(filters: Dict[str, Any]) -> List[str]:
    """Validate extraction filters configuration.

    Args:
        filters: Extraction filters dictionary

    Returns:
        List of validation error messages
    """
    errors = []

    if not isinstance(filters, dict):
        errors.append("Extraction filters must be a dictionary")
        return errors

    # Each filter should be a list of domain conditions
    for filter_name, filter_conditions in filters.items():
        if not isinstance(filter_conditions, list):
            errors.append(f"Filter '{filter_name}' must be a list")
            continue

        for i, condition in enumerate(filter_conditions):
            if not isinstance(condition, list) or len(condition) < 2:
                errors.append(f"Filter '{filter_name}' condition {i} must be a list with at least 2 elements")
                continue

            # Basic domain validation - first element should be field name
            if not isinstance(condition[0], str):
                errors.append(f"Filter '{filter_name}' condition {i} first element must be a string (field name)")

    return errors


def validate_project_structure(project_root: Path) -> List[str]:
    """Validate project directory structure.

    Args:
        project_root: Project root directory path

    Returns:
        List of validation error messages
    """
    errors = []

    # Check for required directories
    required_dirs = ['.odoo-sync', 'shared']
    for dir_name in required_dirs:
        dir_path = project_root / dir_name
        if not dir_path.exists():
            errors.append(f"Required directory missing: {dir_name}")
        elif not dir_path.is_dir():
            errors.append(f"Path exists but is not a directory: {dir_name}")

    # Check for config files
    config_files = ['odoo-instances.json', 'feature-mapping.json']
    for config_file in config_files:
        config_path = project_root / '.odoo-sync' / config_file
        if not config_path.exists():
            errors.append(f"Required config file missing: .odoo-sync/{config_file}")

    return errors


# Data Validation Functions

def validate_odoo_model_name(model: str) -> List[str]:
    """Validate Odoo model name format.

    Args:
        model: Model name to validate

    Returns:
        List of validation error messages
    """
    errors = []

    if not model or not isinstance(model, str):
        errors.append("Model name must be a non-empty string")
        return errors

    # Basic model name validation
    if not model.replace('.', '').replace('_', '').isalnum():
        errors.append("Model name can only contain letters, numbers, dots, and underscores")

    if model.startswith('.') or model.endswith('.'):
        errors.append("Model name cannot start or end with a dot")

    if '..' in model:
        errors.append("Model name cannot contain consecutive dots")

    return errors


def validate_xml_id(xml_id: str) -> List[str]:
    """Validate XML ID format.

    Args:
        xml_id: XML ID to validate

    Returns:
        List of validation error messages
    """
    errors = []

    if not xml_id or not isinstance(xml_id, str):
        errors.append("XML ID must be a non-empty string")
        return errors

    # XML ID rules: letters, digits, underscores, dots, hyphens
    import re
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_\-\.]*$', xml_id):
        errors.append("XML ID must start with a letter or underscore and contain only letters, digits, underscores, dots, and hyphens")

    if xml_id.startswith('.') or xml_id.endswith('.'):
        errors.append("XML ID cannot start or end with a dot")

    if '..' in xml_id:
        errors.append("XML ID cannot contain consecutive dots")

    return errors


def validate_domain_condition(condition: List[Any]) -> List[str]:
    """Validate a single Odoo domain condition.

    Args:
        condition: Domain condition list

    Returns:
        List of validation error messages
    """
    errors = []

    if not isinstance(condition, list):
        errors.append("Domain condition must be a list")
        return errors

    if len(condition) < 2:
        errors.append("Domain condition must have at least 2 elements")
        return errors

    # First element should be field name
    if not isinstance(condition[0], str):
        errors.append("First element of domain condition must be a string (field name)")

    # Second element should be operator
    valid_operators = ['=', '!=', '<', '>', '<=', '>=', 'in', 'not in', 'like', 'ilike', 'not like', 'not ilike', 'child_of', 'parent_of']
    if len(condition) > 1 and condition[1] not in valid_operators:
        errors.append(f"Invalid operator '{condition[1]}'. Must be one of {valid_operators}")

    return errors


def validate_field_definition(field_def: Dict[str, Any]) -> List[str]:
    """Validate a field definition dictionary.

    Args:
        field_def: Field definition to validate

    Returns:
        List of validation error messages
    """
    errors = []

    required_keys = ['name', 'field_type']
    for key in required_keys:
        if key not in field_def:
            errors.append(f"Field definition missing required key: {key}")

    # Validate field name
    if 'name' in field_def:
        name = field_def['name']
        if not isinstance(name, str) or not name.strip():
            errors.append("Field name must be a non-empty string")

    # Validate field type
    if 'field_def' in field_def:
        field_type = field_def['field_type']
        valid_types = ['char', 'text', 'boolean', 'integer', 'float', 'date', 'datetime',
                      'selection', 'many2one', 'one2many', 'many2many', 'binary', 'html']
        if field_type not in valid_types:
            errors.append(f"Invalid field type '{field_type}'. Must be one of {valid_types}")

    return errors


# General Validation Utilities

def validate_data_structure(data: Any, schema: Dict[str, Any]) -> List[str]:
    """Validate data structure against a simple schema.

    Args:
        data: Data to validate
        schema: Schema definition

    Returns:
        List of validation error messages
    """
    errors = []

    def _validate_recursive(data: Any, schema: Dict[str, Any], path: str = "") -> List[str]:
        local_errors = []

        expected_type = schema.get('type')
        if expected_type and not isinstance(data, expected_type):
            local_errors.append(f"{path} must be of type {expected_type.__name__}")

        if 'required' in schema and schema['required'] and data is None:
            local_errors.append(f"{path} is required")

        if isinstance(data, dict) and 'properties' in schema:
            for prop_name, prop_schema in schema['properties'].items():
                prop_path = f"{path}.{prop_name}" if path else prop_name
                if prop_name in data:
                    local_errors.extend(_validate_recursive(data[prop_name], prop_schema, prop_path))
                elif prop_schema.get('required', False):
                    local_errors.append(f"{prop_path} is required")

        elif isinstance(data, list) and 'items' in schema:
            for i, item in enumerate(data):
                item_path = f"{path}[{i}]"
                local_errors.extend(_validate_recursive(item, schema['items'], item_path))

        return local_errors

    return _validate_recursive(data, schema)


def collect_validation_errors(*validators: callable) -> List[str]:
    """Collect validation errors from multiple validator functions.

    Args:
        *validators: Validator functions that return List[str] of errors

    Returns:
        Combined list of all validation errors
    """
    all_errors = []
    for validator in validators:
        errors = validator()
        if errors:
            all_errors.extend(errors)
    return all_errors


def raise_if_errors(errors: List[str], context: str = "Validation") -> None:
    """Raise ValidationError if there are any errors.

    Args:
        errors: List of error messages
        context: Context for the error message

    Raises:
        ValidationError: If errors is not empty
    """
    if errors:
        error_message = f"{context} failed:\n" + "\n".join(f"  - {error}" for error in errors)
        raise ValidationError(error_message)