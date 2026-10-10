#!/usr/bin/env python3
"""Migrate a legacy utils runtime into the .odoo runtime contract."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
CONFIG_KEYS = {
    "ODOO_ROOT", "ODOO_DATA_DIR", "PYTHON_PATH", "DB_NAME", "DB_HOST", "DB_PORT",
    "DB_USER", "HTTP_PORT", "TEST_HTTP_PORT", "TEST_GEVENT_PORT",
    "TEST_PORT_RANGE_START", "TEST_PORT_RANGE_END", "ODOO_LOCAL_URL", "ODOO_LOCAL_DB",
    "ODOO_LOCAL_API_KEY", "ODOO_REMOTE_URL", "ODOO_REMOTE_DB", "ODOO_REMOTE_API_KEY",
    "ODOO_DIRECT_USER", "ODOO_DIRECT_API_KEY",
}


class MigrationError(RuntimeError):
    pass


def load_env(path: Path) -> dict[str, str]:
    """Read simple assignments without executing user-controlled shell content."""
    values = {}
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = ASSIGNMENT.fullmatch(line)
        if not match:
            raise MigrationError(f"Unsupported assignment syntax at {path}:{number}.")
        key, value = match.groups()
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise MigrationError(f"Unclosed quoted value at {path}:{number}.")
            value = value[1:-1]
        values[key] = value
    return values


def major_version(root: str) -> int:
    match = re.search(r"(?:^|[^0-9])V?(1[7-9]|[2-9][0-9])(?:$|[^0-9])", root)
    if not match:
        raise MigrationError("Cannot determine Odoo major version from ODOO_ROOT.")
    return int(match.group(1))


def toml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_scalar(item) for item in value) + "]"
    return json.dumps(str(value), ensure_ascii=False)


def dumps_toml(mapping: dict, prefix: str = "") -> str:
    lines: list[str] = []
    tables: list[tuple[str, dict]] = []
    for key, value in mapping.items():
        if isinstance(value, dict):
            tables.append((key, value))
        else:
            lines.append(f"{key} = {toml_scalar(value)}")
    for key, value in tables:
        header = f"{prefix}.{key}" if prefix else key
        nested: list[tuple[str, dict]] = []
        scalars: list[tuple[str, object]] = []
        for child_key, child_value in value.items():
            if isinstance(child_value, dict):
                nested.append((child_key, child_value))
            else:
                scalars.append((child_key, child_value))
        if scalars or not nested:
            if lines:
                lines.append("")
            lines.append(f"[{header}]")
            for child_key, child_value in scalars:
                lines.append(f"{child_key} = {toml_scalar(child_value)}")
        for child_key, child_value in nested:
            lines.append("")
            child_header = f"{header}.{child_key}"
            lines.append(f"[{child_header}]")
            for nested_key, nested_value in child_value.items():
                if isinstance(nested_value, dict):
                    raise MigrationError(f"Unsupported nested table {child_header}.{nested_key}")
                lines.append(f"{nested_key} = {toml_scalar(nested_value)}")
    return "\n".join(lines) + "\n"


def config_from(values: dict[str, str], repo: Path) -> dict:
    root, database = values.get("ODOO_ROOT"), values.get("DB_NAME")
    if not root or not database:
        raise MigrationError("Legacy runtime must define ODOO_ROOT and DB_NAME.")
    major = major_version(root)
    http = int(values.get("HTTP_PORT", "8096"))
    test_http = int(values.get("TEST_HTTP_PORT", str(http + 1000)))
    test_gevent = int(values.get("TEST_GEVENT_PORT", str(test_http + 1)))
    test_start = int(values.get("TEST_PORT_RANGE_START", str(test_http)))
    test_end = int(values.get("TEST_PORT_RANGE_END", str(test_start + 101)))
    data_dir = values.get("ODOO_DATA_DIR", str(repo / ".odoo/data"))
    if "/utils/" in data_dir or data_dir.endswith("/utils"):
        data_dir = str(repo / ".odoo/data")
    config = {
        "version": 1, "project": {"name": repo.name},
        "odoo": {"root": root, "data_dir": data_dir},
        "database": {"name": database, "port": int(values.get("DB_PORT", "5432")),
                     "user": values.get("DB_USER", "odoo")},
        "ports": {"http": http, "test_http": test_http, "test_gevent": test_gevent,
                  "test_range_start": test_start, "test_range_end": test_end},
        "tags": {
            "develop": {"read": "allow", "create": "allow", "write": "allow", "unlink": "ask", "exec": "ask"},
            "production": {"read": "allow", "create": "ask", "write": "ask", "unlink": "ask", "exec": "ask"},
        },
        "targets": {"local": {"odoo_version": major,
                     "url": values.get("ODOO_LOCAL_URL", f"http://127.0.0.1:{http}"),
                     "database": values.get("ODOO_LOCAL_DB", database), "tags": ["develop"]}},
    }
    if values.get("PYTHON_PATH"):
        config["odoo"]["bin_path"] = values["PYTHON_PATH"]
    if values.get("DB_HOST"):
        config["database"]["host"] = values["DB_HOST"]
    if values.get("ODOO_REMOTE_URL") or values.get("ODOO_REMOTE_DB"):
        if not (values.get("ODOO_REMOTE_URL") and values.get("ODOO_REMOTE_DB")):
            raise MigrationError("Remote target requires both ODOO_REMOTE_URL and ODOO_REMOTE_DB.")
        config["targets"]["production"] = {
            "odoo_version": major, "url": values["ODOO_REMOTE_URL"],
            "database": values["ODOO_REMOTE_DB"], "tags": ["production"],
        }
    if major in (17, 18) and values.get("ODOO_DIRECT_USER"):
        config["targets"]["local"]["username"] = values["ODOO_DIRECT_USER"]
    return config


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate(config: Path, override: Path) -> None:
    result = subprocess.run(["python3", str(Path(__file__).with_name("config.py")), "json", str(config), str(override)],
                            text=True, capture_output=True)
    if result.returncode:
        raise MigrationError(result.stderr.strip() or "Generated configuration is invalid.")


def migrate(repo: Path, delete_legacy: bool) -> None:
    legacy = repo / "utils" / ".env"
    if not legacy.is_file():
        raise MigrationError(f"Retired runtime file not found: {legacy}")
    values = load_env(legacy)
    config = repo / ".odoo/config.toml"
    if config.exists():
        # The committed .odoo contract is authoritative; do not rewrite a
        # configured repository merely because its retired file differs.
        validate(config, repo / ".odoo/worktree.toml")
    else:
        generated = dumps_toml(config_from(values, repo))
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(generated)
    validate(config, repo / ".odoo/worktree.toml")

    secrets = repo / ".odoo/secrets.env"
    secret_values = {key: value for key, value in values.items() if key not in CONFIG_KEYS}
    for old, target in (("ODOO_LOCAL_API_KEY", "ODOO_DIRECT_LOCAL_API_KEY"),
                        ("ODOO_REMOTE_API_KEY", "ODOO_DIRECT_PRODUCTION_API_KEY"),
                        ("ODOO_DIRECT_API_KEY", "ODOO_DIRECT_LOCAL_API_KEY")):
        if values.get(old):
            secret_values[target] = values[old]
    rendered = "# Local credentials and integration settings. This file is ignored by Git.\n" + "".join(
        f"{key}={value}\n" for key, value in sorted(secret_values.items())
    )
    if not secrets.exists():
        write_private(secrets, rendered)
    if delete_legacy:
        legacy.unlink()
        for path in (repo / "utils/odoo.conf", repo / "utils/odoo.conf.local"):
            if path.is_file():
                path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("--delete-legacy", action="store_true")
    args = parser.parse_args()
    try:
        migrate(args.repo.resolve(), args.delete_legacy)
    except MigrationError as error:
        raise SystemExit(f"Migration stopped: {error}")


if __name__ == "__main__":
    main()
