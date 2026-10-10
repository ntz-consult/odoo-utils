#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare database records with XML/CSV data files and manage discrepancies interactively.

Usage:
    python sync_xml_data.py --module MODULE_NAME [options]

Options:
    --module MODULE     Module name to check (required)
    --dry-run           Show discrepancies without prompting
    --auto-ignore       Automatically ignore all discrepancies
    --update [N]        Update source files; with N, stop after N successful changes

Examples:
    python sync_xml_data.py --module ibcorr
    python sync_xml_data.py --module ibcorr --dry-run
    python sync_xml_data.py --module ibcorr --update
    python sync_xml_data.py --module ibcorr --update 25
"""

import os
import sys
import argparse
import ast
import configparser
import csv
import re
import textwrap
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from collections import defaultdict
from pathlib import Path
from time import perf_counter
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

# =============================================================================
# Configuration
# =============================================================================


# Read from environment (set by sync.sh which sources common.sh)
ENV_DIR = Path(os.environ.get("ENV_DIR", Path.cwd()))
PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", ENV_DIR))
ODOO_ROOT = Path(os.environ.get("ODOO_ROOT", str(Path.home() / "Odoo/V19")))
ODOO_SOURCE = ODOO_ROOT / "odoo"
CONFIG_FILE = Path(os.environ.get("CONF_FILE", ENV_DIR / "odoo.conf"))

# Add Odoo to path
if str(ODOO_SOURCE) not in sys.path:
    sys.path.insert(0, str(ODOO_SOURCE))

# Suppress Odoo warnings
import logging


def _configure_quiet_odoo_logging():
    """Keep sync output focused on discrepancies, not registry startup noise."""
    logging.getLogger("odoo").setLevel(logging.ERROR)
    logging.getLogger("odoo.schema").setLevel(logging.ERROR)
    logging.getLogger("odoo.tools.config").setLevel(logging.ERROR)
    logging.getLogger("odoo.modules").setLevel(logging.ERROR)
    logging.getLogger("odoo.modules.loading").setLevel(logging.CRITICAL)
    logging.getLogger("py.warnings").setLevel(logging.ERROR)
    logging.getLogger("odoo.addons.attachment_indexation").setLevel(logging.ERROR)


_configure_quiet_odoo_logging()

# Module logger
_logger = logging.getLogger(__name__)

import odoo
from odoo import fields, models, api
from odoo.modules.registry import Registry


# =============================================================================
# Data Classes
# =============================================================================


class DiscrepancyType(Enum):
    """Types of discrepancies between DB and source data."""

    MISSING_IN_DB = "missing_in_db"
    MISSING_IN_XML = "missing_in_xml"
    MISSING_XML_ID = "missing_xml_id"
    AMBIGUOUS_MATCH = "ambiguous_match"
    DUPLICATE_IN_XML = "duplicate_in_xml"
    FIELD_DIFFERENCE = "field_difference"


class ResolutionAction(Enum):
    """User resolution actions."""

    IGNORE = "ignore"
    UPDATE_XML = "update_xml"


@dataclass
class Discrepancy:
    """Represents a single discrepancy."""

    xml_id: str
    model: str
    discrepancy_type: DiscrepancyType
    db_values: Dict[str, Any] = field(default_factory=dict)
    xml_values: Dict[str, Any] = field(default_factory=dict)
    field_differences: Dict[str, Tuple[Any, Any]] = field(default_factory=dict)
    file_path: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def __str__(self):
        if self.discrepancy_type == DiscrepancyType.MISSING_IN_DB:
            source_label = self.details.get("source_label", "Source")
            return f"[{self.model}] {self.xml_id}: {source_label}-only record"
        elif self.discrepancy_type == DiscrepancyType.MISSING_IN_XML:
            return f"[{self.model}] {self.xml_id}: Missing in source data (exists only in DB)"
        elif self.discrepancy_type == DiscrepancyType.MISSING_XML_ID:
            return f"[{self.model}] {self.xml_id}: DB record has no matching XML ID"
        elif self.discrepancy_type == DiscrepancyType.AMBIGUOUS_MATCH:
            return f"[{self.model}] {self.xml_id}: Ambiguous natural-key match"
        elif self.discrepancy_type == DiscrepancyType.DUPLICATE_IN_XML:
            return f"[{self.model}] {self.xml_id}: Duplicate source definition"
        elif self.discrepancy_type == DiscrepancyType.FIELD_DIFFERENCE:
            fields_str = ", ".join(
                f"{k}=(DB:{v[0]}|XML:{v[1]})" for k, v in self.field_differences.items()
            )
            return f"[{self.model}] {self.xml_id}: Field differences: {fields_str}"
        return f"[{self.model}] {self.xml_id}: Unknown"


PTAL_MODEL = "product.template.attribute.line"
PTAL_VALUE_FIELD = "value_ids"
XML_REF_RE = re.compile(r"""ref\(\s*['"]([^'"]+)['"]\s*\)""")
SIMPLE_UNIQUE_RE = re.compile(
    r"^(?:UNIQUE\s+)?(?:INDEX\s+)?(?:USING\s+\w+\s+)?\((?P<fields>[^()]+)\)\s*$",
    re.IGNORECASE,
)
SQL_UNIQUE_RE = re.compile(r"^UNIQUE\s+\((?P<fields>[^()]+)\)\s*$", re.IGNORECASE)
SQL_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
SKIP_FORCE_COMPARE_FIELD_TYPES = {"one2many"}
AUDIT_FIELD_NAMES = {"id", "create_uid", "create_date", "write_uid", "write_date"}


class SyncProfiler:
    """Collect opt-in sync timings and operation counters."""

    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self.timings: Dict[str, float] = defaultdict(float)
        self.counts: Dict[str, int] = defaultdict(int)

    @contextmanager
    def time(self, label: str):
        """Record elapsed time for a named block when profiling is enabled."""
        if not self.enabled:
            yield
            return

        started = perf_counter()
        try:
            yield
        finally:
            self.timings[label] += perf_counter() - started

    def count(self, label: str, amount: int = 1):
        """Increment a named counter when profiling is enabled."""
        if self.enabled:
            self.counts[label] += amount

    def format_report(self) -> str:
        """Return a compact human-readable profile report."""
        if not self.enabled:
            return ""

        lines = ["", "=" * 80, "PROFILE", "=" * 80]
        if self.timings:
            lines.append("Timings:")
            for label, seconds in sorted(
                self.timings.items(),
                key=lambda item: (-item[1], item[0]),
            ):
                lines.append(f"  {label:<32} {seconds:>10.3f}s")
        if self.counts:
            lines.append("Counters:")
            for label, value in sorted(self.counts.items()):
                lines.append(f"  {label:<32} {value:>10}")
        lines.append("=" * 80)
        return "\n".join(lines)


def _slugify_xml_id(value: Any, fallback: str = "record") -> str:
    """Return a deterministic XML-ID-safe slug."""
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", str(value or "").strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or fallback


def _record_key(record) -> Tuple[str, int]:
    """Return a stable identity tuple for a record."""
    return (record._name, record.id)


def _is_empty_record(record) -> bool:
    """Return whether an Odoo record-like value has no real database row."""
    return not record or not getattr(record, "id", None)


def _record_display_name(record) -> str:
    """Return a compact human-readable record name."""
    if not record:
        return "record"
    display_name = getattr(record, "display_name", None) or getattr(record, "name", None)
    if isinstance(display_name, dict):
        display_name = display_name.get("en_US") or next(iter(display_name.values()), "")
    if display_name:
        return str(display_name)
    return f"{record._name},{record.id}"


def _generated_xml_id_name_for_record(record) -> str:
    """Generate a model-aware local XML ID for a DB record."""
    model_name = record._name
    if model_name == "product.attribute":
        return f"product_attribute_{_slugify_xml_id(getattr(record, 'name', None))}"
    if model_name == "product.attribute.value":
        attribute_name = _record_display_name(getattr(record, "attribute_id", None))
        return (
            "product_attribute_value_"
            f"{_slugify_xml_id(attribute_name)}_{_slugify_xml_id(getattr(record, 'name', None))}"
        )
    if model_name == PTAL_MODEL:
        template_name = _record_display_name(getattr(record, "product_tmpl_id", None))
        attribute_name = _record_display_name(getattr(record, "attribute_id", None))
        return f"line_{_slugify_xml_id(template_name)}_{_slugify_xml_id(attribute_name)}"
    if model_name == "attribute.rule":
        return f"rule_{_slugify_xml_id(getattr(record, 'name', None))}"
    if model_name == "ibcorr.import.source.item.code.part":
        source_code = getattr(getattr(record, "source_code_id", None), "source_item_code", None)
        return (
            "source_item_code_part_"
            f"{_slugify_xml_id(source_code)}_"
            f"{_slugify_xml_id(getattr(record, 'sequence', None))}_"
            f"{_slugify_xml_id(getattr(record, 'position', None))}_"
            f"{_slugify_xml_id(getattr(record, 'source_token', None))}"
        )
    if model_name == "ibcorr.import.source.item.code.value":
        source_code = getattr(getattr(record, "source_code_id", None), "source_item_code", None)
        return (
            "source_item_code_value_"
            f"{_slugify_xml_id(source_code)}_"
            f"{_slugify_xml_id(getattr(record, 'sequence', None))}_"
            f"{_slugify_xml_id(getattr(record, 'attribute_value_label', None))}_"
            f"{_slugify_xml_id(getattr(record, 'value_source', None))}"
        )
    return f"{_slugify_xml_id(model_name)}_{_slugify_xml_id(_record_display_name(record))}"


def _coerce_full_xml_id(module: str, xml_id: str) -> str:
    """Return a fully-qualified XML ID."""
    if "." in xml_id:
        return xml_id
    return f"{module}.{xml_id}"


def _env_ref(env, module: str, xml_id: str, raise_if_not_found: bool = True):
    """Resolve an XML ID while supporting simple test fakes."""
    full_xml_id = _coerce_full_xml_id(module, xml_id)
    try:
        return env.ref(full_xml_id, raise_if_not_found=raise_if_not_found)
    except TypeError:
        try:
            return env.ref(full_xml_id)
        except KeyError:
            if raise_if_not_found:
                raise
            return None


def _xml_id_reference_variants(module: str, full_xml_id: str) -> set[str]:
    """Return XML ID forms that may be used inside same-module XML files."""
    short_xml_id = full_xml_id.split(".")[-1]
    return {full_xml_id, short_xml_id, _coerce_full_xml_id(module, short_xml_id)}


def _field_references_xml_id(module: str, field_def: Dict[str, Any], full_xml_id: str) -> bool:
    """Return whether a parsed XML field explicitly references an XML ID."""
    variants = _xml_id_reference_variants(module, full_xml_id)
    ref_value = field_def.get("ref")
    if ref_value and _coerce_full_xml_id(module, ref_value) in variants:
        return True

    for expr_key in ("eval", "search"):
        expression = field_def.get(expr_key)
        if not expression:
            continue
        for ref_match in XML_REF_RE.findall(expression):
            if _coerce_full_xml_id(module, ref_match) in variants:
                return True
    return False


def _discrepancy_type_label(disc_type: DiscrepancyType) -> str:
    """Return user-facing discrepancy labels."""
    if disc_type == DiscrepancyType.MISSING_IN_DB:
        return "Source-Only"
    if disc_type == DiscrepancyType.MISSING_IN_XML:
        return "Missing In Source"
    if disc_type == DiscrepancyType.MISSING_XML_ID:
        return "Missing XML ID"
    if disc_type == DiscrepancyType.AMBIGUOUS_MATCH:
        return "Ambiguous Match"
    if disc_type == DiscrepancyType.DUPLICATE_IN_XML:
        return "Duplicate Source"
    if disc_type == DiscrepancyType.FIELD_DIFFERENCE:
        return "Field Difference"
    return disc_type.value.replace("_", " ").title()


def _read_manifest(project_root: Path, module_name: str) -> Dict[str, Any]:
    """Read an Odoo manifest without importing project code."""
    manifest_path = project_root / module_name / "__manifest__.py"
    if not manifest_path.exists():
        return {}
    try:
        return ast.literal_eval(manifest_path.read_text(encoding="utf-8"))
    except (SyntaxError, ValueError):
        return {}


def _project_module_dependency_closure(project_root: Path, module_name: str) -> set[str]:
    """Return target module plus project-local dependency modules."""
    seen: set[str] = set()
    pending = [module_name]
    while pending:
        current = pending.pop()
        if current in seen or not (project_root / current).is_dir():
            continue
        seen.add(current)
        manifest = _read_manifest(project_root, current)
        for dependency in manifest.get("depends", []):
            if (project_root / dependency).is_dir() and dependency not in seen:
                pending.append(dependency)
    return seen


def _literal_string(node: ast.AST) -> Optional[str]:
    """Return a literal string value from an AST node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _model_name_from_class(assignments: Dict[str, ast.AST]) -> Optional[str]:
    """Return the Odoo model represented by a class body."""
    name = _literal_string(assignments.get("_name")) if "_name" in assignments else None
    if name:
        return name
    inherit_node = assignments.get("_inherit")
    if inherit_node is None:
        return None
    inherit = _literal_string(inherit_node)
    if inherit:
        return inherit
    return None


def _assigned_field_name(stmt: ast.stmt) -> Optional[str]:
    """Return class attribute name when a statement assigns fields.*(...)."""
    target = None
    value = None
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
        target = stmt.targets[0]
        value = stmt.value
    elif isinstance(stmt, ast.AnnAssign):
        target = stmt.target
        value = stmt.value
    if not isinstance(target, ast.Name) or not isinstance(value, ast.Call):
        return None
    func = value.func
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "fields"
    ):
        return target.id
    return None


def _discover_model_fields_in_file(path: Path) -> Dict[str, set[str]]:
    """Discover class-level Odoo field declarations in a Python file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return {}

    model_fields: Dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        assignments: Dict[str, ast.AST] = {}
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                target = stmt.targets[0]
                if isinstance(target, ast.Name) and target.id in ("_name", "_inherit"):
                    assignments[target.id] = stmt.value
        model_name = _model_name_from_class(assignments)
        if not model_name:
            continue
        for stmt in node.body:
            field_name = _assigned_field_name(stmt)
            if field_name:
                model_fields.setdefault(model_name, set()).add(field_name)
    return model_fields


def discover_project_model_fields(project_root: Path, module_name: str) -> Dict[str, set[str]]:
    """Discover model fields declared by a module and project-local dependencies."""
    discovered: Dict[str, set[str]] = {}
    for project_module in sorted(_project_module_dependency_closure(project_root, module_name)):
        module_dir = project_root / project_module
        for path in sorted(module_dir.rglob("*.py")):
            if "tests" in path.parts or "__pycache__" in path.parts:
                continue
            for model_name, field_names in _discover_model_fields_in_file(path).items():
                discovered.setdefault(model_name, set()).update(field_names)
    return discovered


def _discover_project_models_in_file(path: Path) -> Dict[str, str]:
    """Discover Odoo model names keyed by Python class name in a file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return {}

    discovered: Dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        assignments: Dict[str, ast.AST] = {}
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                target = stmt.targets[0]
                if isinstance(target, ast.Name) and target.id in ("_name", "_inherit"):
                    assignments[target.id] = stmt.value
        model_name = _model_name_from_class(assignments)
        if model_name:
            discovered[node.name] = model_name
    return discovered


def discover_project_models(project_root: Path, module_name: str) -> Dict[str, str]:
    """Discover Odoo model names declared by class in a module dependency closure."""
    discovered: Dict[str, str] = {}
    for project_module in sorted(_project_module_dependency_closure(project_root, module_name)):
        module_dir = project_root / project_module
        for path in sorted(module_dir.rglob("*.py")):
            if "tests" in path.parts or "__pycache__" in path.parts:
                continue
            discovered.update(_discover_project_models_in_file(path))
    return discovered


def _camel_to_snake(value: str) -> str:
    """Convert a Python class name to snake_case."""
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return value.lower()


