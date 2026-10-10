#!/usr/bin/env python3
"""Load .odoo/config.toml without Ruby or a YAML library."""

from __future__ import annotations

import json
import shlex
import sys
import tomllib
from pathlib import Path
from typing import Any

SHELL_MAPPING = {
    "PROJECT_NAME": ("project", "name"),
    "ODOO_ROOT": ("odoo", "root"),
    "ODOO_DATA_DIR": ("odoo", "data_dir"),
    "ODOO_HTTP_INTERFACE": ("odoo", "http_interface"),
    "ODOO_LIST_DB": ("odoo", "list_db"),
    "ODOO_PROXY_MODE": ("odoo", "proxy_mode"),
    "ODOO_LOG_LEVEL": ("odoo", "log_level"),
    "BIN_PATH": ("odoo", "bin_path"),
    "ODOO_SYNC_SCRIPT": ("odoo", "sync_script"),
    "DB_NAME": ("database", "name"),
    "DB_HOST": ("database", "host"),
    "DB_PORT": ("database", "port"),
    "DB_USER": ("database", "user"),
    "HTTP_PORT": ("ports", "http"),
    "TEST_HTTP_PORT": ("ports", "test_http"),
    "TEST_GEVENT_PORT": ("ports", "test_gevent"),
    "TEST_PORT_RANGE_START": ("ports", "test_range_start"),
    "TEST_PORT_RANGE_END": ("ports", "test_range_end"),
}


class ConfigError(Exception):
    pass


def fail_config(message: str) -> None:
    raise ConfigError(message)


def load_toml(path: Path, *, required: bool) -> dict[str, Any]:
    if not path.is_file():
        if required:
            fail_config(f"Odoo configuration not found: {path}")
        return {}
    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        fail_config(f"invalid TOML in {path}: {error}")
    if value is None:
        value = {}
    if not isinstance(value, dict):
        fail_config(f"{path} must contain a TOML table")
    return value


def deep_merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, new_value in right.items():
        old_value = merged.get(key)
        if isinstance(old_value, dict) and isinstance(new_value, dict):
            merged[key] = deep_merge(old_value, new_value)
        else:
            merged[key] = new_value
    return merged


def dig_value(config: dict[str, Any], *path: str) -> Any:
    value: Any = config
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def load_merged_config(config_path: Path, override_path: Path | None = None) -> dict[str, Any]:
    yaml_path = config_path.with_name("config.yaml")
    if not config_path.is_file() and yaml_path.is_file():
        fail_config(
            f"found {yaml_path}; rename it to {config_path.name}. "
            "Odoo commands now read TOML, not YAML."
        )
    config = load_toml(config_path, required=True)
    if override_path is not None:
        config = deep_merge(config, load_toml(override_path, required=False))
    if config.get("version") != 1:
        fail_config("config version must be 1")
    return config


def shell_exports(config: dict[str, Any]) -> str:
    lines = []
    for name, path in SHELL_MAPPING.items():
        value = dig_value(config, *path)
        if value is None:
            continue
        lines.append(f"export {name}={shlex.quote(str(value))}")
    return "\n".join(lines) + ("\n" if lines else "")


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[1] not in {"shell", "json"}:
        print(
            "Error: usage: config.py shell|json CONFIG [WORKTREE_OVERRIDE]",
            file=sys.stderr,
        )
        return 1
    command, config_path = argv[1], Path(argv[2])
    override = Path(argv[3]) if len(argv) > 3 else None
    try:
        config = load_merged_config(config_path, override)
    except ConfigError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    if command == "json":
        json.dump(config, sys.stdout, default=str)
        sys.stdout.write("\n")
        return 0
    sys.stdout.write(shell_exports(config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
