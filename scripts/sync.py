#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare database records with XML data files and manage discrepancies interactively.

Usage:
    python sync_xml_data.py --module MODULE_NAME [options]

Options:
    --module MODULE     Module name to check (required)
    --dry-run           Show discrepancies without prompting
    --auto-ignore       Automatically ignore all discrepancies
    --auto-update       Automatically update XML for all discrepancies

Examples:
    python sync_xml_data.py --module ibcorr
    python sync_xml_data.py --module ibcorr --dry-run
    python sync_xml_data.py --module ibcorr --auto-update
"""

import os
import sys
import argparse
import configparser
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

# =============================================================================
# Configuration
# =============================================================================


# Read from environment (set by sync.sh which sources common.sh)
ENV_DIR = Path(os.environ.get("ENV_DIR", Path.cwd()))
PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", ENV_DIR))
ODOO_ROOT = Path(os.environ.get("ODOO_ROOT", "/home/gdt/Odoo/V19"))
ODOO_SOURCE = ODOO_ROOT / "odoo"
CONFIG_FILE = Path(os.environ.get("CONF_FILE", ENV_DIR / "odoo.conf"))

# Add Odoo to path
if str(ODOO_SOURCE) not in sys.path:
    sys.path.insert(0, str(ODOO_SOURCE))

# Suppress Odoo warnings
import logging

logging.getLogger("odoo.tools.config").setLevel(logging.ERROR)
logging.getLogger("odoo.modules").setLevel(logging.ERROR)
logging.getLogger("odoo.modules.loading").setLevel(logging.CRITICAL)
logging.getLogger("odoo").setLevel(logging.WARNING)
logging.getLogger("py.warnings").setLevel(logging.ERROR)
logging.getLogger("odoo.addons.attachment_indexation").setLevel(logging.ERROR)

# Module logger
_logger = logging.getLogger(__name__)

import odoo
from odoo import fields, models, api
from odoo.modules.registry import Registry


# =============================================================================
# Data Classes
# =============================================================================


class DiscrepancyType(Enum):
    """Types of discrepancies between DB and XML."""

    MISSING_IN_DB = "missing_in_db"
    MISSING_IN_XML = "missing_in_xml"
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

    def __str__(self):
        if self.discrepancy_type == DiscrepancyType.MISSING_IN_DB:
            return f"[{self.model}] {self.xml_id}: Missing in database"
        elif self.discrepancy_type == DiscrepancyType.MISSING_IN_XML:
            return f"[{self.model}] {self.xml_id}: Missing in XML (exists only in DB)"
        elif self.discrepancy_type == DiscrepancyType.FIELD_DIFFERENCE:
            fields_str = ", ".join(
                f"{k}=(DB:{v[0]}|XML:{v[1]})" for k, v in self.field_differences.items()
            )
            return f"[{self.model}] {self.xml_id}: Field differences: {fields_str}"
        return f"[{self.model}] {self.xml_id}: Unknown"


# =============================================================================
# XML Parser
# =============================================================================


class XMLDataParser:
    """Parse XML data files and extract record definitions."""

    def __init__(self, data_path: str, module: str):
        self.data_path = Path(data_path)
        self.module = module
        self.records: Dict[str, Dict] = {}
        self.file_mapping: Dict[str, str] = {}
        self.models: set[str] = set()

    def parse_all_files(self) -> Dict[str, Dict]:
        """Parse all XML files in data directory."""
        if not self.data_path.exists():
            raise FileNotFoundError(f"Data path not found: {self.data_path}")

        xml_files = list(self.data_path.rglob("*.xml"))

        for xml_file in xml_files:
            try:
                self._parse_file(xml_file)
            except ET.ParseError as e:
                print(f"  Warning: Could not parse {xml_file}: {e}")
                continue

        return self.records

    def _parse_file(self, file_path: Path):
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

                if search_expr:
                    fields_data[field_name] = {"type": "search", "value": search_expr}
                elif ref:
                    fields_data[field_name] = {"type": "ref", "value": ref}
                elif eval_expr:
                    fields_data[field_name] = {"type": "eval", "value": eval_expr}
                elif field_elem.get("type") == "base64" and field_elem.get("file"):
                    fields_data[field_name] = {
                        "type": "base64",
                        "value": field_elem.get("file"),
                    }
                else:
                    fields_data[field_name] = {
                        "type": "value",
                        "value": field_elem.text or "",
                    }

            self.records[full_xml_id] = {
                "xml_id": xml_id,
                "model": model,
                "fields": fields_data,
                "file": str(file_path.relative_to(self.data_path)),
            }
            self.file_mapping[full_xml_id] = str(file_path)


# =============================================================================
# Database Comparator
# =============================================================================


class DatabaseComparator:
    """Compare database records with XML definitions."""

    def __init__(self, env, module: str, compare_images: bool = False, debug: bool = False):
        self.env = env
        self.module = module
        self.compare_images = compare_images
        self.debug = debug

    def compare(
        self, xml_records: Dict[str, Dict], xml_models: set[str]
    ) -> List[Discrepancy]:
        """Compare XML records with database records."""
        discrepancies = []
        db_xml_ids = self._get_db_xml_ids()
        skipped_records: List[str] = []

        # Check: Records in XML but missing or different in DB
        for full_xml_id, xml_record in xml_records.items():
            disc = self._compare_single_record(
                full_xml_id, xml_record, db_xml_ids, skipped_records
            )
            if disc:
                discrepancies.append(disc)

        # Check: Records in DB but not in XML (only for models that appear in XML files)
        for full_xml_id, db_record in db_xml_ids.items():
            if full_xml_id not in xml_records and db_record["model"] in xml_models:
                disc = Discrepancy(
                    xml_id=full_xml_id,
                    model=db_record["model"],
                    discrepancy_type=DiscrepancyType.MISSING_IN_XML,
                    db_values={"res_id": db_record["res_id"]},
                )
                discrepancies.append(disc)

        return discrepancies

    def _get_db_xml_ids(self) -> Dict[str, Dict]:
        """Get all XML IDs from the database for this module."""
        result = {}
        xml_id_records = self.env["ir.model.data"].search(
            [("module", "=", self.module)]
        )

        for xml_id_rec in xml_id_records:
            full_xml_id = f"{xml_id_rec.module}.{xml_id_rec.name}"
            result[full_xml_id] = {
                "model": xml_id_rec.model,
                "res_id": xml_id_rec.res_id,
                "id": xml_id_rec.id,
            }
        return result

    def _compare_single_record(
        self, full_xml_id: str, xml_record: Dict, db_xml_ids: Dict[str, Dict], skipped: List[str]
    ) -> Optional[Discrepancy]:
        """Compare a single XML record with database."""
        model_name = xml_record["model"]
        xml_fields = xml_record["fields"]

        # Check if record exists in DB
        if full_xml_id not in db_xml_ids:
            return Discrepancy(
                xml_id=full_xml_id,
                model=model_name,
                discrepancy_type=DiscrepancyType.MISSING_IN_DB,
                xml_values={k: v["value"] for k, v in xml_fields.items()},
                file_path=xml_record.get("file"),
            )

        # Get database record
        db_xml_rec = db_xml_ids[full_xml_id]
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
            )

        # Compare field values
        field_differences = {}

        if self.debug:
            print(f"[DEBUG] Comparing {full_xml_id} ({model_name})")

        for field_name, field_def in xml_fields.items():
            field_type = field_def["type"]

            # Skip fields defined with `search` or `eval` — dynamically resolved by Odoo at load time
            if field_type in ("search", "eval"):
                continue

            xml_value = field_def["value"]
            db_value = getattr(db_record, field_name, None)

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
                field_meta = self.env[model_name]._fields.get(field_name)
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
                db_values={k: getattr(db_record, k, None) for k in xml_fields.keys()},
                xml_values={k: v["value"] for k, v in xml_fields.items()},
                field_differences=field_differences,
                file_path=xml_record.get("file"),
            )

        return None

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
            if isinstance(value, models.Model):
                xml_id = self.env["ir.model.data"].search(
                    [
                        ("model", "=", value._name),
                        ("res_id", "=", value.id),
                    ],
                    limit=1,
                )
                if xml_id:
                    return f"{xml_id.module}.{xml_id.name}"
                return f"{value._name},{value.id}"
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

from collections import defaultdict


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
        + _cell(_colored("XML Value", _C_BOLD, _C_GREEN), w_xml)
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


def format_report_text(discrepancies: List[Discrepancy]) -> str:
    """Return a grouped, human-readable text report."""
    if not discrepancies:
        return "✓ No discrepancies found. Database and XML are in sync!"

    lines = []
    lines.append("=" * 80)
    lines.append("DISCREPANCY REPORT")
    lines.append("=" * 80)

    total = len(discrepancies)
    missing_db = sum(
        1 for d in discrepancies if d.discrepancy_type == DiscrepancyType.MISSING_IN_DB
    )
    missing_xml = sum(
        1 for d in discrepancies if d.discrepancy_type == DiscrepancyType.MISSING_IN_XML
    )
    field_diff = sum(
        1
        for d in discrepancies
        if d.discrepancy_type == DiscrepancyType.FIELD_DIFFERENCE
    )

    lines.append(f"Total discrepancies: {total}")
    lines.append(f"  Missing in DB:     {missing_db}")
    lines.append(f"  Missing in XML:    {missing_xml}")
    lines.append(f"  Field differences: {field_diff}")
    lines.append("")

    by_model = defaultdict(list)
    for disc in discrepancies:
        by_model[disc.model].append(disc)

    for model in sorted(by_model.keys()):
        model_discs = by_model[model]
        lines.append("-" * 80)
        lines.append(model)
        lines.append("-" * 80)

        by_type = defaultdict(list)
        for disc in model_discs:
            by_type[disc.discrepancy_type].append(disc)

        for disc_type in (
            DiscrepancyType.FIELD_DIFFERENCE,
            DiscrepancyType.MISSING_IN_DB,
            DiscrepancyType.MISSING_IN_XML,
        ):
            if disc_type not in by_type:
                continue

            type_discs = by_type[disc_type]
            lines.append("")
            lines.append(f"  {disc_type.value.replace('_', ' ').title()} ({len(type_discs)})")

            field_diff_rows: List[Tuple[str, str, str, str]] = []
            missing_db_ids: List[str] = []
            missing_xml_ids: List[str] = []

            for disc in type_discs:
                if disc_type == DiscrepancyType.FIELD_DIFFERENCE:
                    for field_name, (db_val, xml_val) in disc.field_differences.items():
                        field_diff_rows.append(
                            (disc.xml_id, field_name, xml_val, db_val)
                        )
                elif disc_type == DiscrepancyType.MISSING_IN_DB:
                    missing_db_ids.append(disc.xml_id)
                elif disc_type == DiscrepancyType.MISSING_IN_XML:
                    missing_xml_ids.append(
                        f"{disc.xml_id} (res_id={disc.db_values.get('res_id', 'N/A')})"
                    )

            if field_diff_rows:
                lines.extend(_build_field_diff_table(field_diff_rows))
            for item in missing_db_ids:
                lines.append(f"    {item}")
            for item in missing_xml_ids:
                lines.append(f"    {item}")

    lines.append("")
    lines.append("=" * 80)
    return "\n".join(lines)


def format_report_markdown(discrepancies: List[Discrepancy]) -> str:
    """Return a grouped Markdown report."""
    if not discrepancies:
        return "# Discrepancy Report\n\n✓ No discrepancies found. Database and XML are in sync!"

    lines = []
    lines.append("# Discrepancy Report")
    lines.append("")

    total = len(discrepancies)
    missing_db = sum(
        1 for d in discrepancies if d.discrepancy_type == DiscrepancyType.MISSING_IN_DB
    )
    missing_xml = sum(
        1 for d in discrepancies if d.discrepancy_type == DiscrepancyType.MISSING_IN_XML
    )
    field_diff = sum(
        1
        for d in discrepancies
        if d.discrepancy_type == DiscrepancyType.FIELD_DIFFERENCE
    )

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total discrepancies:** {total}")
    lines.append(f"- **Missing in DB:** {missing_db}")
    lines.append(f"- **Missing in XML:** {missing_xml}")
    lines.append(f"- **Field differences:** {field_diff}")
    lines.append("")

    by_model = defaultdict(list)
    for disc in discrepancies:
        by_model[disc.model].append(disc)

    for model in sorted(by_model.keys()):
        model_discs = by_model[model]
        lines.append(f"## {model}")
        lines.append("")

        by_type = defaultdict(list)
        for disc in model_discs:
            by_type[disc.discrepancy_type].append(disc)

        for disc_type in (
            DiscrepancyType.FIELD_DIFFERENCE,
            DiscrepancyType.MISSING_IN_DB,
            DiscrepancyType.MISSING_IN_XML,
        ):
            if disc_type not in by_type:
                continue

            type_discs = by_type[disc_type]
            lines.append(
                f"### {disc_type.value.replace('_', ' ').title()} ({len(type_discs)})"
            )
            lines.append("")

            for disc in type_discs:
                if disc_type == DiscrepancyType.FIELD_DIFFERENCE:
                    lines.append(f"**`{disc.xml_id}`**")
                    lines.append("")
                    lines.append("| Field | DB Value | XML Value |")
                    lines.append("|-------|----------|-----------|")
                    for field_name, (db_val, xml_val) in disc.field_differences.items():
                        lines.append(
                            f"| `{field_name}` | `{db_val!r}` | `{xml_val!r}` |"
                        )
                    lines.append("")
                elif disc_type == DiscrepancyType.MISSING_IN_DB:
                    lines.append(f"- `{disc.xml_id}`")
                elif disc_type == DiscrepancyType.MISSING_IN_XML:
                    lines.append(
                        f"- `{disc.xml_id}` (res_id={disc.db_values.get('res_id', 'N/A')})"
                    )
            lines.append("")

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

        match_count = xml_count - missing_db - field_diff
        mismatch_count = missing_db + field_diff + missing_xml

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

        match_count = xml_count - missing_db - field_diff
        mismatch_count = missing_db + field_diff + missing_xml

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

    def __init__(self, data_path: str, module: str, env):
        self.data_path = Path(data_path)
        self.module = module
        self.env = env
        self.stats = {
            "ignored": 0,
            "updated": 0,
            "total": 0,
        }

    def resolve(
        self, discrepancies: List[Discrepancy], auto_action: Optional[str] = None
    ):
        """Resolve discrepancies interactively or automatically."""
        if not discrepancies:
            print("\n✓ No discrepancies found. Database and XML are in sync!")
            return

        # Print grouped summary first
        print("\n" + format_report_text(discrepancies))
        print("\n" + "-" * 80)
        print("RESOLUTION")
        print("-" * 80)

        for i, disc in enumerate(discrepancies, 1):
            self.stats["total"] += 1

            print(f"\n[{i}/{len(discrepancies)}] {disc.xml_id} [{disc.model}]")

            if disc.discrepancy_type == DiscrepancyType.FIELD_DIFFERENCE:
                rows = [
                    (disc.xml_id, field_name, xml_val, db_val)
                    for field_name, (db_val, xml_val) in disc.field_differences.items()
                ]
                print("  Field differences:")
                for line in _build_field_diff_table(rows):
                    print("  " + line)
            elif disc.discrepancy_type == DiscrepancyType.MISSING_IN_DB:
                print("  Missing in database (record defined in XML only)")
            elif disc.discrepancy_type == DiscrepancyType.MISSING_IN_XML:
                print(
                    f"  Missing in XML (record exists in DB, res_id={disc.db_values.get('res_id', 'N/A')})"
                )

            # Determine action
            if auto_action == "ignore":
                action = ResolutionAction.IGNORE
                print("  [Auto] Ignored")
            elif auto_action == "update":
                action = ResolutionAction.UPDATE_XML
                print("  [Auto] Will update XML")
            else:
                action = self._prompt_user(disc)

            if action == ResolutionAction.IGNORE:
                self.stats["ignored"] += 1
            elif action == ResolutionAction.UPDATE_XML:
                self._update_xml(disc)
                self.stats["updated"] += 1

        self._print_summary()

    def _prompt_user(self, discrepancy: Discrepancy) -> ResolutionAction:
        """Prompt user for action on a discrepancy."""
        while True:
            if discrepancy.discrepancy_type == DiscrepancyType.MISSING_IN_XML:
                # For records only in DB, ask if we should add to XML
                choice = input("  Action: [I]gnore / [A]dd to XML? ").strip().lower()
            else:
                choice = input("  Action: [I]gnore / [U]pdate XML? ").strip().lower()

            if choice in ("i", "ignore", ""):
                return ResolutionAction.IGNORE
            elif choice in ("u", "update", "a", "add"):
                return ResolutionAction.UPDATE_XML
            else:
                print("  Invalid choice. Please enter I or U/A.")

    def _update_xml(self, discrepancy: Discrepancy):
        """Update or add XML definition for a record."""
        if discrepancy.discrepancy_type == DiscrepancyType.MISSING_IN_DB:
            print(f"  [Update XML] Record exists only in XML - nothing to update")
            return

        if discrepancy.discrepancy_type == DiscrepancyType.MISSING_IN_XML:
            # Need to add new record to XML
            print(f"  [Update XML] Adding {discrepancy.xml_id} to data file...")
            self._add_record_to_xml(discrepancy)
        else:
            # Update existing fields in XML
            print(f"  [Update XML] Updating fields in existing XML...")
            self._update_existing_xml(discrepancy)

    def _add_record_to_xml(self, discrepancy: Discrepancy):
        """Add a new record definition to an XML file."""
        # Determine target file based on model
        target_file = self._determine_target_file(discrepancy.model)
        file_path = self.data_path / target_file

        # Create record XML
        xml_content = self._generate_record_xml(discrepancy)

        # Append to file or create new
        if file_path.exists():
            self._append_to_existing_file(file_path, xml_content)
        else:
            self._create_new_data_file(file_path, xml_content)

        print(f"  Created/updated: {file_path}")

    def _update_existing_xml(self, discrepancy: Discrepancy):
        """Update field values in existing XML file."""
        if not discrepancy.file_path:
            print("  Error: Cannot determine source XML file")
            return

        file_path = self.data_path / discrepancy.file_path
        if not file_path.exists():
            print(f"  Error: File not found: {file_path}")
            return

        # Parse and update
        tree = ET.parse(file_path)
        root = tree.getroot()

        # Find the record
        xml_id_short = discrepancy.xml_id.split(".")[-1]
        for record_elem in root.findall(".//record"):
            if record_elem.get("id") == xml_id_short:
                # Update fields
                for field_name, (db_val, _) in discrepancy.field_differences.items():
                    field_elem = record_elem.find(f"field[@name='{field_name}']")

                    if field_elem is None:
                        # Add new field element
                        field_elem = ET.SubElement(record_elem, "field")
                        field_elem.set("name", field_name)

                    # Update value (handle ref/eval appropriately)
                    if isinstance(db_val, str) and "." in db_val:
                        # Assume it's a reference
                        field_elem.set("ref", db_val)
                        field_elem.text = None
                    else:
                        field_elem.text = str(db_val) if db_val is not None else ""
                        # Remove ref/eval if present
                        for attr in ["ref", "eval"]:
                            if attr in field_elem.attrib:
                                del field_elem.attrib[attr]

                break

        # Write back
        tree.write(file_path, encoding="utf-8", xml_declaration=True)
        print(f"  Updated: {file_path}")

    def _determine_target_file(self, model: str) -> str:
        """Determine target XML file based on model name."""
        model_to_file = {
            "product.category": "product_categories.xml",
            "product.attribute": "attributes/{attribute_name}.xml",
            "product.attribute.value": "attributes/{attribute_name}.xml",
            "product.template": "products/products.xml",
            "mrp.workcenter": "ibcorr_workcenter_data.xml",
            "ir.config_parameter": "ir_config_parameter.xml",
            "stock.location": "stock_locations.xml",
        }

        if model in model_to_file:
            return model_to_file[model]

        # Default: create in misc.xml
        return "misc.xml"

    def _generate_record_xml(self, discrepancy: Discrepancy) -> str:
        """Generate XML string for a record."""
        lines = []
        xml_id_short = discrepancy.xml_id.split(".")[-1]

        lines.append(f'    <record id="{xml_id_short}" model="{discrepancy.model}">')

        # Need to fetch full record from DB to get all fields
        # Get the actual record
        xml_id_rec = self.env["ir.model.data"].search(
            [
                ("module", "=", self.module),
                ("name", "=", xml_id_short),
            ],
            limit=1,
        )

        if xml_id_rec:
            record = self.env[discrepancy.model].browse(xml_id_rec.res_id)
            if record.exists():
                # Get all fields from the model
                for field_name, field in self.env[discrepancy.model]._fields.items():
                    if field_name in (
                        "id",
                        "create_uid",
                        "create_date",
                        "write_uid",
                        "write_date",
                    ):
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
        xml_id_rec = self.env["ir.model.data"].search(
            [
                ("model", "=", record._name),
                ("res_id", "=", record.id),
            ],
            limit=1,
        )

        if xml_id_rec:
            if xml_id_rec.module == self.module:
                return xml_id_rec.name
            return f"{xml_id_rec.module}.{xml_id_rec.name}"
        return None

    def _append_to_existing_file(self, file_path: Path, xml_content: str):
        """Append record to existing XML file."""
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Find closing </odoo> tag and insert before it
        insert_pos = content.rfind("</odoo>")
        if insert_pos > 0:
            new_content = (
                content[:insert_pos] + xml_content + "\n" + content[insert_pos:]
            )
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)

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

    def _print_summary(self):
        """Print summary statistics."""
        print("\n" + "=" * 50)
        print("SYNCHRONIZATION SUMMARY")
        print("=" * 50)
        print(f"Total discrepancies checked: {self.stats['total']}")
        print(f"Ignored:                   {self.stats['ignored']}")
        print(f"Updated/Added to XML:      {self.stats['updated']}")
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


def main():
    parser = argparse.ArgumentParser(
        description="Compare database records with XML data files and manage discrepancies",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sync_xml_data.py --module ibcorr              # Summary report
  python sync_xml_data.py --module ibcorr --detail     # Full detail report
  python sync_xml_data.py --module ibcorr --update     # Update XML after confirmation
  python sync_xml_data.py --module ibcorr --img        # Include image/binary fields
  python sync_xml_data.py --module ibcorr --models     # List models
        """,
    )
    parser.add_argument(
        "--module",
        help="Module name to check (e.g., ibcorr, ibcorr_base)",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Update XML for all discrepancies after confirmation",
    )
    parser.add_argument(
        "--out",
        metavar="PATH",
        help="Also write the report to a Markdown file",
    )
    parser.add_argument(
        "--models",
        action="store_true",
        help="List models found in the module's XML data files and exit",
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

    args = parser.parse_args()

    # Show help if no module provided
    if not args.module:
        parser.print_help()
        sys.exit(1)

    if args.models and (args.update or args.model or args.detail or args.img):
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

    # Parse XML files (needed for both --models and full comparison)
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
        sys.exit(0)

    # Read config
    db_config = read_config()

    # Configure Odoo
    odoo_args = [
        f"--db_host={db_config['db_host']}",
        f"--db_port={db_config['db_port']}",
        f"--database={db_config['db_name']}",
        f"--db_user={db_config['db_user']}",
        f"--db_password={db_config['db_password']}",
    ]
    if db_config.get("addons_path"):
        odoo_args.append(f"--addons-path={db_config['addons_path']}")
    odoo.tools.config.parse_config(odoo_args)

    # Create registry and environment
    try:
        registry = Registry(db_config["db_name"])
    except Exception as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)

    with registry.cursor() as cr:
        env = api.Environment(cr, odoo.SUPERUSER_ID, {})
        comparator = DatabaseComparator(env, module, compare_images=args.img, debug=args.debug)
        discrepancies = comparator.compare(xml_records, xml_parser.models)
        print(f"[DEBUG] Total discrepancies returned: {len(discrepancies)}")
        for d in discrepancies[:10]:
            print(f"  {d.xml_id} [{d.model}] {d.discrepancy_type.value}")

        # Filter by --model if requested
        if args.model:
            discrepancies = [d for d in discrepancies if d.model == args.model]
            report_models = {args.model}
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
            md_path = Path(args.out)
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_content = md_formatter(discrepancies)
            md_path.write_text(md_content, encoding="utf-8")
            print(f"\nMarkdown report written to: {md_path}")

        if args.update and discrepancies:
            choice = input("\nProceed with updates? [Y/n] ").strip().lower()
            if choice in ("y", "yes", ""):
                resolver = InteractiveResolver(str(data_path), module, env)
                resolver.resolve(discrepancies, auto_action="update")
            else:
                print("Update cancelled.")

    # Exit with appropriate code
    sys.exit(0 if not discrepancies else 1)


if __name__ == "__main__":
    main()