def resolve_model_filter(
    requested_model: str,
    xml_models: set[str],
    project_models: Dict[str, str],
) -> str:
    """Resolve a CLI model filter to an Odoo model name.

    The comparator works with Odoo model names, but users often pass Python class
    names such as SourceItemCodePart. Resolve those aliases instead of silently
    producing an empty report.
    """
    known_model_names = set(xml_models) | set(project_models.values())
    if requested_model in known_model_names:
        return requested_model
    if "." in requested_model:
        return requested_model

    alias_map: Dict[str, set[str]] = defaultdict(set)
    for class_name, model_name in project_models.items():
        snake_name = _camel_to_snake(class_name)
        for alias in (class_name, snake_name, snake_name.replace("_", ".")):
            alias_map[alias].add(model_name)
            alias_map[alias.lower()].add(model_name)

    candidates = alias_map.get(requested_model) or alias_map.get(requested_model.lower())
    if not candidates:
        known = ", ".join(sorted(known_model_names)[:20])
        if len(known_model_names) > 20:
            known += ", ..."
        raise ValueError(
            f"Unknown model filter '{requested_model}'. Use an Odoo model name"
            f" or discovered Python class name. Known models: {known}"
        )
    if len(candidates) > 1:
        raise ValueError(
            f"Ambiguous model filter '{requested_model}': "
            + ", ".join(sorted(candidates))
        )
    return next(iter(candidates))


def comparison_model_scope(xml_models: set[str], model_filter: Optional[str] = None) -> set[str]:
    """Return models that should participate in DB/XML comparison."""
    comparison_models = set(xml_models)
    if model_filter:
        comparison_models.add(model_filter)
    return comparison_models


def _is_force_comparable_field(
    field_meta,
    compare_images: bool = False,
) -> bool:
    """Return whether a discovered project field should be compared when omitted."""
    field_type = getattr(field_meta, "type", None)
    if not field_type:
        return False
    if field_type in SKIP_FORCE_COMPARE_FIELD_TYPES:
        return False
    if field_type == "binary" and not compare_images:
        return False
    if getattr(field_meta, "related", None):
        return False
    if getattr(field_meta, "compute", None) and not getattr(field_meta, "inverse", None):
        return False
    if getattr(field_meta, "readonly", False) and not getattr(field_meta, "inverse", None):
        return False
    if getattr(field_meta, "store", True) is False and field_type not in ("many2many",):
        return False
    return True


def _missing_xml_field_def(field_meta, default_value: Any = None) -> Dict[str, Any]:
    """Return an XML field definition representing an omitted field default."""
    field_type = getattr(field_meta, "type", "")
    if field_type == "many2one":
        return {"type": "ref", "value": default_value, "missing": True}
    if field_type == "many2many":
        return {
            "type": "eval",
            "value": default_value if default_value is not None else "[(6, 0, [])]",
            "missing": True,
        }
    if field_type == "one2many":
        return {
            "type": "one2many",
            "value": default_value if default_value is not None else [],
            "missing": True,
        }
    if field_type == "boolean":
        return {"type": "value", "value": bool(default_value), "missing": True}
    return {"type": "value", "value": default_value, "missing": True}


def _get_full_xml_id_for_record(env, record) -> Optional[str]:
    """Return a full XML ID for a record or None if unavailable."""
    xml_id_rec = env["ir.model.data"].search(
        [
            ("model", "=", record._name),
            ("res_id", "=", record.id),
        ],
        limit=1,
    )
    if not xml_id_rec:
        return None
    return f"{xml_id_rec.module}.{xml_id_rec.name}"


def _get_local_xml_id_for_record(env, module: str, record) -> Optional[str]:
    """Return a local XML ID for same-module records, otherwise full XML ID."""
    full_xml_id = _get_full_xml_id_for_record(env, record)
    if not full_xml_id:
        return None
    prefix = f"{module}."
    if full_xml_id.startswith(prefix):
        return full_xml_id[len(prefix) :]
    return full_xml_id


def _safe_eval_xml_expression(env, module: str, expression: str, ref_resolver=None):
    """Evaluate a limited XML expression with ref() support."""
    globals_dict = {"__builtins__": {}}

    def ref(xml_id: str) -> int:
        if ref_resolver:
            resolved_id = ref_resolver(xml_id)
            if resolved_id:
                return resolved_id
        return env.ref(_coerce_full_xml_id(module, xml_id)).id

    locals_dict = {
        "ref": ref,
        "True": True,
        "False": False,
        "None": None,
    }
    return eval(expression, globals_dict, locals_dict)


def _extract_value_ids_from_eval_result(eval_result: Any) -> List[int]:
    """Extract many2many target IDs from a supported XML eval result."""
    if isinstance(eval_result, list):
        for command in eval_result:
            if (
                isinstance(command, (list, tuple))
                and len(command) >= 3
                and command[0] == 6
            ):
                return list(command[2] or [])
    return []


def _sort_records_for_xml(records) -> List[Any]:
    """Return records sorted in a stable, Odoo-like default order."""
    return sorted(
        list(records),
        key=lambda record: (
            getattr(getattr(record, "attribute_id", None), "id", 0),
            getattr(record, "sequence", 0),
            record.id,
        ),
    )


def _resolve_ptal_value_records(env, module: str, field_def: Dict[str, Any], ref_resolver=None):
    """Resolve XML value_ids for product.template.attribute.line to DB records."""
    value_model = env["product.attribute.value"]
    field_type = field_def["type"]
    if field_type == "search":
        domain = _safe_eval_xml_expression(env, module, field_def["value"], ref_resolver)
        return value_model.search(domain)
    if field_type == "eval":
        eval_result = _safe_eval_xml_expression(env, module, field_def["value"], ref_resolver)
        value_ids = _extract_value_ids_from_eval_result(eval_result)
        return value_model.browse(value_ids)
    if field_type == "value" and not str(field_def["value"]).strip():
        return value_model.browse([])
    raise ValueError(
        f"Unsupported value_ids expression type for {PTAL_MODEL}: {field_type}"
    )


def _resolve_many2many_records(env, module: str, field_meta, field_def: Dict[str, Any], ref_resolver=None):
    """Resolve XML many2many data into target records."""
    relation = getattr(field_meta, "comodel_name", None) or getattr(field_meta, "relation", None)
    if not relation:
        raise ValueError("many2many field has no relation model")
    target_model = env[relation]
    field_type = field_def["type"]
    if field_type == "search":
        domain = _safe_eval_xml_expression(env, module, field_def["value"], ref_resolver)
        return target_model.search(domain)
    if field_type == "eval":
        eval_result = _safe_eval_xml_expression(env, module, field_def["value"], ref_resolver)
        value_ids = _extract_value_ids_from_eval_result(eval_result)
        return target_model.browse(value_ids)
    if field_type == "value" and not str(field_def["value"] or "").strip():
        return target_model.browse([])
    raise ValueError(f"Unsupported many2many expression type: {field_type}")


def _resolve_record_xml_ids(env, records) -> Tuple[List[str], List[str]]:
    """Resolve records to XML IDs and track records with no XML ID."""
    xml_ids: List[str] = []
    missing: List[str] = []
    for record in _sort_records_for_xml(records):
        xml_id = _get_full_xml_id_for_record(env, record)
        if xml_id:
            xml_ids.append(xml_id)
        else:
            missing.append(f"{record._name},{record.id}")
    return xml_ids, missing


def _serialize_ptal_value_ids(env, records) -> str:
    """Serialize PTAL value_ids to an explicit XML eval expression."""
    xml_ids, missing = _resolve_record_xml_ids(env, records)
    if missing:
        raise ValueError(
            "missing XML IDs for value_ids: " + ", ".join(missing)
        )
    refs = ", ".join(f"ref('{xml_id}')" for xml_id in xml_ids)
    return f"[(6, 0, [{refs}])]"


def _serialize_many2many_value(env, records) -> str:
    """Serialize a many2many recordset to an explicit XML eval expression."""
    return _serialize_ptal_value_ids(env, records)


def _simple_unique_fields_from_definition(definition: str) -> Tuple[str, ...]:
    """Return simple field names from a unique SQL definition, or an empty tuple."""
    if not definition:
        return ()
    definition = " ".join(str(definition).strip().split())
    if " WHERE " in definition.upper():
        return ()

    match = SQL_UNIQUE_RE.match(definition) or SIMPLE_UNIQUE_RE.match(definition)
    if not match:
        return ()

    fields = []
    for raw_field in match.group("fields").split(","):
        field_name = raw_field.strip().strip('"')
        if not SQL_IDENTIFIER_RE.match(field_name):
            return ()
        fields.append(field_name)
    return tuple(fields)


def _record_field_identity_value(value: Any):
    """Return a hashable value suitable for record identity indexes."""
    if hasattr(value, "id"):
        return value.id or None
    if isinstance(value, (list, tuple, set)):
        return tuple(value)
    return value


# =============================================================================
# Source Data Parser
# =============================================================================


class XMLDataParser:
    """Parse XML/CSV data files and extract record definitions."""

    def __init__(self, data_path: str, module: str):
        self.data_path = Path(data_path)
        self.module = module
        self.records: Dict[str, Dict] = {}
        self.file_mapping: Dict[str, str] = {}
        self.models: set[str] = set()
        self.duplicates: List[Discrepancy] = []
        self._warned_unsupported_csv_columns: set[Tuple[str, str]] = set()

    def parse_all_files(self) -> Dict[str, Dict]:
        """Parse all supported data files in data directory."""
        if not self.data_path.exists():
            raise FileNotFoundError(f"Data path not found: {self.data_path}")

        xml_files = sorted(self.data_path.rglob("*.xml"))
        csv_files = sorted(self.data_path.rglob("*.csv"))

        for xml_file in xml_files:
            try:
                self._parse_xml_file(xml_file)
            except ET.ParseError as e:
                print(f"  Warning: Could not parse {xml_file}: {e}")
                continue

        for csv_file in csv_files:
            self._parse_csv_file(csv_file)

        return self.records

    def _parse_xml_file(self, file_path: Path):
        """Parse a single XML file."""
        tree = ET.parse(file_path)
        root = tree.getroot()

        for record_elem in root.findall(".//record"):
            xml_id = record_elem.get("id")
            model = record_elem.get("model")

            if not xml_id or not model:
                continue

            self.models.add(model)

            # Build full XML ID
            full_xml_id = f"{self.module}.{xml_id}" if "." not in xml_id else xml_id

            # Parse fields
            fields_data = {}
            for field_elem in record_elem.findall("field"):
                field_name = field_elem.get("name")
                ref = field_elem.get("ref")
                eval_expr = field_elem.get("eval")
                search_expr = field_elem.get("search")
                field_info = {
                    "text": field_elem.text or "",
                    "ref": ref,
                    "eval": eval_expr,
                    "search": search_expr,
                    "attributes": dict(field_elem.attrib),
                }

                if search_expr:
                    field_info.update({"type": "search", "value": search_expr})
                elif ref:
                    field_info.update({"type": "ref", "value": ref})
                elif eval_expr:
                    field_info.update({"type": "eval", "value": eval_expr})
                elif field_elem.get("type") == "base64" and field_elem.get("file"):
                    field_info.update(
                        {
                            "type": "base64",
                            "value": field_elem.get("file"),
                        }
                    )
                else:
                    field_info.update(
                        {
                            "type": "value",
                            "value": field_elem.text or "",
                        }
                    )
                fields_data[field_name] = field_info

            relative_file = str(file_path.relative_to(self.data_path))
            if full_xml_id in self.records:
                self.duplicates.append(
                    Discrepancy(
                        xml_id=full_xml_id,
                        model=model,
                        discrepancy_type=DiscrepancyType.DUPLICATE_IN_XML,
                        file_path=relative_file,
                        details={
                            "first_file": self.records[full_xml_id].get("file"),
                            "duplicate_file": relative_file,
                        },
                    )
                )
                continue

            self.records[full_xml_id] = {
                "xml_id": xml_id,
                "model": model,
                "fields": fields_data,
                "file": relative_file,
                "source_type": "xml",
            }
            self.file_mapping[full_xml_id] = str(file_path)

    def _parse_csv_file(self, file_path: Path):
        """Parse a single Odoo CSV data file."""
        model = file_path.stem.split("-")[0]
        relative_file = str(file_path.relative_to(self.data_path))
        try:
            with open(file_path, "r", encoding="utf-8", newline="") as csv_file:
                rows = list(csv.reader(csv_file, quotechar='"', delimiter=","))
        except UnicodeDecodeError as exc:
            print(f"  Warning: Could not decode CSV {file_path}: {exc}")
            return

        if not rows:
            return

        headers = rows[0]
        import_headers = [
            (index, header)
            for index, header in enumerate(headers)
            if "@" not in header
        ]
        id_index = next(
            (index for index, header in import_headers if header == "id"),
            None,
        )
        if id_index is None:
            print(f"  Warning: Skipping CSV without id column: {relative_file}")
            return

        self.models.add(model)
        for row_index, row in enumerate(rows[1:], start=1):
            if not any(row):
                continue
            xml_id = row[id_index].strip() if id_index < len(row) else ""
            if not xml_id:
                print(f"  Warning: Skipping CSV row without id: {relative_file}:{row_index + 1}")
                continue
            full_xml_id = f"{self.module}.{xml_id}" if "." not in xml_id else xml_id
            fields_data = {}
            for column_index, header in import_headers:
                if header == "id":
                    continue
                cell_value = row[column_index] if column_index < len(row) else ""
                field_def = self._csv_field_def(header, cell_value)
                if field_def is None:
                    continue
                if field_def.get("unsupported"):
                    warning_key = (relative_file, header)
                    if warning_key not in self._warned_unsupported_csv_columns:
                        print(f"  Warning: Skipping unsupported CSV column: {relative_file}:{header}")
                        self._warned_unsupported_csv_columns.add(warning_key)
                    continue
                fields_data[field_def["name"]] = field_def

            if full_xml_id in self.records:
                self.duplicates.append(
                    Discrepancy(
                        xml_id=full_xml_id,
                        model=model,
                        discrepancy_type=DiscrepancyType.DUPLICATE_IN_XML,
                        file_path=relative_file,
                        details={
                            "first_file": self.records[full_xml_id].get("file"),
                            "duplicate_file": relative_file,
                            "source_type": "csv",
                        },
                    )
                )
                continue

            self.records[full_xml_id] = {
                "xml_id": xml_id,
                "model": model,
                "fields": fields_data,
                "file": relative_file,
                "source_type": "csv",
                "csv_row_index": row_index,
                "csv_headers": headers,
            }
            self.file_mapping[full_xml_id] = str(file_path)

    def _csv_field_def(self, header: str, value: str) -> Optional[Dict[str, Any]]:
        """Return a parsed field definition for a supported CSV import column."""
        field_path = self._csv_import_field_path(header)
        if not field_path or field_path[0] in (None, ".id"):
            return None
        field_name = field_path[0]
        base = {
            "name": field_name,
            "text": value,
            "attributes": {"csv_header": header},
            "csv_header": header,
            "source_type": "csv",
        }
        if len(field_path) == 1:
            return {
                **base,
                "type": "value",
                "value": value,
            }
        if len(field_path) == 2 and field_path[1] == "id":
            return {
                **base,
                "type": "ref",
                "value": value,
                "ref": value,
            }
        return {
            **base,
            "type": "unsupported",
            "value": value,
            "unsupported": True,
        }

    def _csv_import_field_path(self, header: str) -> List[str]:
        """Return Odoo's import-style field path for a CSV header."""
        fixed_db_id = re.sub(r"([^/])\.id", r"\1/.id", header)
        fixed_external_id = re.sub(r"([^/]):id", r"\1/id", fixed_db_id)
        return fixed_external_id.split("/")


# =============================================================================
# Database Comparator
# =============================================================================


class DatabaseComparator:
    """Compare database records with source data definitions."""

    def __init__(
        self,
        env,
        module: str,
        compare_images: bool = False,
        debug: bool = False,
        project_model_fields: Optional[Dict[str, set[str]]] = None,
        profiler: Optional[SyncProfiler] = None,
    ):
        self.env = env
        self.module = module
        self.compare_images = compare_images
        self.debug = debug
        self.profiler = profiler or SyncProfiler(False)
        self.project_model_fields = (
            project_model_fields
            if project_model_fields is not None
            else discover_project_model_fields(PROJECT_ROOT, module)
        )
        self._model_records_cache: Dict[str, List[Any]] = {}
        self._natural_key_index_cache: Dict[
            Tuple[str, Tuple[str, ...]],
            Dict[Tuple[Any, ...], List[Any]],
        ] = {}
        self._unique_field_sets_cache: Dict[str, List[Tuple[str, ...]]] = {}
        self._full_xml_id_cache: Dict[Tuple[str, int], Optional[str]] = {}
        self._xml_ref_id_cache: Dict[str, Optional[int]] = {}

    def compare(
        self,
        xml_records: Dict[str, Dict],
        xml_models: set[str],
        source_records: Optional[Dict[str, Dict]] = None,
    ) -> List[Discrepancy]:
        """Compare source data records with database records."""
        source_records = source_records or xml_records
        discrepancies = []
        with self.profiler.time("DB XML-ID loading"):
            db_xml_ids = self._get_db_xml_ids()
        skipped_records: List[str] = []
        self._seen_db_records: set[Tuple[str, int]] = set()
        self._extra_discrepancies: List[Discrepancy] = []
        self._reserved_xml_ids: set[str] = set(source_records) | set(db_xml_ids)
        self._db_records_with_xml_ids: set[Tuple[str, int]] = {
            (db_record["model"], db_record["res_id"])
            for db_record in db_xml_ids.values()
        }
        self._db_records_with_any_xml_id = self._get_db_record_keys_with_xml_ids(
            xml_models
        )
        self._generated_xml_ids: Dict[Tuple[str, int], str] = {}
        self._xml_records = source_records
        self._model_source_types: Dict[str, set[str]] = defaultdict(set)
        for source_record in source_records.values():
            self._model_source_types[source_record.get("model")].add(
                source_record.get("source_type", "xml")
            )

        # Check: Records in source data but missing or different in DB
        with self.profiler.time("source-vs-DB comparison"):
            for full_xml_id, xml_record in sorted(xml_records.items()):
                disc = self._compare_single_record(
                    full_xml_id, xml_record, db_xml_ids, skipped_records
                )
                if disc:
                    discrepancies.append(disc)

        discrepancies = self._extra_discrepancies + discrepancies

        # Check: Records in DB but not in source data (only for represented models)
        with self.profiler.time("DB XML-ID source gap check"):
            for full_xml_id, db_record in sorted(db_xml_ids.items()):
                if full_xml_id not in xml_records and db_record["model"] in xml_models:
                    try:
                        record = self.env[db_record["model"]].browse(db_record["res_id"])
                    except KeyError:
                        continue
                    if not record.exists():
                        continue
                    self._seen_db_records.add(_record_key(record))
                    disc = Discrepancy(
                        xml_id=full_xml_id,
                        model=db_record["model"],
                        discrepancy_type=DiscrepancyType.MISSING_IN_XML,
                        db_values={"res_id": db_record["res_id"]},
                        details=self._missing_source_details_for_model(db_record["model"]),
                    )
                    discrepancies.append(disc)

        with self.profiler.time("DB-only record discovery"):
            for record in self._find_untracked_db_records(xml_records, xml_models):
                generated_xml_id = self._generated_full_xml_id_for_record(record)
                discrepancies.append(
                    Discrepancy(
                        xml_id=generated_xml_id,
                        model=record._name,
                        discrepancy_type=DiscrepancyType.MISSING_IN_XML,
                        db_values={"res_id": record.id},
                        details={
                            **self._missing_source_details_for_model(record._name),
                            "generated_xml_id": generated_xml_id,
                            "missing_xml_id": True,
                        },
                    )
                )

        return discrepancies

    def _missing_source_details_for_model(self, model_name: str) -> Dict[str, Any]:
        """Return source metadata for a DB-only discrepancy."""
        source_types = self._model_source_types.get(model_name, set())
        if source_types == {"csv"}:
            return {
                "source_type": "csv",
                "source_label": "CSV",
            }
        return {}

    def _get_db_xml_ids(self) -> Dict[str, Dict]:
        """Get all XML IDs from the database for this module."""
        result = {}
        self.profiler.count("ir.model.data lookups")
        xml_id_records = self.env["ir.model.data"].search(
            [("module", "=", self.module)]
        )

        for xml_id_rec in sorted(
            xml_id_records,
            key=lambda rec: (
                getattr(rec, "module", ""),
                getattr(rec, "name", ""),
                getattr(rec, "id", 0),
            ),
        ):
            full_xml_id = f"{xml_id_rec.module}.{xml_id_rec.name}"
            result[full_xml_id] = {
                "model": xml_id_rec.model,
                "res_id": xml_id_rec.res_id,
                "id": xml_id_rec.id,
            }
        return result

    def _get_db_record_keys_with_xml_ids(self, model_names: set[str]) -> set[Tuple[str, int]]:
        """Return compared DB record keys that already have any XML ID."""
        if not model_names:
            return set()
        self.profiler.count("ir.model.data lookups")
        xml_id_records = self.env["ir.model.data"].search(
            [("model", "in", sorted(model_names))]
        )
        return {
            (xml_id_rec.model, xml_id_rec.res_id)
            for xml_id_rec in xml_id_records
        }

    def _compare_single_record(
        self, full_xml_id: str, xml_record: Dict, db_xml_ids: Dict[str, Dict], skipped: List[str]
    ) -> Optional[Discrepancy]:
        """Compare a single source data record with database."""
        self.profiler.count("XML records compared")
        model_name = xml_record["model"]
        xml_fields = xml_record["fields"]
        source_type = xml_record.get("source_type", "xml")
        source_label = source_type.upper()

        # Check if record exists in DB
        db_xml_rec = db_xml_ids.get(full_xml_id)
        db_record = None
        if not db_xml_rec:
            natural_matches = self._find_natural_key_matches(model_name, xml_fields)
            if len(natural_matches) > 1:
                for match in natural_matches:
                    self._seen_db_records.add(_record_key(match))
                return Discrepancy(
                    xml_id=full_xml_id,
                    model=model_name,
                    discrepancy_type=DiscrepancyType.AMBIGUOUS_MATCH,
                    xml_values={k: v["value"] for k, v in xml_fields.items()},
                    file_path=xml_record.get("file"),
                    details={
                        "source_type": source_type,
                        "source_label": source_label,
                        "matches": [
                            f"{match._name},{match.id} {_record_display_name(match)}"
                            for match in natural_matches
                        ]
                    },
                )
            if not natural_matches:
                return Discrepancy(
                    xml_id=full_xml_id,
                    model=model_name,
                    discrepancy_type=DiscrepancyType.MISSING_IN_DB,
                    xml_values={k: v["value"] for k, v in xml_fields.items()},
                    file_path=xml_record.get("file"),
                    details={
                        "source_type": source_type,
                        "source_label": source_label,
                    },
                )
            db_record = natural_matches[0]
            self._generated_xml_ids[_record_key(db_record)] = full_xml_id
        else:
            # Get database record
            try:
                db_record = self.env[model_name].browse(db_xml_rec["res_id"])
            except KeyError:
                skipped.append(full_xml_id)
                return None

        if not db_record.exists():
            return Discrepancy(
                xml_id=full_xml_id,
                model=model_name,
                discrepancy_type=DiscrepancyType.MISSING_IN_DB,
                xml_values={k: v["value"] for k, v in xml_fields.items()},
                file_path=xml_record.get("file"),
                details={
                    "source_type": source_type,
                    "source_label": source_label,
                },
            )
        self._seen_db_records.add(_record_key(db_record))

        # Compare field values
        field_differences = {}
        comparison_fields = self._get_comparison_fields(model_name, xml_fields)

        if self.debug:
            print(f"[DEBUG] Comparing {full_xml_id} ({model_name})")

        for field_name, field_def in comparison_fields.items():
            field_type = field_def["type"]
            field_meta = self._get_field_meta(model_name, field_name)
            is_forced_field = field_def.get("missing", False)
            if field_def.get("unsupported"):
                continue
            if field_meta and field_meta.type == "one2many":
                continue

            # Skip fields defined with `search` or `eval` — dynamically resolved by Odoo at load time
            if (
                field_type in ("search", "eval")
                and not self._should_compare_dynamic_field(model_name, field_name)
                and not is_forced_field
                and not (
                    field_meta
                    and field_meta.type in ("boolean", "integer", "float", "many2many")
                )
            ):
                continue

            xml_value = field_def["value"]
            db_value = getattr(db_record, field_name, None)

            if model_name == PTAL_MODEL and field_name == PTAL_VALUE_FIELD:
                db_val_normalized, xml_val_normalized = self._compare_ptal_value_ids(
                    field_def, db_value
                )
                if db_val_normalized != xml_val_normalized:
                    field_differences[field_name] = (
                        db_val_normalized,
                        xml_val_normalized,
                )
                continue

            if field_meta and field_meta.type == "many2one":
                db_val_normalized = self._normalize_value(db_value, "ref", field_name)
                if field_type == "ref" and xml_value:
                    resolved_xml_id = self._resolve_xml_ref_id(xml_value)
                    if (
                        db_value
                        and resolved_xml_id
                        and getattr(db_value, "id", None) == resolved_xml_id
                    ):
                        xml_val_normalized = db_val_normalized
                    else:
                        xml_val_normalized = _coerce_full_xml_id(self.module, xml_value)
                elif field_type in ("search", "eval"):
                    resolved_id = self._xml_field_search_value(field_def, field_meta)
                    if (
                        db_value
                        and resolved_id
                        and getattr(db_value, "id", None) == resolved_id
                    ):
                        xml_val_normalized = db_val_normalized
                    else:
                        xml_val_normalized = resolved_id
                else:
                    xml_val_normalized = None
                if db_val_normalized != xml_val_normalized:
                    field_differences[field_name] = (
                        db_val_normalized,
                        xml_val_normalized,
                    )
                continue

            if field_meta and field_meta.type == "many2many":
                if field_def.get("source_type") == "csv" and field_type == "ref":
                    continue
                db_val_normalized, xml_val_normalized = self._compare_many2many_field(
                    field_meta,
                    field_def,
                    db_value,
                )
                if db_val_normalized != xml_val_normalized:
                    field_differences[field_name] = (
                        db_val_normalized,
                        xml_val_normalized,
                    )
                continue

            # Skip image/binary fields unless --img is set
            if not self.compare_images and self._is_image_field(
                field_name, field_type, xml_value, db_value
            ):
                continue

            # Base64 fields with a file path: read file and encode for comparison
            if field_type == "base64":
                if isinstance(xml_value, str) and xml_value:
                    file_path = PROJECT_ROOT / xml_value
                    if file_path.exists():
                        import base64

                        with open(file_path, "rb") as f:
                            xml_value = base64.b64encode(f.read()).decode("ascii")
                db_val_normalized = self._normalize_value(
                    db_value, "base64", field_name
                )
                xml_val_normalized = self._normalize_value(
                    xml_value, "base64", field_name
                )
                if db_val_normalized != xml_val_normalized:
                    field_differences[field_name] = (
                        db_val_normalized,
                        xml_val_normalized,
                    )
                continue

            # Boolean fields: normalize XML string "True"/"False" to actual bool
            # Float/integer fields: cast both sides to numeric to avoid string mismatches
            try:
                if field_meta and field_meta.type == "boolean":
                    xml_bool = (
                        xml_value.lower() == "true"
                        if isinstance(xml_value, str)
                        else bool(xml_value)
                    )
                    db_bool = bool(db_value) if db_value is not None else False
                    if xml_bool != db_bool:
                        field_differences[field_name] = (db_bool, xml_bool)
                    continue
                elif field_meta and field_meta.type == "float":
                    xml_float = float(xml_value) if xml_value is not None else 0.0
                    db_float = float(db_value) if db_value is not None else 0.0
                    if xml_float != db_float:
                        field_differences[field_name] = (db_float, xml_float)
                    continue
                elif field_meta and field_meta.type == "integer":
                    xml_int = int(xml_value) if xml_value is not None else 0
                    db_int = int(db_value) if db_value is not None else 0
                    if self.debug:
                        print(f"  [DEBUG-INT] {full_xml_id}.{field_name}: xml={xml_int!r} db={db_int!r} diff={xml_int != db_int}")
                    if xml_int != db_int:
                        field_differences[field_name] = (db_int, xml_int)
                    continue
            except (ValueError, TypeError, AttributeError):
                pass

            # Pass field_name for special handling (sequence as integer, case-sensitive strings)
            db_val_normalized = self._normalize_value(db_value, field_type, field_name)
            xml_val_normalized = self._normalize_value(
                xml_value, field_type, field_name
            )

            # For ref fields, XML may omit the module prefix; resolve to full XML ID
            if field_type == "ref" and isinstance(xml_val_normalized, str):
                if "." not in xml_val_normalized:
                    xml_val_normalized = f"{self.module}.{xml_val_normalized}"

            if self.debug:
                match = "==" if db_val_normalized == xml_val_normalized else "!!"
                print(
                    f"  [DEBUG] {full_xml_id}.{field_name}: "
                    f"xml_raw={xml_value!r} db_raw={db_value!r} | "
                    f"xml_norm={xml_val_normalized!r} db_norm={db_val_normalized!r} [{match}]"
                )

            # Comparison is CASE-SENSITIVE for strings (Python's != is case-sensitive by default)
            if db_val_normalized != xml_val_normalized:
                field_differences[field_name] = (db_val_normalized, xml_val_normalized)

        if field_differences:
            return Discrepancy(
                xml_id=full_xml_id,
                model=model_name,
                discrepancy_type=DiscrepancyType.FIELD_DIFFERENCE,
                db_values={k: getattr(db_record, k, None) for k in comparison_fields.keys()},
                xml_values={k: v["value"] for k, v in comparison_fields.items()},
                field_differences=field_differences,
                file_path=xml_record.get("file"),
                details={
                    "source_type": source_type,
                    "source_label": source_label,
                    "csv_row_index": xml_record.get("csv_row_index"),
                },
            )

        return None

    def _generated_full_xml_id_for_record(self, record) -> str:
        """Return a generated full XML ID that does not collide in this run."""
        key = _record_key(record)
        if not hasattr(self, "_generated_xml_ids"):
            self._generated_xml_ids = {}
        if key in self._generated_xml_ids:
            return self._generated_xml_ids[key]

        base_name = _generated_xml_id_name_for_record(record)
        candidate = base_name
        suffix = 2
        while _coerce_full_xml_id(self.module, candidate) in self._reserved_xml_ids:
            candidate = f"{base_name}_{suffix}"
            suffix += 1
        full_xml_id = _coerce_full_xml_id(self.module, candidate)
        self._reserved_xml_ids.add(full_xml_id)
        self._generated_xml_ids[key] = full_xml_id
        return full_xml_id

    def _find_natural_key_matches(self, model_name: str, xml_fields: Dict[str, Dict]):
        """Find DB records matching an XML record by natural fields."""
        domains = self._natural_key_domains(model_name, xml_fields)
        for domain in domains:
            try:
                self.profiler.count("natural-key searches")
                matches = self._find_records_by_identity_domain(model_name, domain)
            except (KeyError, ValueError, AttributeError, TypeError):
                continue
            if matches:
                return matches
        return []

    def _natural_key_domain(
        self,
        model_name: str,
        xml_fields: Dict[str, Dict],
    ) -> List[Tuple[str, str, Any]]:
        """Build a conservative natural-key domain from XML fields."""
        domains = self._natural_key_domains(model_name, xml_fields)
        return domains[0] if domains else []

    def _natural_key_domains(
        self,
        model_name: str,
        xml_fields: Dict[str, Dict],
    ) -> List[List[Tuple[str, str, Any]]]:
        """Build conservative natural-key domains from strongest to weakest."""
        unique_domains = self._unique_natural_key_domains(model_name, xml_fields)
        if unique_domains:
            return unique_domains

        fallback_field_sets: List[Tuple[str, ...]] = []
        if model_name == PTAL_MODEL:
            fallback_field_sets.append(("product_tmpl_id", "attribute_id"))
        elif model_name == "product.attribute.value":
            fallback_field_sets.append(("attribute_id", "name"))
        elif model_name == "product.attribute":
            fallback_field_sets.append(("name",))
        elif model_name == "product.template":
            fallback_field_sets.extend((("default_code",), ("name",)))
        elif model_name == "attribute.rule":
            fallback_field_sets.append(
                (
                    "action",
                    "condition_eval",
                    "condition_domain",
                    "target_domain",
                    "sequence",
                )
            )

        fallback_field_sets.append(("name",))
        ref_fields = [
            field_name
            for field_name, field_def in xml_fields.items()
            if self._field_can_resolve_scalar(model_name, field_name, field_def)
        ]
        if ref_fields:
            fallback_field_sets.append(tuple(ref_fields))

        domains = []
        seen = set()
        for field_names in fallback_field_sets:
            domain = self._domain_for_fields(model_name, xml_fields, field_names)
            domain_key = tuple(domain)
            if domain and domain_key not in seen:
                domains.append(domain)
                seen.add(domain_key)
        return domains

    def _unique_natural_key_domains(
        self,
        model_name: str,
        xml_fields: Dict[str, Dict],
    ) -> List[List[Tuple[str, str, Any]]]:
        """Return complete unique-index/constraint domains for an XML record."""
        domains = []
        for field_names in self._unique_field_sets_for_model(model_name):
            domain = self._domain_for_fields(model_name, xml_fields, field_names)
            if domain:
                domains.append(domain)
        return domains

    def _domain_for_fields(
        self,
        model_name: str,
        xml_fields: Dict[str, Dict],
        field_names: Tuple[str, ...],
    ) -> List[Tuple[str, str, Any]]:
        """Build a search domain for XML fields when all values are resolvable."""
        domain = []
        for field_name in field_names:
            field_def = xml_fields.get(field_name)
            if not field_def:
                return []
            field_meta = self._get_field_meta(model_name, field_name)
            value = self._xml_field_search_value(field_def, field_meta)
            if value is None:
                return []
            domain.append((field_name, "=", value))
        return domain

    def _field_can_resolve_scalar(
        self,
        model_name: str,
        field_name: str,
        field_def: Dict[str, Any],
    ) -> bool:
        """Return whether an XML field can contribute to a scalar identity."""
        field_meta = self._get_field_meta(model_name, field_name)
        field_type_name = getattr(field_meta, "type", None)
        if field_type_name in ("one2many", "many2many", "binary"):
            return False

        field_type = field_def.get("type")
        if field_type in ("ref", "value", "eval"):
            return True
        return bool(field_type == "search" and field_type_name == "many2one")

    def _unique_field_sets_for_model(self, model_name: str) -> List[Tuple[str, ...]]:
        """Return simple unique field sets declared on an Odoo model."""
        if model_name in self._unique_field_sets_cache:
            return self._unique_field_sets_cache[model_name]

        try:
            model = self.env[model_name]
        except KeyError:
            self._unique_field_sets_cache[model_name] = []
            return []

        field_sets = []
        for table_object in getattr(model, "_table_objects", {}).values():
            if not getattr(table_object, "unique", False):
                definition = self._table_object_definition(model, table_object)
                if not definition.upper().startswith("UNIQUE "):
                    continue
            else:
                definition = self._table_object_definition(model, table_object)
            fields = _simple_unique_fields_from_definition(definition)
            if fields and self._fields_are_identity_safe(model_name, fields):
                field_sets.append(fields)

        field_sets = sorted(set(field_sets), key=lambda item: (len(item), item))
        self._unique_field_sets_cache[model_name] = field_sets
        return field_sets

    def _table_object_definition(self, model, table_object) -> str:
        """Return a table object SQL definition without requiring a real registry."""
        try:
            return table_object.get_definition(getattr(model, "pool", None))
        except TypeError:
            return table_object.get_definition()
        except AttributeError:
            return str(getattr(table_object, "definition", ""))

    def _fields_are_identity_safe(
        self,
        model_name: str,
        field_names: Tuple[str, ...],
    ) -> bool:
        """Return whether fields can be represented in a deterministic natural key."""
        for field_name in field_names:
            field_meta = self._get_field_meta(model_name, field_name)
            field_type = getattr(field_meta, "type", None)
            if field_type in ("one2many", "many2many", "binary"):
                return False
        return True

    def _find_records_by_identity_domain(
        self,
        model_name: str,
        domain: List[Tuple[str, str, Any]],
    ) -> List[Any]:
        """Find records for equality-only domains using cached per-model indexes."""
        if not domain:
            return []
        if all(operator == "=" for _field, operator, _value in domain):
            field_names = tuple(field_name for field_name, _operator, _value in domain)
            key = tuple(value for _field_name, _operator, value in domain)
            index = self._natural_key_index(model_name, field_names)
            return list(index.get(key, []))
        return list(self.env[model_name].search(domain))

    def _natural_key_index(
        self,
        model_name: str,
        field_names: Tuple[str, ...],
    ) -> Dict[Tuple[Any, ...], List[Any]]:
        """Build or return a cached DB record index for an identity field set."""
        cache_key = (model_name, field_names)
        if cache_key in self._natural_key_index_cache:
            return self._natural_key_index_cache[cache_key]

        index: Dict[Tuple[Any, ...], List[Any]] = defaultdict(list)
        for record in self._all_model_records(model_name):
            key_values = []
            for field_name in field_names:
                key_values.append(
                    _record_field_identity_value(getattr(record, field_name, None))
                )
            if any(value is None for value in key_values):
                continue
            index[tuple(key_values)].append(record)

        self._natural_key_index_cache[cache_key] = index
        return index

    def _all_model_records(self, model_name: str) -> List[Any]:
        """Return all records for a model in deterministic order."""
        if model_name not in self._model_records_cache:
            self.profiler.count("full-model DB scans")
            records = self.env[model_name].search([])
            self._model_records_cache[model_name] = sorted(
                list(records),
                key=lambda record: getattr(record, "id", 0),
            )
        return self._model_records_cache[model_name]

    def _full_xml_id_for_record(self, record) -> Optional[str]:
        """Return a cached full XML ID for a record."""
        record_key = _record_key(record)
        if record_key not in self._full_xml_id_cache:
            self.profiler.count("ir.model.data lookups")
            self._full_xml_id_cache[record_key] = _get_full_xml_id_for_record(
                self.env,
                record,
            )
        return self._full_xml_id_cache[record_key]

    def _resolve_xml_ref_id(self, xml_id: str) -> Optional[int]:
        """Resolve a DB ID from ir.model.data or source XML natural keys."""
        full_xml_id = _coerce_full_xml_id(self.module, xml_id)
        if full_xml_id in self._xml_ref_id_cache:
            return self._xml_ref_id_cache[full_xml_id]

        self.profiler.count("XML ref resolutions")
        ref_record = _env_ref(self.env, self.module, full_xml_id, raise_if_not_found=False)
        if ref_record:
            self._xml_ref_id_cache[full_xml_id] = ref_record.id
            return ref_record.id
        source_record = getattr(self, "_xml_records", {}).get(full_xml_id)
        if source_record:
            matches = self._find_natural_key_matches(
                source_record["model"],
                source_record.get("fields", {}),
            )
            if len(matches) == 1:
                self._xml_ref_id_cache[full_xml_id] = matches[0].id
                return matches[0].id
        self._xml_ref_id_cache[full_xml_id] = None
        return None

    def _xml_field_search_value(self, field_def: Dict[str, Any], field_meta=None):
        """Return a DB search value for a parsed XML field."""
        field_type_name = getattr(field_meta, "type", None)
        if field_type_name in ("one2many", "many2many", "binary"):
            return None

        field_type = field_def.get("type")
        value = field_def.get("value")
        if field_type == "ref":
            try:
                return self._resolve_xml_ref_id(value)
            except (KeyError, ValueError, AttributeError):
                return None
        if field_type == "eval":
            try:
                return _safe_eval_xml_expression(self.env, self.module, value)
            except Exception:
                return None
        if field_type == "search":
            if not field_meta or getattr(field_meta, "type", None) != "many2one":
                return None
            relation = getattr(field_meta, "comodel_name", None) or getattr(
                field_meta, "relation", None
            )
            if not relation:
                return None
            try:
                domain = _safe_eval_xml_expression(
                    self.env,
                    self.module,
                    value,
                    self._resolve_xml_ref_id,
                )
                matches = self._find_records_by_identity_domain(relation, domain)
            except Exception:
                return None
            if len(matches) != 1:
                return None
            return matches[0].id
        if field_type == "value":
            return str(value).strip() if value is not None else None
        return None

    def _find_untracked_db_records(
        self,
        xml_records: Dict[str, Dict],
        xml_models: set[str],
    ) -> List[Any]:
        """Find DB records for XML models that are not represented by XML."""
        untracked = []
        seen_candidate_keys = set(self._seen_db_records)
        for model_name in sorted(xml_models):
            try:
                candidates = self._all_model_records(model_name)
            except (KeyError, ValueError, AttributeError):
                continue
            for record in candidates:
                self.profiler.count("DB records scanned")
                key = _record_key(record)
                if key in seen_candidate_keys:
                    continue
                seen_candidate_keys.add(key)
                if not record.exists():
                    continue
                if key in self._db_records_with_any_xml_id:
                    continue
                self._seen_db_records.add(key)
                untracked.append(record)
        return untracked

    def _get_comparison_fields(self, model_name: str, xml_fields: Dict[str, Dict]) -> Dict[str, Dict]:
        """Return XML fields plus discovered project fields that should be compared."""
        comparison_fields = dict(xml_fields)
        missing_field_meta = {}
        for field_name in sorted(self.project_model_fields.get(model_name, ())):
            if field_name in comparison_fields:
                continue
            field_meta = self._get_field_meta(model_name, field_name)
            if field_meta and _is_force_comparable_field(
                field_meta,
                self.compare_images,
            ):
                missing_field_meta[field_name] = field_meta
        defaults = self._get_missing_field_defaults(model_name, list(missing_field_meta))
        for field_name, field_meta in missing_field_meta.items():
            comparison_fields[field_name] = _missing_xml_field_def(
                field_meta,
                defaults.get(field_name),
            )
        return comparison_fields

    def _get_field_meta(self, model_name: str, field_name: str):
        """Return registry field metadata when available."""
        try:
            return self.env[model_name]._fields.get(field_name)
        except (KeyError, AttributeError):
            return None

    def _get_missing_field_defaults(self, model_name: str, field_names: List[str]) -> Dict[str, Any]:
        """Return Odoo create defaults for omitted fields."""
        if not field_names:
            return {}
        try:
            self.profiler.count("default_get calls")
            return self.env[model_name].default_get(field_names)
        except (KeyError, AttributeError):
            return {}

    def _should_compare_dynamic_field(self, model_name: str, field_name: str) -> bool:
        """Return True when a search/eval field should be materially compared."""
        return model_name == PTAL_MODEL and field_name == PTAL_VALUE_FIELD

    def _compare_ptal_value_ids(
        self, field_def: Dict[str, Any], db_value
    ) -> Tuple[List[str], List[str]]:
        """Compare PTAL value_ids by membership, not by expression text."""
        self.profiler.count("many2many/PTAL comparisons")
        xml_records = _resolve_ptal_value_records(
            self.env,
            self.module,
            field_def,
            self._resolve_xml_ref_id,
        )
        xml_xml_ids, missing_xml = _resolve_record_xml_ids(self.env, xml_records)
        db_xml_ids, missing_db = _resolve_record_xml_ids(self.env, db_value)
        if missing_xml:
            xml_xml_ids.extend(missing_xml)
        if missing_db:
            db_xml_ids.extend(missing_db)
        return sorted(db_xml_ids), sorted(xml_xml_ids)

    def _compare_many2many_field(
        self, field_meta, field_def: Dict[str, Any], db_value
    ) -> Tuple[List[str], List[str]]:
        """Compare a many2many field by XML-ID membership."""
        self.profiler.count("many2many/PTAL comparisons")
        xml_records = _resolve_many2many_records(
            self.env,
            self.module,
            field_meta,
            field_def,
            self._resolve_xml_ref_id,
        )
        xml_xml_ids, missing_xml = _resolve_record_xml_ids(self.env, xml_records)
        db_xml_ids, missing_db = _resolve_record_xml_ids(self.env, db_value or [])
        if missing_xml:
            xml_xml_ids.extend(missing_xml)
        if missing_db:
            db_xml_ids.extend(missing_db)
        return sorted(db_xml_ids), sorted(xml_xml_ids)

    def _xml_plain_value(self, field_def: Optional[Dict[str, Any]]):
        """Return a simple parsed XML field value."""
        if not field_def:
            return ""
        return str(field_def.get("value", "")).strip()

    def _normalize_value(
        self, value: Any, field_type: str, field_name: str = ""
    ) -> Any:
        """Normalize value for comparison.

        Note: String comparisons are CASE-SENSITIVE.
        The 'sequence' field is always treated as an integer.
        """
        if value is None or value is False:
            return None
        if field_type == "ref":
            if isinstance(value, models.Model) or (
                hasattr(value, "_name") and hasattr(value, "id")
            ):
                if not value or not value.id:
                    return None
                xml_id = self._full_xml_id_for_record(value)
                return xml_id or f"{value._name},{value.id}"
            return str(value)
        if field_type == "eval":
            try:
                return eval(value)
            except:
                return value
        if field_type == "base64":
            if isinstance(value, bytes):
                import base64
                return base64.b64encode(value).decode("ascii")
            return str(value) if value else None

        # Special handling for 'sequence' field - always treat as integer
        if field_name == "sequence":
            try:
                return int(value)
            except (ValueError, TypeError):
                return str(value).strip() if value else None

        # For all other fields: preserve case sensitivity (strip whitespace only)
        return str(value).strip() if value else None

    def _is_image_field(
        self, field_name: str, field_type: str, xml_value: Any, db_value: Any
    ) -> bool:
        """Return True if this field is an image or binary field."""
        if field_type == "base64":
            return True
        if any(
            kw in field_name.lower()
            for kw in ("image", "picture", "photo", "binary", "file", "attachment")
        ):
            val = xml_value if xml_value else db_value
            if isinstance(val, (str, bytes)) and len(val) > 200:
                return True
        return False


# =============================================================================
# Report Formatters
# =============================================================================


# ANSI color helpers
_C_RESET = "\033[0m"
_C_BOLD = "\033[1m"
_C_DIM = "\033[2m"
_C_RED = "\033[31m"
_C_GREEN = "\033[32m"
_C_YELLOW = "\033[33m"
_C_BLUE = "\033[34m"
_C_MAGENTA = "\033[35m"
_C_CYAN = "\033[36m"
_C_WHITE = "\033[37m"
_C_BG_RED = "\033[41m"
_C_BG_GREEN = "\033[42m"
_C_BG_YELLOW = "\033[43m"


def _colored(text: str, *codes: str) -> str:
    """Wrap text in ANSI color codes."""
    return "".join(codes) + str(text) + _C_RESET


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    import re

    return re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", text)


def _visible_len(text: str) -> int:
    """Return visible length of text (ANSI codes stripped)."""
    return len(_strip_ansi(text))


def _fmt_val(val: Any, field_name: str = "") -> str:
    """Format a value for display.

    - Binary / image fields are shown as [binary: X.Y KB].
    - All other values are shown in full (no truncation).
    """
    if val is None:
        return "None"

    s = repr(val)

    # Detect binary/image fields by name or by base64-like content
    is_binary_field = any(
        kw in field_name.lower()
        for kw in ("image", "picture", "photo", "binary", "file", "attachment")
    )
    is_binary_like = isinstance(val, (str, bytes)) and len(s) > 200

    if is_binary_field or is_binary_like:
        # If the value is a file path (from XML type="base64" file="..."), show it.
        # Base64 strings can contain '/' so we gate on length — real paths are short.
        if isinstance(val, str) and ("/" in val or "\\" in val) and len(val) < 300:
            return val

        # Compute raw byte length
        if isinstance(val, bytes):
            byte_len = len(val)
        elif isinstance(val, str):
            byte_len = len(val.encode("utf-8", "replace"))
        else:
            byte_len = len(s)

        if byte_len < 1024:
            return f"[binary: {byte_len} B]"
        return f"[binary: {byte_len / 1024:.1f} KB]"

    return s


def _normalize_collection_for_display(value: Any) -> Optional[List[str]]:
    """Normalize simple collections for human-friendly diff display."""
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return None


def _format_wrapped_lines(
    label: str, value: str, width: int = 100, indent: str = "    "
) -> List[str]:
    """Render a labeled value with wrapping."""
    prefix = f"{indent}{label}: "
    body_width = max(width - len(prefix), 20)
    wrapped = textwrap.wrap(
        value,
        width=body_width,
        break_long_words=False,
        break_on_hyphens=False,
    )
    if not wrapped:
        return [prefix]
    lines = [prefix + wrapped[0]]
    continuation = " " * len(prefix)
    lines.extend(continuation + line for line in wrapped[1:])
    return lines


def _format_collection_diff_lines(
    xml_values: List[str], db_values: List[str], indent: str = "    "
) -> List[str]:
    """Render concise set-style differences for collection fields."""
    xml_only = [value for value in xml_values if value not in db_values]
    db_only = [value for value in db_values if value not in xml_values]
    lines: List[str] = []
    if xml_only:
        lines.append(f"{indent}Only in Source:")
        lines.extend(f"{indent}  - {value}" for value in xml_only)
    if db_only:
        lines.append(f"{indent}Only in DB:")
        lines.extend(f"{indent}  - {value}" for value in db_only)
    if not lines:
        lines.append(f"{indent}No material difference after normalization.")
    return lines


def _format_field_difference_lines(
    field_name: str, db_val: Any, xml_val: Any, indent: str = "  "
) -> List[str]:
    """Render a field difference in a readable block format."""
    lines = [f"{indent}{field_name}"]
    xml_collection = _normalize_collection_for_display(xml_val)
    db_collection = _normalize_collection_for_display(db_val)
    if xml_collection is not None and db_collection is not None:
        lines.extend(
            _format_collection_diff_lines(
                xml_collection,
                db_collection,
                indent=indent + "  ",
            )
        )
        return lines

    lines.extend(
        _format_wrapped_lines(
            "XML",
            _fmt_val(xml_val, field_name),
            indent=indent + "  ",
        )
    )
    lines.extend(
        _format_wrapped_lines(
            "DB",
            _fmt_val(db_val, field_name),
            indent=indent + "  ",
        )
    )
    return lines


def _build_field_diff_table(field_diffs: List[Tuple[str, str, str, str]]) -> List[str]:
    """Build a colored ASCII table from field difference rows.

    Each row is (record, field, xml_val, db_val).
    Returns list of line strings.
    """
    if not field_diffs:
        return []

    # Column widths (measure visible characters only)
    w_rec = max(_visible_len(r[0]) for r in field_diffs)
    w_fld = max(_visible_len(r[1]) for r in field_diffs)
    w_xml = max(_visible_len(_fmt_val(r[2], r[1])) for r in field_diffs)
    w_db = max(_visible_len(_fmt_val(r[3], r[1])) for r in field_diffs)

    # Minimum widths for readability
    w_rec = max(w_rec, 20)
    w_fld = max(w_fld, 18)
    w_xml = max(w_xml, 16)
    w_db = max(w_db, 16)

    sep = (
        "┌"
        + "─" * (w_rec + 2)
        + "┬"
        + "─" * (w_fld + 2)
        + "┬"
        + "─" * (w_xml + 2)
        + "┬"
        + "─" * (w_db + 2)
        + "┐"
    )
    mid = (
        "├"
        + "─" * (w_rec + 2)
        + "┼"
        + "─" * (w_fld + 2)
        + "┼"
        + "─" * (w_xml + 2)
        + "┼"
        + "─" * (w_db + 2)
        + "┤"
    )
    bot = (
        "└"
        + "─" * (w_rec + 2)
        + "┴"
        + "─" * (w_fld + 2)
        + "┴"
        + "─" * (w_xml + 2)
        + "┴"
        + "─" * (w_db + 2)
        + "┘"
    )

    def _cell(text: str, width: int, align: str = "<") -> str:
        pad = width - _visible_len(text)
        if align == ">":
            return " " + " " * pad + text + " "
        return " " + text + " " * pad + " "

    lines = [sep]
    lines.append(
        "│"
        + _cell(_colored("Record", _C_BOLD, _C_WHITE), w_rec)
        + "│"
        + _cell(_colored("Field", _C_BOLD, _C_WHITE), w_fld)
        + "│"
        + _cell(_colored("Source Value", _C_BOLD, _C_GREEN), w_xml)
        + "│"
        + _cell(_colored("DB Value", _C_BOLD, _C_RED), w_db)
        + "│"
    )
    lines.append(mid)

    prev_record = None
    for rec, fld, xml_v, db_v in field_diffs:
        display_rec = "" if rec == prev_record else rec
        prev_record = rec

        xml_str = _fmt_val(xml_v, fld)
        db_str = _fmt_val(db_v, fld)

        rec_cell = _cell(
            _colored(display_rec, _C_CYAN) if display_rec else _colored("⋮", _C_DIM),
            w_rec,
        )
        fld_cell = _cell(_colored(fld, _C_YELLOW), w_fld)

        # Highlight differing values — XML in green, DB in red so they pop
        xml_cell = _cell(_colored(xml_str, _C_GREEN), w_xml)
        db_cell = _cell(_colored(db_str, _C_RED), w_db)

        lines.append("│" + rec_cell + "│" + fld_cell + "│" + xml_cell + "│" + db_cell + "│")

    lines.append(bot)
    return lines


DETAIL_COLUMNS = (
    ("Model", 28),
    ("Record", 42),
    ("Issue", 18),
    ("Field", 18),
    ("Source State", 24),
    ("DB State", 24),
    ("Value", 72),
    ("File/Blocker", 36),
)


def _truncate_cell(value: Any, width: int) -> str:
    """Return a single-line table cell capped to width."""
    text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= width:
        return text
    return text[: max(width - 1, 0)] + "…"


def _discrepancy_summary_counts(discrepancies: List[Discrepancy]) -> List[str]:
    """Return concise discrepancy count lines."""
    lines = [f"Total discrepancies: {len(discrepancies)}"]
    for disc_type in DiscrepancyType:
        count = sum(1 for disc in discrepancies if disc.discrepancy_type == disc_type)
        if count:
            lines.append(f"  {_discrepancy_type_label(disc_type)}: {count}")
    return lines


def _detail_report_rows(discrepancies: List[Discrepancy]) -> List[Tuple[str, ...]]:
    """Flatten discrepancies into one row per atomic issue."""
    rows: List[Tuple[str, ...]] = []
    for disc in discrepancies:
        file_or_blocker = disc.file_path or disc.details.get("blocker", "")
        if disc.discrepancy_type == DiscrepancyType.FIELD_DIFFERENCE:
            for field_name, (db_val, xml_val) in disc.field_differences.items():
                xml_collection = _normalize_collection_for_display(xml_val)
                db_collection = _normalize_collection_for_display(db_val)
                if xml_collection is not None and db_collection is not None:
                    xml_only = [value for value in xml_collection if value not in db_collection]
                    db_only = [value for value in db_collection if value not in xml_collection]
                    for value in xml_only:
                        rows.append(
                            (
                                disc.model,
                                disc.xml_id,
                                "Only in Source",
                                field_name,
                                "Present",
                                "Missing",
                                value,
                                file_or_blocker,
                            )
                        )
                    for value in db_only:
                        rows.append(
                            (
                                disc.model,
                                disc.xml_id,
                                "Only in DB",
                                field_name,
                                "Missing",
                                "Present",
                                value,
                                file_or_blocker,
                            )
                        )
                    if not xml_only and not db_only:
                        rows.append(
                            (
                                disc.model,
                                disc.xml_id,
                                "Field difference",
                                field_name,
                                _fmt_val(xml_val, field_name),
                                _fmt_val(db_val, field_name),
                                "",
                                file_or_blocker,
                            )
                        )
                    continue

                rows.append(
                    (
                        disc.model,
                        disc.xml_id,
                        "Field difference",
                        field_name,
                        _fmt_val(xml_val, field_name),
                        _fmt_val(db_val, field_name),
                        "",
                        file_or_blocker,
                    )
                )
            continue

        if disc.discrepancy_type == DiscrepancyType.MISSING_IN_DB:
            rows.append(
                (
                    disc.model,
                    disc.xml_id,
                    "Source-only",
                    "",
                    "Present",
                    "Missing",
                    "",
                    file_or_blocker,
                )
            )
        elif disc.discrepancy_type == DiscrepancyType.MISSING_IN_XML:
            rows.append(
                (
                    disc.model,
                    disc.xml_id,
                    "Missing in Source",
                    "",
                    "Missing",
                    f"res_id={disc.db_values.get('res_id', 'N/A')}",
                    disc.details.get("generated_xml_id", ""),
                    file_or_blocker,
                )
            )
        elif disc.discrepancy_type == DiscrepancyType.MISSING_XML_ID:
            rows.append(
                (
                    disc.model,
                    disc.xml_id,
                    "Missing XML ID",
                    "",
                    "Source ID only",
                    f"res_id={disc.db_values.get('res_id', 'N/A')}",
                    disc.details.get("generated_xml_id", ""),
                    file_or_blocker,
                )
            )
        elif disc.discrepancy_type == DiscrepancyType.AMBIGUOUS_MATCH:
            rows.append(
                (
                    disc.model,
                    disc.xml_id,
                    "Ambiguous match",
                    "",
                    "Present",
                    "Multiple matches",
                    "",
                    "; ".join(disc.details.get("matches", [])),
                )
            )
        elif disc.discrepancy_type == DiscrepancyType.DUPLICATE_IN_XML:
            rows.append(
                (
                    disc.model,
                    disc.xml_id,
                    "Duplicate Source",
                    "",
                    disc.details.get("duplicate_file", disc.file_path or ""),
                    "Canonical source",
                    "",
                    disc.details.get("first_file", ""),
                )
            )
    return rows


def _format_detail_table(rows: List[Tuple[str, ...]]) -> List[str]:
    """Render detail rows in a compact fixed-width table."""
    if not rows:
        return []
    widths = [width for _, width in DETAIL_COLUMNS]
    header = " | ".join(
        _truncate_cell(label, width).ljust(width)
        for (label, width) in DETAIL_COLUMNS
    )
    separator = "-+-".join("-" * width for width in widths)
    lines = [header, separator]
    for row in rows:
        lines.append(
            " | ".join(
                _truncate_cell(value, width).ljust(width)
                for value, width in zip(row, widths)
            )
        )
    return lines


def format_report_text(discrepancies: List[Discrepancy]) -> str:
    """Return a compact row-based discrepancy report."""
    if not discrepancies:
        return "✓ No discrepancies found. Database and source data are in sync!"

    lines = []
    lines.append("=" * 80)
    lines.append("DISCREPANCY REPORT")
    lines.append("=" * 80)
    lines.extend(_discrepancy_summary_counts(discrepancies))
    lines.append("")
    lines.extend(_format_detail_table(_detail_report_rows(discrepancies)))
    lines.append("")
    lines.append("=" * 80)
    return "\n".join(lines)


def format_report_markdown(discrepancies: List[Discrepancy]) -> str:
    """Return a row-based Markdown report."""
    if not discrepancies:
        return "# Discrepancy Report\n\n✓ No discrepancies found. Database and source data are in sync!"

    lines = []
    lines.append("# Discrepancy Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    for line in _discrepancy_summary_counts(discrepancies):
        lines.append(f"- {line.strip()}")
    lines.append("")
    lines.append("## Details")
    lines.append("")
    labels = [label for label, _ in DETAIL_COLUMNS]
    lines.append("| " + " | ".join(labels) + " |")
    lines.append("| " + " | ".join("---" for _ in labels) + " |")
    for row in _detail_report_rows(discrepancies):
        escaped = [str(value or "").replace("|", "\\|") for value in row]
        lines.append("| " + " | ".join(escaped) + " |")
    return "\n".join(lines)


def format_summary_text(
    discrepancies: List[Discrepancy], xml_records: Dict[str, Dict], xml_models: set[str]
) -> str:
    """Return a compact per-model summary."""
    from collections import Counter, defaultdict

    xml_counts = Counter(r["model"] for r in xml_records.values())

    disc_counts: Dict[str, Dict[DiscrepancyType, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for d in discrepancies:
        disc_counts[d.model][d.discrepancy_type] += 1

    lines = []
    lines.append("=" * 80)
    lines.append("DISCREPANCY SUMMARY")
    lines.append("=" * 80)
    lines.append(f"{'Model':<50} {'Match':>8} {'Mismatch':>10}")
    lines.append("-" * 80)

    total_match = 0
    total_mismatch = 0
    for model in sorted(xml_models):
        xml_count = xml_counts.get(model, 0)
        missing_db = disc_counts[model].get(DiscrepancyType.MISSING_IN_DB, 0)
        field_diff = disc_counts[model].get(DiscrepancyType.FIELD_DIFFERENCE, 0)
        missing_xml = disc_counts[model].get(DiscrepancyType.MISSING_IN_XML, 0)
        missing_xml_id = disc_counts[model].get(DiscrepancyType.MISSING_XML_ID, 0)
        ambiguous = disc_counts[model].get(DiscrepancyType.AMBIGUOUS_MATCH, 0)
        duplicate_xml = disc_counts[model].get(DiscrepancyType.DUPLICATE_IN_XML, 0)

        match_count = xml_count - missing_db - field_diff - missing_xml_id - ambiguous
        mismatch_count = (
            missing_db
            + field_diff
            + missing_xml
            + missing_xml_id
            + ambiguous
            + duplicate_xml
        )

        total_match += match_count
        total_mismatch += mismatch_count

        if mismatch_count > 0:
            lines.append(
                f"{model:<50} {match_count:>8} {mismatch_count:>10}  <<<"
            )
        else:
            lines.append(f"{model:<50} {match_count:>8} {mismatch_count:>10}")

    lines.append("-" * 80)
    lines.append(f"{'TOTAL':<50} {total_match:>8} {total_mismatch:>10}")
    lines.append("=" * 80)
    return "\n".join(lines)


def format_summary_markdown(
    discrepancies: List[Discrepancy], xml_records: Dict[str, Dict], xml_models: set[str]
) -> str:
    """Return a compact per-model Markdown summary."""
    from collections import Counter, defaultdict

    xml_counts = Counter(r["model"] for r in xml_records.values())

    disc_counts: Dict[str, Dict[DiscrepancyType, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for d in discrepancies:
        disc_counts[d.model][d.discrepancy_type] += 1

    lines = []
    lines.append("# Discrepancy Summary")
    lines.append("")
    lines.append("| Model | Match | Mismatch |")
    lines.append("|-------|-------|----------|")

    total_match = 0
    total_mismatch = 0
    for model in sorted(xml_models):
        xml_count = xml_counts.get(model, 0)
        missing_db = disc_counts[model].get(DiscrepancyType.MISSING_IN_DB, 0)
        field_diff = disc_counts[model].get(DiscrepancyType.FIELD_DIFFERENCE, 0)
        missing_xml = disc_counts[model].get(DiscrepancyType.MISSING_IN_XML, 0)
        missing_xml_id = disc_counts[model].get(DiscrepancyType.MISSING_XML_ID, 0)
        ambiguous = disc_counts[model].get(DiscrepancyType.AMBIGUOUS_MATCH, 0)
        duplicate_xml = disc_counts[model].get(DiscrepancyType.DUPLICATE_IN_XML, 0)

        match_count = xml_count - missing_db - field_diff - missing_xml_id - ambiguous
        mismatch_count = (
            missing_db
            + field_diff
            + missing_xml
            + missing_xml_id
            + ambiguous
            + duplicate_xml
        )

        total_match += match_count
        total_mismatch += mismatch_count

        alert = " **<<<**" if mismatch_count > 0 else ""
        lines.append(f"| `{model}` | {match_count} | {mismatch_count}{alert} |")

    lines.append(f"| **TOTAL** | **{total_match}** | **{total_mismatch}** |")
    return "\n".join(lines)


# =============================================================================
# Interactive Resolver
# =============================================================================


class InteractiveResolver:
    """Handle interactive resolution of discrepancies."""

    XML_FLUSH_INTERVAL = 100

    def __init__(self, data_path: str, module: str, env, xml_records: Optional[Dict[str, Dict]] = None):
        self.data_path = Path(data_path)
        self.module = module
        self.env = env
        self.xml_records = xml_records or {}
        self.generated_xml_ids: Dict[Tuple[str, int], str] = {}
        self._reserved_xml_ids: set[str] = set(self.xml_records)
        self._xml_tree_cache: Dict[Path, Tuple[Any, Any]] = {}
        self._dirty_xml_trees: set[Path] = set()
        self._defer_xml_writes = False
        self._full_xml_id_cache: Dict[Tuple[str, int], Optional[str]] = {}
        self._source_xml_id_cache: Dict[Tuple[str, int], Optional[str]] = {}
        self._source_xml_indexes: Optional[Dict[str, Dict[str, str]]] = None
        self.stats = {
            "ignored": 0,
            "updated": 0,
            "total": 0,
        }

    def resolve(
        self,
        discrepancies: List[Discrepancy],
        auto_action: Optional[str] = None,
        update_limit: Optional[int] = None,
    ):
        """Resolve discrepancies interactively or automatically."""
        if not discrepancies:
            print("\n✓ No discrepancies found. Database and source data are in sync!")
            return

        if update_limit is None:
            self._prepare_generated_xml_ids(discrepancies)

        # Print grouped summary first
        print("\n" + format_report_text(discrepancies))
        print("\n" + "-" * 80)
        print("RESOLUTION")
        print("-" * 80)

        previous_defer = self._defer_xml_writes
        self._defer_xml_writes = auto_action == "update"
        try:
            for i, disc in enumerate(discrepancies, 1):
                if update_limit is not None and self.stats["updated"] >= update_limit:
                    print(
                        f"\nUpdate limit reached: {self.stats['updated']} successful source "
                        f"change{'s' if self.stats['updated'] != 1 else ''} applied."
                    )
                    break

                self.stats["total"] += 1
                if update_limit is not None:
                    self._prepare_generated_xml_ids([disc])

                print(f"\n[{i}/{len(discrepancies)}] {disc.xml_id} [{disc.model}]")

                for row_line in _format_detail_table(_detail_report_rows([disc])):
                    print(f"  {row_line}")

                # Determine action
                if auto_action == "ignore":
                    action = ResolutionAction.IGNORE
                    print("  [Auto] Ignored")
                elif auto_action == "update":
                    action = ResolutionAction.UPDATE_XML
                    print("  [Auto] Will update source data")
                else:
                    action = self._prompt_user(disc)

                if action == ResolutionAction.IGNORE:
                    self.stats["ignored"] += 1
                elif action == ResolutionAction.UPDATE_XML:
                    if self._update_xml(disc):
                        self.stats["updated"] += 1
                        if self.stats["updated"] % self.XML_FLUSH_INTERVAL == 0:
                            self._flush_dirty_xml_trees()
        finally:
            self._flush_dirty_xml_trees()
            self._defer_xml_writes = previous_defer

        self._print_summary()

    def _prepare_generated_xml_ids(self, discrepancies: List[Discrepancy]):
        """Build generated XML-ID lookup for this update batch."""
        reserved = set(self.xml_records) | set(self.generated_xml_ids.values())
        for disc in discrepancies:
            generated_xml_id = disc.details.get("generated_xml_id")
            if not generated_xml_id:
                continue
            record = self._get_record_for_discrepancy(disc)
            if record and record.exists():
                self.generated_xml_ids[_record_key(record)] = generated_xml_id
                reserved.add(generated_xml_id)
                self._reserved_xml_ids.add(generated_xml_id)

        for disc in discrepancies:
            if disc.discrepancy_type not in (
                DiscrepancyType.MISSING_IN_XML,
                DiscrepancyType.MISSING_XML_ID,
            ):
                continue
            record = self._get_record_for_discrepancy(disc)
            if not record or not record.exists() or _record_key(record) in self.generated_xml_ids:
                continue
            full_xml_id = _coerce_full_xml_id(
                self.module,
                self._generate_unique_xml_id_name(record, reserved),
            )
            self.generated_xml_ids[_record_key(record)] = full_xml_id
            disc.details["generated_xml_id"] = full_xml_id
            reserved.add(full_xml_id)
            self._reserved_xml_ids.add(full_xml_id)

    def _generate_unique_xml_id_name(self, record, reserved: set[str]) -> str:
        """Generate a local XML ID name unique against current source XML."""
        base_name = _generated_xml_id_name_for_record(record)
        candidate = base_name
        suffix = 2
        while _coerce_full_xml_id(self.module, candidate) in reserved:
            candidate = f"{base_name}_{suffix}"
            suffix += 1
        return candidate

    def _prompt_user(self, discrepancy: Discrepancy) -> ResolutionAction:
        """Prompt user for action on a discrepancy."""
        while True:
            source_type = discrepancy.details.get("source_type", "xml")
            if discrepancy.discrepancy_type in (
                DiscrepancyType.MISSING_IN_DB,
                DiscrepancyType.DUPLICATE_IN_XML,
            ):
                if source_type == "csv":
                    choice = input("  Action: [I]gnore? ").strip().lower()
                else:
                    choice = input("  Action: [I]gnore / [R]emove from XML? ").strip().lower()
            elif discrepancy.discrepancy_type == DiscrepancyType.MISSING_IN_XML:
                if source_type == "csv":
                    choice = input("  Action: [I]gnore? ").strip().lower()
                else:
                    # For records only in DB, ask if we should add to XML
                    choice = input("  Action: [I]gnore / [A]dd to XML? ").strip().lower()
            elif discrepancy.discrepancy_type == DiscrepancyType.AMBIGUOUS_MATCH:
                choice = input("  Action: [I]gnore? ").strip().lower()
            else:
                source_label = "CSV" if source_type == "csv" else "XML"
                choice = input(f"  Action: [I]gnore / [U]pdate {source_label}? ").strip().lower()

            if choice in ("i", "ignore", ""):
                return ResolutionAction.IGNORE
            elif choice in ("u", "update", "a", "add", "r", "remove"):
                return ResolutionAction.UPDATE_XML
            else:
                print("  Invalid choice. Please enter I or U/A.")

    def _update_xml(self, discrepancy: Discrepancy) -> bool:
        """Update or add a source definition for a record."""
        source_type = discrepancy.details.get("source_type", "xml")
        if source_type == "csv":
            return self._update_csv(discrepancy)

        if discrepancy.discrepancy_type == DiscrepancyType.AMBIGUOUS_MATCH:
            print("  [Update XML] Skipped ambiguous match")
            return False

        if discrepancy.discrepancy_type == DiscrepancyType.DUPLICATE_IN_XML:
            print("  [Update XML] Removing duplicate XML record...")
            return self._remove_record_from_xml(discrepancy, check_references=False)

        if discrepancy.discrepancy_type == DiscrepancyType.MISSING_IN_DB:
            print("  [Update XML] Removing source-only XML record...")
            return self._remove_record_from_xml(discrepancy)

        if discrepancy.discrepancy_type == DiscrepancyType.MISSING_IN_XML:
            # Need to add new record to XML
            print(f"  [Update XML] Adding {discrepancy.xml_id} to data file...")
            return self._add_record_to_xml(discrepancy)

        if discrepancy.discrepancy_type == DiscrepancyType.MISSING_XML_ID:
            print("  [Update XML] Renaming source XML ID...")
            return self._rename_source_xml_id(discrepancy)

        # Update existing fields in XML
        print(f"  [Update XML] Updating fields in existing XML...")
        return self._update_existing_xml(discrepancy)

    def _update_csv(self, discrepancy: Discrepancy) -> bool:
        """Update supported fields in an existing CSV data row."""
        if discrepancy.discrepancy_type != DiscrepancyType.FIELD_DIFFERENCE:
            print("  [Update CSV] Skipped: CSV add/remove/rename is not supported")
            return False
        print("  [Update CSV] Updating supported fields in existing CSV row...")
        return self._update_existing_csv(discrepancy)

    def _xml_file_path(self, file_path: Path) -> Path:
        """Return an absolute data XML path for cache keys."""
        path = Path(file_path)
        if not path.is_absolute():
            path = self.data_path / path
        return path

    def _load_xml_tree(self, file_path: Path, create: bool = False):
        """Load an XML file once per resolver run."""
        path = self._xml_file_path(file_path)
        cached = self._xml_tree_cache.get(path)
        if cached:
            return cached

        if path.exists():
            tree = ET.parse(path)
            root = tree.getroot()
        elif create:
            path.parent.mkdir(parents=True, exist_ok=True)
            root = ET.Element("odoo")
            ET.SubElement(root, "data")
            tree = ET.ElementTree(root)
        else:
            raise FileNotFoundError(path)

        self._xml_tree_cache[path] = (tree, root)
        return tree, root

    def _mark_xml_tree_dirty(self, file_path: Path, flush_now: bool = False):
        """Mark a cached XML tree as changed and flush when appropriate."""
        path = self._xml_file_path(file_path)
        self._dirty_xml_trees.add(path)
        if flush_now or not self._defer_xml_writes:
            self._flush_dirty_xml_trees({path})

    def _flush_dirty_xml_trees(self, paths: Optional[set[Path]] = None):
        """Write dirty cached XML trees to disk."""
        dirty_paths = set(self._dirty_xml_trees)
        if paths is not None:
            dirty_paths &= {self._xml_file_path(path) for path in paths}

        for path in sorted(dirty_paths):
            cached = self._xml_tree_cache.get(path)
            if not cached:
                self._dirty_xml_trees.discard(path)
                continue
            tree, _root = cached
            path.parent.mkdir(parents=True, exist_ok=True)
            self._write_formatted_xml_tree(path, tree)
            self._dirty_xml_trees.discard(path)

    def _write_formatted_xml_tree(self, file_path: Path, tree):
        """Write an XML tree with stable indentation."""
        try:
            ET.indent(tree, space="    ")
        except AttributeError:
            pass
        tree.write(file_path, encoding="utf-8", xml_declaration=True)

    def _rename_source_xml_id(self, discrepancy: Discrepancy) -> bool:
        """Rename an XML record ID and rewrite source references to it."""
        generated_xml_id = discrepancy.details.get("generated_xml_id")
        if not generated_xml_id:
            print(f"  Cannot update {discrepancy.xml_id}: no generated XML ID")
            return False
        if generated_xml_id == discrepancy.xml_id:
            print("  XML ID already matches generated source ID")
            return False
        if not discrepancy.file_path:
            print("  Error: Cannot determine source XML file")
            return False

        file_path = self.data_path / discrepancy.file_path
        if not file_path.exists():
            print(f"  Error: File not found: {file_path}")
            return False

        old_short = discrepancy.xml_id.split(".")[-1]
        new_short = generated_xml_id.split(".")[-1]
        tree = ET.parse(file_path)
        root = tree.getroot()
        renamed = False
        for record_elem in root.findall(".//record"):
            if record_elem.get("id") in (old_short, discrepancy.xml_id):
                record_elem.set("id", new_short)
                renamed = True
                break
        if not renamed:
            print(f"  Error: Record not found in XML file: {discrepancy.xml_id}")
            return False
        tree.write(file_path, encoding="utf-8", xml_declaration=True)
        self._rewrite_xml_references(discrepancy.xml_id, generated_xml_id)
        print(f"  Renamed: {discrepancy.xml_id} -> {generated_xml_id}")
        return True

    def _rewrite_xml_references(self, old_full_xml_id: str, new_full_xml_id: str):
        """Rewrite XML refs from one XML ID to another across data files."""
        old_short = old_full_xml_id.split(".")[-1]
        new_short = new_full_xml_id.split(".")[-1]
        variants = {old_full_xml_id: new_full_xml_id, old_short: new_short}
        for xml_file in self.data_path.rglob("*.xml"):
            try:
                tree = ET.parse(xml_file)
            except ET.ParseError:
                continue
            root = tree.getroot()
            changed = False
            for field_elem in root.findall(".//field"):
                ref_value = field_elem.get("ref")
                if ref_value in variants:
                    field_elem.set("ref", variants[ref_value])
                    changed = True
                for attr_name in ("eval", "search"):
                    expression = field_elem.get(attr_name)
                    if not expression:
                        continue
                    new_expression = self._replace_ref_calls(expression, variants)
                    if new_expression != expression:
                        field_elem.set(attr_name, new_expression)
                        changed = True
            if changed:
                self._write_formatted_xml_tree(xml_file, tree)

    def _replace_ref_calls(self, expression: str, replacements: Dict[str, str]) -> str:
        """Replace ref('xml_id') values in an XML eval/search expression."""
        def replace(match):
            xml_id = match.group(1)
            replacement = replacements.get(xml_id)
            if not replacement:
                return match.group(0)
            quote = "'" if "'" in match.group(0) else '"'
            return f"ref({quote}{replacement}{quote})"

        return XML_REF_RE.sub(replace, expression)

    def _remove_record_from_xml(self, discrepancy: Discrepancy, check_references: bool = True) -> bool:
        """Remove an XML-only record after checking explicit XML references."""
        if not discrepancy.file_path:
            print("  Error: Cannot determine source XML file")
            return False

        references = self._find_xml_references(discrepancy.xml_id) if check_references else []
        if references:
            print(f"  Cannot remove {discrepancy.xml_id}: referenced by XML records:")
            for reference in references[:10]:
                print(f"    - {reference}")
            if len(references) > 10:
                print(f"    ... {len(references) - 10} more")
            return False

        file_path = self.data_path / discrepancy.file_path
        if not file_path.exists():
            print(f"  Error: File not found: {file_path}")
            return False

        tree = ET.parse(file_path)
        root = tree.getroot()
        parent_map = {child: parent for parent in root.iter() for child in parent}
        xml_id_short = discrepancy.xml_id.split(".")[-1]

        matches = [
            record_elem
            for record_elem in root.findall(".//record")
            if record_elem.get("id") in (xml_id_short, discrepancy.xml_id)
        ]
        if matches:
            record_elem = (
                matches[-1]
                if discrepancy.discrepancy_type == DiscrepancyType.DUPLICATE_IN_XML
                else matches[0]
            )
            parent = parent_map.get(record_elem, root)
            parent.remove(record_elem)
            self._write_formatted_xml_tree(file_path, tree)
            print(f"  Removed: {file_path}")
            return True

        print(f"  Error: Record not found in XML file: {discrepancy.xml_id}")
        return False

    def _find_xml_references(self, full_xml_id: str) -> List[str]:
        """Find parsed XML records that explicitly reference an XML ID."""
        references: List[str] = []
        for xml_id, xml_record in sorted(self.xml_records.items()):
            if xml_id == full_xml_id:
                continue
            for field_name, field_def in xml_record.get("fields", {}).items():
                if _field_references_xml_id(self.module, field_def, full_xml_id):
                    references.append(f"{xml_id}.{field_name}")
        return references

    def _add_record_to_xml(self, discrepancy: Discrepancy) -> bool:
        """Add a new record definition to an XML file."""
        # Determine target file based on model
        target_file = self._determine_target_file(discrepancy.model, discrepancy)
        file_path = self.data_path / target_file

        # Create record XML
        try:
            xml_content = self._generate_record_xml(discrepancy)
        except ValueError as exc:
            print(f"  Cannot update {discrepancy.xml_id}: {exc}")
            return False

        # Append to file or create new
        if file_path.exists():
            self._append_to_existing_file(file_path, xml_content)
        else:
            self._create_new_data_file(file_path, xml_content)

        print(f"  Created/updated: {file_path}")
        return True

    def _update_existing_xml(self, discrepancy: Discrepancy) -> bool:
        """Update field values in existing XML file."""
        if not discrepancy.file_path:
            print("  Error: Cannot determine source XML file")
            return False

        file_path = self.data_path / discrepancy.file_path
        if not file_path.exists():
            print(f"  Error: File not found: {file_path}")
            return False

        # Parse and update
        try:
            tree, root = self._load_xml_tree(file_path)
        except FileNotFoundError:
            print(f"  Error: File not found: {file_path}")
            return False
        ptal_value_eval = None
        if (
            discrepancy.model == PTAL_MODEL
            and PTAL_VALUE_FIELD in discrepancy.field_differences
        ):
            value_records = discrepancy.db_values.get(PTAL_VALUE_FIELD)
            if value_records is None:
                record = self._get_record_for_discrepancy(discrepancy)
                value_records = getattr(record, PTAL_VALUE_FIELD, None) if record else None
            try:
                ptal_value_eval = self._serialize_record_refs(value_records or [], PTAL_VALUE_FIELD)
            except ValueError as exc:
                print(f"  Cannot update {discrepancy.xml_id}: {exc}")
                return False

        # Find the record
        xml_id_short = discrepancy.xml_id.split(".")[-1]
        for record_elem in root.findall(".//record"):
            if record_elem.get("id") == xml_id_short:
                # Update fields
                changed = False
                for field_name, (db_val, _) in discrepancy.field_differences.items():
                    try:
                        field_meta = self.env[discrepancy.model]._fields.get(field_name)
                    except (KeyError, AttributeError):
                        field_meta = None

                    if field_meta and getattr(field_meta, "type", None) == "one2many":
                        continue

                    field_elem = record_elem.find(f"field[@name='{field_name}']")

                    if field_elem is None:
                        # Add new field element
                        field_elem = ET.SubElement(record_elem, "field")
                        field_elem.set("name", field_name)

                    if (
                        discrepancy.model == PTAL_MODEL
                        and field_name == PTAL_VALUE_FIELD
                        and ptal_value_eval is not None
                    ):
                        for attr in ["ref", "eval", "search", "type", "file"]:
                            field_elem.attrib.pop(attr, None)
                        field_elem.set("eval", ptal_value_eval)
                        field_elem.text = None
                        changed = True
                        continue

                    try:
                        self._set_field_xml_value(field_elem, field_meta, db_val)
                    except ValueError as exc:
                        print(f"  Cannot update {discrepancy.xml_id}: {exc}")
                        return False
                    changed = True
                    continue

                if not changed:
                    print("  No supported fields to update")
                    return False
                self._mark_xml_tree_dirty(file_path)
                print(f"  Updated: {file_path}")
                return True

        print(f"  Error: Record not found in XML file: {discrepancy.xml_id}")
        return False

    def _update_existing_csv(self, discrepancy: Discrepancy) -> bool:
        """Update supported field values in an existing CSV row."""
        if not discrepancy.file_path:
            print("  Error: Cannot determine source CSV file")
            return False

        file_path = self.data_path / discrepancy.file_path
        if not file_path.exists():
            print(f"  Error: File not found: {file_path}")
            return False

        source_record = self.xml_records.get(discrepancy.xml_id)
        row_index = discrepancy.details.get("csv_row_index")
        if row_index is None and source_record:
            row_index = source_record.get("csv_row_index")
        if row_index is None:
            print("  Error: Cannot determine source CSV row")
            return False

        with open(file_path, "r", encoding="utf-8", newline="") as csv_file:
            rows = list(csv.reader(csv_file, quotechar='"', delimiter=","))
        if not rows or row_index >= len(rows):
            print(f"  Error: CSV row not found: {discrepancy.xml_id}")
            return False

        headers = rows[0]
        row = rows[row_index]
        if len(row) < len(headers):
            row.extend([""] * (len(headers) - len(row)))

        changed = False
        unsupported = []
        source_fields = (source_record or {}).get("fields", {})
        for field_name, (db_val, _xml_val) in discrepancy.field_differences.items():
            raw_db_val = discrepancy.db_values.get(field_name, db_val)
            field_def = source_fields.get(field_name)
            header = (field_def or {}).get("csv_header")
            if not header or header not in headers:
                unsupported.append(field_name)
                continue
            try:
                field_meta = self.env[discrepancy.model]._fields.get(field_name)
            except (KeyError, AttributeError):
                field_meta = None
            try:
                csv_value = self._serialize_csv_field_value(field_meta, raw_db_val)
            except ValueError as exc:
                print(f"  Cannot update {discrepancy.xml_id}.{field_name}: {exc}")
                continue
            column_index = headers.index(header)
            if row[column_index] != csv_value:
                row[column_index] = csv_value
                changed = True

        if unsupported:
            print("  Skipped unsupported CSV fields: " + ", ".join(sorted(unsupported)))
        if not changed:
            print("  No supported CSV fields to update")
            return False

        with open(file_path, "w", encoding="utf-8", newline="") as csv_file:
            writer = csv.writer(csv_file, quotechar='"', delimiter=",")
            writer.writerows(rows)
        print(f"  Updated: {file_path}")
        return True

    def _serialize_csv_field_value(self, field_meta, db_val) -> str:
        """Serialize a DB value into an Odoo CSV import cell."""
        field_type = getattr(field_meta, "type", None)
        if field_type in ("one2many", "many2many", "binary"):
            raise ValueError(f"unsupported CSV field type: {field_type}")
        if field_type == "many2one":
            if _is_empty_record(db_val):
                return ""
            ref_xml_id = self._get_xml_id_for_record(db_val)
            if not ref_xml_id:
                raise ValueError(f"missing XML ID for {db_val._name},{db_val.id}")
            return ref_xml_id
        if field_type == "boolean":
            return "True" if bool(db_val) else "False"
        if db_val is None or db_val is False:
            return ""
        return str(db_val)

    def _get_or_generate_xml_id_for_record(self, root, record) -> str:
        """Return an existing or generated XML ID for a record."""
        xml_id = self._get_xml_id_for_record(record)
        if xml_id:
            return xml_id

        base_name = _generated_xml_id_name_for_record(record)
        candidate = base_name
        suffix = 2
        while _coerce_full_xml_id(self.module, candidate) in self._reserved_xml_ids:
            candidate = f"{base_name}_{suffix}"
            suffix += 1
        full_xml_id = _coerce_full_xml_id(self.module, candidate)
        self.generated_xml_ids[_record_key(record)] = full_xml_id
        self._reserved_xml_ids.add(full_xml_id)
        return full_xml_id

    def _clear_field_xml_value(self, field_elem):
        """Remove XML value-carrying attributes before setting a field value."""
        for attr in ["ref", "eval", "search", "type", "file"]:
            field_elem.attrib.pop(attr, None)
        field_elem.text = None

    def _set_field_xml_value(self, field_elem, field_meta, db_val):
        """Serialize a DB value into an XML field element."""
        field_type = getattr(field_meta, "type", None)
        if field_type == "boolean":
            self._clear_field_xml_value(field_elem)
            field_elem.set("eval", "True" if bool(db_val) else "False")
            return

        if field_type == "many2one":
            self._clear_field_xml_value(field_elem)
            if _is_empty_record(db_val):
                return
            ref_xml_id = self._get_xml_id_for_record(db_val)
            if not ref_xml_id:
                raise ValueError(f"missing XML ID for {db_val._name},{db_val.id}")
            field_elem.set("ref", ref_xml_id)
            return

        if field_type == "many2many":
            self._clear_field_xml_value(field_elem)
            field_elem.set("eval", self._serialize_record_refs(db_val or [], "many2many field"))
            return

        if field_type in ("integer", "float", "monetary"):
            self._clear_field_xml_value(field_elem)
            field_elem.text = str(db_val if db_val is not None else "")
            return

        # Fallback for char, text, html, selection, and legacy unknown metadata.
        self._clear_field_xml_value(field_elem)
        if isinstance(db_val, str) and "." in db_val and field_type is None:
            field_elem.set("ref", db_val)
            return
        field_elem.text = str(db_val) if db_val is not None else ""

    def _determine_target_file(self, model: str, discrepancy: Optional[Discrepancy] = None) -> str:
        """Determine target XML file based on model name."""
        if model == PTAL_MODEL and discrepancy:
            sibling_file = self._find_ptal_sibling_file(discrepancy)
            if sibling_file:
                return sibling_file
        if model == "product.attribute.value" and discrepancy:
            sibling_file = self._find_attribute_value_sibling_file(discrepancy)
            if sibling_file:
                return sibling_file
        if model == "product.attribute" and discrepancy and discrepancy.file_path:
            return discrepancy.file_path

        sibling_file = self._find_model_sibling_file(model)
        if sibling_file:
            return sibling_file

        model_to_file = {
            "product.category": "product_categories.xml",
            "product.attribute": "attributes/generated.xml",
            "product.attribute.value": "attributes/generated.xml",
            "product.template": "products/products.xml",
            "mrp.workcenter": "ibcorr_workcenter_data.xml",
            "ir.config_parameter": "ir_config_parameter.xml",
            "stock.location": "stock_locations.xml",
        }

        if model in model_to_file:
            return model_to_file[model]

        # Default: create in misc.xml
        return "misc.xml"

    def _find_model_sibling_file(self, model: str) -> Optional[str]:
        """Reuse the most common existing XML file for a model."""
        file_counts: Dict[str, int] = {}
        for xml_record in self.xml_records.values():
            if xml_record.get("model") != model:
                continue
            file_path = xml_record.get("file")
            if file_path:
                file_counts[file_path] = file_counts.get(file_path, 0) + 1
        if not file_counts:
            return None
        return sorted(file_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

    def _generate_record_xml(self, discrepancy: Discrepancy) -> str:
        """Generate XML string for a record."""
        record = self._get_record_for_discrepancy(discrepancy)
        if not record or not record.exists():
            raise ValueError("record not found in database")

        if discrepancy.model == PTAL_MODEL:
            return self._generate_ptal_record_xml(discrepancy, record)

        lines = []
        xml_id_short = discrepancy.xml_id.split(".")[-1]

        lines.append(f'    <record id="{xml_id_short}" model="{discrepancy.model}">')
        # Get all fields from the model
        for field_name, field in self.env[discrepancy.model]._fields.items():
            if field_name in AUDIT_FIELD_NAMES:
                continue
            if getattr(field, "type", None) in ("one2many", "many2many"):
                continue
            if getattr(field, "compute", None) and not getattr(field, "inverse", None):
                continue
            if getattr(field, "readonly", False) and not getattr(field, "inverse", None):
                continue

            value = getattr(record, field_name, None)
            if value is None or value is False:
                continue

            # Handle reference fields (many2one)
            if field.type == "many2one" and isinstance(value, models.Model):
                ref_xml_id = self._get_xml_id_for_record(value)
                if ref_xml_id:
                    lines.append(
                        f'        <field name="{field_name}" ref="{ref_xml_id}"/>'
                    )
                continue

            # Handle boolean
            if field.type == "boolean":
                lines.append(
                    f'        <field name="{field_name}" eval="{value}"/>'
                )
                continue

            # Handle numeric
            if field.type in ("integer", "float", "monetary"):
                lines.append(
                    f'        <field name="{field_name}">{value}</field>'
                )
                continue

            # Default: string value
            escaped_value = (
                str(value)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            lines.append(
                f'        <field name="{field_name}">{escaped_value}</field>'
            )

        lines.append("    </record>")

        return "\n".join(lines)

    def _get_xml_id_for_record(self, record: models.Model) -> Optional[str]:
        """Get XML ID for a database record."""
        if not record:
            return None
        generated_xml_id = self.generated_xml_ids.get(_record_key(record))
        if generated_xml_id:
            return generated_xml_id
        record_key = _record_key(record)
        if record_key not in self._full_xml_id_cache:
            self._full_xml_id_cache[record_key] = _get_full_xml_id_for_record(self.env, record)
        return self._full_xml_id_cache[record_key] or self._get_source_xml_id_for_record(record)

    def _get_source_xml_id_for_record(self, record) -> Optional[str]:
        """Resolve a DB record to an XML source record by natural key."""
        record_key = _record_key(record)
        if record_key in self._source_xml_id_cache:
            return self._source_xml_id_cache[record_key]

        indexed_xml_id = self._get_indexed_source_xml_id_for_record(record)
        if indexed_xml_id:
            self._source_xml_id_cache[record_key] = indexed_xml_id
            return indexed_xml_id

        for xml_id, xml_record in self.xml_records.items():
            if self._xml_record_matches_db_record(xml_id, xml_record, record):
                full_xml_id = _coerce_full_xml_id(self.module, xml_record.get("xml_id", xml_id))
                self._source_xml_id_cache[record_key] = full_xml_id
                return full_xml_id
        self._source_xml_id_cache[record_key] = None
        return None

    def _get_indexed_source_xml_id_for_record(self, record) -> Optional[str]:
        """Resolve common source XML records without scanning every XML record."""
        indexes = self._build_source_xml_indexes()
        for lookup_key in self._source_xml_lookup_keys_from_record(record):
            xml_id = indexes.get(record._name, {}).get(lookup_key)
            if xml_id:
                return xml_id
        return None

    def _build_source_xml_indexes(self) -> Dict[str, Dict[str, str]]:
        """Build natural-key indexes for source XML records used during updates."""
        if self._source_xml_indexes is not None:
            return self._source_xml_indexes
        self._source_xml_indexes = {}
        for xml_id, xml_record in self.xml_records.items():
            self._index_xml_record(xml_id, xml_record)
        return self._source_xml_indexes

    def _index_xml_record(self, xml_id: str, xml_record: Dict[str, Any]):
        """Add a parsed XML record to resolver lookup indexes."""
        if self._source_xml_indexes is None:
            return
        full_xml_id = _coerce_full_xml_id(self.module, xml_record.get("xml_id", xml_id))
        model = xml_record.get("model")
        if not model:
            return
        model_index = self._source_xml_indexes.setdefault(model, {})
        for lookup_key in self._source_xml_lookup_keys_from_fields(
            model,
            xml_record.get("fields", {}),
        ):
            if lookup_key not in model_index:
                model_index[lookup_key] = full_xml_id

    def _source_xml_lookup_keys_from_record(self, record) -> List[str]:
        """Return natural lookup keys for common source records."""
        model = record._name
        if model == "ibcorr.import.source.item.code":
            source_item_code = getattr(record, "source_item_code", None)
            return [f"source_item_code:{source_item_code}"] if source_item_code else []
        if model == "ibcorr.import.source.code.segment":
            source_token = getattr(record, "source_token", None)
            position = getattr(record, "position", None)
            keys = []
            if position not in (None, False, "") and source_token:
                keys.append(f"position_token:{position}|{source_token}")
            if source_token:
                keys.append(f"source_token:{source_token}")
            return keys
        if model == "product.attribute":
            name = getattr(record, "name", None)
            return [f"name:{name}"] if name else []
        return []

    def _source_xml_lookup_keys_from_fields(
        self,
        model: str,
        fields_data: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        """Return natural lookup keys for parsed XML source records."""
        if model == "ibcorr.import.source.item.code":
            source_item_code = self._xml_plain_value(fields_data.get("source_item_code"))
            return [f"source_item_code:{source_item_code}"] if source_item_code else []
        if model == "ibcorr.import.source.code.segment":
            source_token = self._xml_plain_value(fields_data.get("source_token"))
            position = self._xml_plain_value(fields_data.get("position"))
            keys = []
            if position and source_token:
                keys.append(f"position_token:{position}|{source_token}")
            if source_token:
                keys.append(f"source_token:{source_token}")
            return keys
        if model == "product.attribute":
            name = self._xml_plain_value(fields_data.get("name"))
            return [f"name:{name}"] if name else []
        return []

    def _xml_record_matches_db_record(
        self,
        xml_id: str,
        xml_record: Dict[str, Any],
        record,
        visited: Optional[set[str]] = None,
    ) -> bool:
        """Return whether a source XML record naturally identifies a DB record."""
        if xml_record.get("model") != record._name:
            return False
        visited = visited or set()
        if xml_id in visited:
            return False
        visited.add(xml_id)
        fields_data = xml_record.get("fields", {})

        if record._name == "product.attribute":
            return self._xml_plain_value(fields_data.get("name")) == getattr(record, "name", None)

        if record._name == "product.attribute.value":
            return (
                self._xml_plain_value(fields_data.get("name")) == getattr(record, "name", None)
                and self._xml_ref_matches_record(
                    fields_data.get("attribute_id"),
                    record.attribute_id,
                    visited,
                )
            )

        if record._name == PTAL_MODEL:
            return (
                self._xml_ref_matches_record(
                    fields_data.get("product_tmpl_id"),
                    record.product_tmpl_id,
                    visited,
                )
                and self._xml_ref_matches_record(
                    fields_data.get("attribute_id"),
                    record.attribute_id,
                    visited,
                )
            )

        if record._name == "ibcorr.import.source.item.code.part":
            return (
                self._xml_ref_matches_record(
                    fields_data.get("source_code_id"),
                    record.source_code_id,
                    visited,
                )
                and self._xml_plain_value(fields_data.get("sequence")) == str(record.sequence)
                and self._xml_plain_value(fields_data.get("position")) == str(record.position)
                and self._xml_plain_value(fields_data.get("source_token"))
                == getattr(record, "source_token", None)
            )

        if record._name == "ibcorr.import.source.item.code.value":
            return (
                self._xml_ref_matches_record(
                    fields_data.get("source_code_id"),
                    record.source_code_id,
                    visited,
                )
                and self._xml_plain_value(fields_data.get("sequence")) == str(record.sequence)
                and self._xml_plain_value(fields_data.get("attribute_value_label"))
                == getattr(record, "attribute_value_label", None)
                and self._xml_plain_value(fields_data.get("value_source"))
                == getattr(record, "value_source", None)
                and self._xml_plain_value(fields_data.get("evidence_source"))
                == getattr(record, "evidence_source", None)
                and self._xml_plain_value(fields_data.get("evidence_note"))
                == (getattr(record, "evidence_note", None) or "")
            )

        comparator = DatabaseComparator(self.env, self.module)
        matches = comparator._find_natural_key_matches(record._name, fields_data)
        return len(matches) == 1 and matches[0].id == record.id

    def _xml_plain_value(self, field_def: Optional[Dict[str, Any]]):
        """Return a simple parsed XML field value."""
        if not field_def:
            return None
        return str(field_def.get("value", "")).strip()

    def _xml_ref_matches_record(
        self,
        field_def: Optional[Dict[str, Any]],
        record,
        visited: set[str],
    ) -> bool:
        """Return whether an XML ref points to a DB record or matching source record."""
        if not field_def or field_def.get("type") != "ref" or not record:
            return False
        ref_xml_id = _coerce_full_xml_id(self.module, field_def["value"])
        ref_record = _env_ref(self.env, self.module, ref_xml_id, raise_if_not_found=False)
        if ref_record and ref_record._name == record._name and ref_record.id == record.id:
            return True
        source_record = self.xml_records.get(ref_xml_id)
        if not source_record:
            source_record = self.xml_records.get(ref_xml_id.split(".")[-1])
        return bool(
            source_record
            and self._xml_record_matches_db_record(ref_xml_id, source_record, record, visited)
        )

    def _serialize_record_refs(self, records, field_label: str) -> str:
        """Serialize records as an explicit XML eval ref list."""
        refs = []
        missing = []
        for record in _sort_records_for_xml(records):
            xml_id = self._get_xml_id_for_record(record)
            if xml_id:
                refs.append(f"ref('{xml_id}')")
            else:
                missing.append(f"{record._name},{record.id}")
        if missing:
            raise ValueError(f"missing XML IDs for {field_label}: " + ", ".join(missing))
        return f"[(6, 0, [{', '.join(refs)}])]"

    def _get_record_for_discrepancy(self, discrepancy: Discrepancy):
        """Fetch the underlying DB record for a discrepancy."""
        res_id = discrepancy.db_values.get("res_id")
        if res_id:
            return self.env[discrepancy.model].browse(res_id)

        xml_id_short = discrepancy.xml_id.split(".")[-1]
        xml_id_rec = self.env["ir.model.data"].search(
            [
                ("module", "=", self.module),
                ("name", "=", xml_id_short),
            ],
            limit=1,
        )
        if not xml_id_rec:
            return None
        return self.env[discrepancy.model].browse(xml_id_rec.res_id)

    def _find_ptal_sibling_file(self, discrepancy: Discrepancy) -> Optional[str]:
        """Reuse a sibling PTAL file when adding a missing PTAL record."""
        record = self._get_record_for_discrepancy(discrepancy)
        if not record:
            return None

        template_xml_id = _get_full_xml_id_for_record(self.env, record.product_tmpl_id)
        if not template_xml_id:
            return None

        for xml_record in self.xml_records.values():
            if xml_record.get("model") != PTAL_MODEL:
                continue
            field_def = xml_record.get("fields", {}).get("product_tmpl_id")
            if not field_def or field_def.get("type") != "ref":
                continue
            if _coerce_full_xml_id(self.module, field_def["value"]) == template_xml_id:
                return xml_record.get("file")
        return None

    def _find_attribute_value_sibling_file(self, discrepancy: Discrepancy) -> Optional[str]:
        """Place attribute values next to their parent attribute XML."""
        record = self._get_record_for_discrepancy(discrepancy)
        if not record:
            return None
        attribute = getattr(record, "attribute_id", None)
        if not attribute:
            return None

        attribute_xml_ids = {
            xml_id
            for key, xml_id in self.generated_xml_ids.items()
            if key == _record_key(attribute)
        }
        existing_xml_id = _get_full_xml_id_for_record(self.env, attribute)
        if existing_xml_id:
            attribute_xml_ids.add(existing_xml_id)

        for xml_id, xml_record in self.xml_records.items():
            if xml_record.get("model") != "product.attribute":
                continue
            full_xml_id = _coerce_full_xml_id(self.module, xml_record.get("xml_id", xml_id))
            if full_xml_id in attribute_xml_ids or xml_id in attribute_xml_ids:
                return xml_record.get("file")

        for xml_record in self.xml_records.values():
            if xml_record.get("model") != "product.attribute":
                continue
            matches = DatabaseComparator(self.env, self.module)._find_natural_key_matches(
                "product.attribute",
                xml_record.get("fields", {}),
            )
            if matches and matches[0].id == attribute.id:
                return xml_record.get("file")
        return None

    def _generate_ptal_record_xml(self, discrepancy: Discrepancy, record) -> str:
        """Generate a focused PTAL XML record with explicit value_ids."""
        product_tmpl_xml_id = self._get_xml_id_for_record(record.product_tmpl_id)
        attribute_xml_id = self._get_xml_id_for_record(record.attribute_id)
        if not product_tmpl_xml_id:
            raise ValueError(
                f"missing XML ID for product template product.template,{record.product_tmpl_id.id}"
            )
        if not attribute_xml_id:
            raise ValueError(
                f"missing XML ID for attribute product.attribute,{record.attribute_id.id}"
            )

        value_ids_eval = self._serialize_record_refs(record.value_ids, PTAL_VALUE_FIELD)
        xml_id_short = discrepancy.xml_id.split(".")[-1]
        lines = [
            f'    <record id="{xml_id_short}" model="{discrepancy.model}">',
            f'        <field name="product_tmpl_id" ref="{product_tmpl_xml_id}"/>',
            f'        <field name="attribute_id" ref="{attribute_xml_id}"/>',
            f'        <field name="sequence">{record.sequence}</field>',
            f'        <field name="value_ids" eval="{value_ids_eval}"/>',
            "    </record>",
        ]
        return "\n".join(lines)

    def _append_to_existing_file(self, file_path: Path, xml_content: str):
        """Append record to existing XML file."""
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Prefer appending inside an existing <data> block so noupdate is preserved.
        insert_pos = content.rfind("</data>")
        if insert_pos < 0:
            insert_pos = content.rfind("</odoo>")
        if insert_pos > 0:
            new_content = (
                content[:insert_pos] + xml_content + "\n" + content[insert_pos:]
            )
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            self._format_xml_file(file_path)

    def _create_new_data_file(self, file_path: Path, xml_content: str):
        """Create a new XML data file."""
        file_path.parent.mkdir(parents=True, exist_ok=True)

        content = f"""<?xml version="1.0" encoding="utf-8"?>
<odoo>
{xml_content}
</odoo>
"""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        self._format_xml_file(file_path)

    def _format_xml_file(self, file_path: Path):
        """Format an XML file in place when it can be parsed."""
        try:
            tree = ET.parse(file_path)
        except ET.ParseError:
            return
        self._write_formatted_xml_tree(file_path, tree)

    def _print_summary(self):
        """Print summary statistics."""
        print("\n" + "=" * 50)
        print("SYNCHRONIZATION SUMMARY")
        print("=" * 50)
        print(f"Total discrepancies checked: {self.stats['total']}")
        print(f"Ignored:                   {self.stats['ignored']}")
        print(f"Source changes applied:    {self.stats['updated']}")
        print("=" * 50)


# =============================================================================
# Main
# =============================================================================


def read_config() -> Dict[str, str]:
    """Read database configuration from odoo.conf."""
    config = configparser.ConfigParser()

    if not CONFIG_FILE.exists():
        print(f"Error: Config file not found: {CONFIG_FILE}")
        print("Run: odoo-init-env from the current directory to create odoo.conf")
        sys.exit(1)

    config.read(CONFIG_FILE)

    # Use DB_NAME from environment (set by .env via common.sh) as primary source
    db_name = os.environ.get("DB_NAME")
    if not db_name:
        db_name = config.get("options", "db_name", fallback="")

    return {
        "db_host": config.get("options", "db_host", fallback="localhost"),
        "db_port": config.get("options", "db_port", fallback="5432"),
        "db_name": db_name,
        "db_user": config.get("options", "db_user", fallback="odoo"),
        "db_password": config.get("options", "db_password", fallback="odoo"),
        "addons_path": config.get("options", "addons_path", fallback=""),
    }


def _positive_int(value: str) -> int:
    """Argparse type for positive integer values."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def update_requested(update_arg: Any) -> bool:
    """Return whether update mode was requested."""
    return update_arg is not False


def update_limit_from_arg(update_arg: Any) -> Optional[int]:
    """Return the successful-update limit from parsed args, if any."""
    if update_arg is False or update_arg is None:
        return None
    return int(update_arg)


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Compare database records with XML/CSV data files and manage discrepancies",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sync_xml_data.py --module ibcorr              # Summary report
  python sync_xml_data.py --module ibcorr --detail     # Full detail report
  python sync_xml_data.py --module ibcorr --update     # Update all source files after confirmation
  python sync_xml_data.py --module ibcorr --update 25  # Apply 25 successful source changes
  python sync_xml_data.py --module ibcorr --img        # Include image/binary fields
  python sync_xml_data.py --module ibcorr --models     # List models
  python sync_xml_data.py --module ibcorr --profile    # Print timing/counter profile
        """,
    )
    parser.add_argument(
        "--module",
        help="Module name to check (e.g., ibcorr, ibcorr_base)",
    )
    parser.add_argument(
        "--update",
        nargs="?",
        const=None,
        default=False,
        metavar="N",
        type=_positive_int,
        help=(
            "Update source files after confirmation. With N, stop after N successful source "
            "changes; without N, update all discrepancies."
        ),
    )
    parser.add_argument(
        "--out",
        metavar="PATH",
        help="Also write the report to a Markdown file",
    )
    parser.add_argument(
        "--models",
        action="store_true",
        help="List models found in the module's XML/CSV data files and exit",
    )
    parser.add_argument(
        "--model",
        metavar="MODEL",
        help="Filter discrepancies to a single model name (exact match)",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Show full discrepancy details (default is summary only)",
    )
    parser.add_argument(
        "--img",
        action="store_true",
        help="Include image and binary fields in comparison (default: skip them)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print raw XML vs DB field comparisons for every record",
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Print sync timing and operation counters for performance investigation",
    )
    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()
    profiler = SyncProfiler(args.profile)

    # Show help if no module provided
    if not args.module:
        parser.print_help()
        sys.exit(1)

    if args.models and (update_requested(args.update) or args.model or args.detail or args.img):
        print(
            "Error: --models cannot be combined with --update, --model, --detail, or --img"
        )
        sys.exit(1)

    module = args.module

    # Verify PROJECT_ROOT is valid
    if not PROJECT_ROOT.exists():
        print(f"Error: PROJECT_ROOT does not exist: {PROJECT_ROOT}")
        print("Check your .env file or run: odoo-init-env")
        sys.exit(1)

    data_path = PROJECT_ROOT / module / "data"

    # Verify paths
    if not (PROJECT_ROOT / module).exists():
        print(f"Error: Module '{module}' not found at {PROJECT_ROOT / module}")
        sys.exit(1)

    if not data_path.exists():
        print(f"Error: Data folder not found at {data_path}")
        sys.exit(1)

    # Parse source data files (needed for both --models and full comparison)
    with profiler.time("source parsing"):
        xml_parser = XMLDataParser(str(data_path), module)
        try:
            xml_records = xml_parser.parse_all_files()
        except FileNotFoundError as e:
            print(f"Error: {e}")
            sys.exit(1)

    # --models: print models and counts, then exit
    if args.models:
        from collections import Counter

        model_counts = Counter(r["model"] for r in xml_records.values())
        print(f"\nModels found in {module}/data/:\n")
        for model_name in sorted(model_counts):
            count = model_counts[model_name]
            print(f"  {model_name:<50} {count:>3} record{'s' if count != 1 else ''}")
        profile_report = profiler.format_report()
        if profile_report:
            print(profile_report)
        sys.exit(0)

    model_filter = None
    if args.model:
        with profiler.time("model discovery/filter"):
            try:
                project_models = discover_project_models(PROJECT_ROOT, module)
                model_filter = resolve_model_filter(args.model, xml_parser.models, project_models)
            except ValueError as exc:
                print(f"Error: {exc}")
                sys.exit(2)

    # Read config
    with profiler.time("config reading"):
        db_config = read_config()

    # Configure Odoo
    with profiler.time("Odoo config setup"):
        odoo_args = [
            f"--db_host={db_config['db_host']}",
            f"--db_port={db_config['db_port']}",
            f"--database={db_config['db_name']}",
            f"--db_user={db_config['db_user']}",
            f"--db_password={db_config['db_password']}",
        ]
        if db_config.get("addons_path"):
            odoo_args.append(f"--addons-path={db_config['addons_path']}")
        odoo.tools.config.parse_config(odoo_args, setup_logging=False)
        _configure_quiet_odoo_logging()

    # Create registry and environment
    try:
        with profiler.time("registry setup"):
            registry = Registry(db_config["db_name"])
    except Exception as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)

    with registry.cursor() as cr:
        env = api.Environment(cr, odoo.SUPERUSER_ID, {})
        comparison_models = comparison_model_scope(xml_parser.models, model_filter)
        comparison_records = xml_records
        duplicate_records = list(xml_parser.duplicates)
        if model_filter:
            comparison_models = {model_filter}
            comparison_records = {
                xml_id: xml_record
                for xml_id, xml_record in xml_records.items()
                if xml_record.get("model") == model_filter
            }
            duplicate_records = [
                discrepancy
                for discrepancy in duplicate_records
                if discrepancy.model == model_filter
            ]
        with profiler.time("project field discovery"):
            comparator = DatabaseComparator(
                env,
                module,
                compare_images=args.img,
                debug=args.debug,
                profiler=profiler,
            )
        with profiler.time("comparison"):
            discrepancies = duplicate_records + comparator.compare(
                comparison_records,
                comparison_models,
                source_records=xml_records,
            )

        # Filter by --model if requested
        with profiler.time("report formatting"):
            if model_filter:
                discrepancies = [d for d in discrepancies if d.model == model_filter]
                report_models = {model_filter}
            else:
                report_models = xml_parser.models

            # Choose report depth based on --detail
            if args.detail:
                report_text = format_report_text(discrepancies)
                md_formatter = format_report_markdown
            else:
                report_text = format_summary_text(
                    discrepancies, xml_records, report_models
                )
                md_formatter = lambda d: format_summary_markdown(  # noqa: E731
                    d, xml_records, report_models
                )

        print(report_text)

        if args.out:
            with profiler.time("report writing"):
                md_path = Path(args.out)
                md_path.parent.mkdir(parents=True, exist_ok=True)
                md_content = md_formatter(discrepancies)
                md_path.write_text(md_content, encoding="utf-8")
            print(f"\nMarkdown report written to: {md_path}")

        if update_requested(args.update) and discrepancies:
            with profiler.time("update resolution"):
                update_limit = update_limit_from_arg(args.update)
                prompt = "\nProceed with updates? [Y/n] "
                if update_limit is not None:
                    prompt = (
                        f"\nProceed with updates? Limit: {update_limit} successful source "
                        f"change{'s' if update_limit != 1 else ''}. [Y/n] "
                    )
                choice = input(prompt).strip().lower()
                if choice in ("y", "yes", ""):
                    resolver = InteractiveResolver(str(data_path), module, env, xml_records=xml_records)
                    resolver.resolve(
                        discrepancies,
                        auto_action="update",
                        update_limit=update_limit,
                    )
                else:
                    print("Update cancelled.")

        profile_report = profiler.format_report()
        if profile_report:
            print(profile_report)

    # Exit with appropriate code
    sys.exit(0 if not discrepancies else 1)


if __name__ == "__main__":
    main()
