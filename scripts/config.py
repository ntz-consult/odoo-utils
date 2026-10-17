#!/usr/bin/env python3
"""Load .odoo/config.toml without Ruby or a YAML library."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
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
    "GEVENT_PORT": ("ports", "gevent"),
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


def primary_worktree(root: Path) -> Path | None:
    """The first checkout Git reports. That is the primary worktree."""
    try:
        output = subprocess.check_output(
            ["git", "-C", str(root), "worktree", "list", "--porcelain"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in output.splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree "):])
    return None


def uses_shared_odoo(root: Path) -> bool:
    """True when this linked worktree's .odoo is a symlink to the primary checkout's .odoo."""
    odoo = root / ".odoo"
    if not odoo.is_symlink():
        return False
    primary = primary_worktree(root)
    if primary is None:
        return False
    try:
        if root.resolve() == primary.resolve():
            return False
        return odoo.resolve() == (primary / ".odoo").resolve()
    except OSError:
        return False


def shared_worktree_database(root: Path) -> str | None:
    """Database for a worktree that shares the primary .odoo.

    The folder ``<primary>-<slug>`` uses ``<primary>_<slug>``, with every run of
    non-letters folded into one underscore. The same spelling is what
    ``tools/create_worktree.py`` clones. A folder whose name does not follow that
    pattern has no private database name.
    """
    if not uses_shared_odoo(root):
        return None
    primary = primary_worktree(root)
    if primary is None:
        return None
    prefix = primary.resolve().name + "-"
    folder = root.resolve().name
    if not folder.startswith(prefix):
        return None
    slug = folder[len(prefix):]
    normalized = re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_")
    if not normalized:
        return None
    database = f"{primary.resolve().name}_{normalized}"
    if len(database) > 63:
        return None
    return database


def apply_shared_worktree_database(config: dict[str, Any], root: Path) -> dict[str, Any]:
    """Select the worktree's own database when .odoo is the primary folder."""
    database = shared_worktree_database(root)
    if not database:
        return config
    merged = deep_merge(config, {"database": {"name": database}})
    local = (merged.get("targets") or {}).get("local")
    if isinstance(local, dict):
        local["database"] = database
    return merged


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[1] == "uses-shared-odoo":
        return 0 if uses_shared_odoo(Path(argv[2])) else 1
    if len(argv) >= 3 and argv[1] == "shared-db":
        root = Path(argv[2])
        if not uses_shared_odoo(root):
            return 0
        database = shared_worktree_database(root)
        if not database:
            print(
                f"Error: {root} points .odoo at the primary checkout, but its folder "
                "name does not name a private database.",
                file=sys.stderr,
            )
            return 1
        print(database)
        return 0
    if len(argv) < 3 or argv[1] not in {"shell", "json"}:
        print(
            "Error: usage: config.py shell|json CONFIG [WORKTREE_OVERRIDE] [ROOT]",
            file=sys.stderr,
        )
        return 1
    command, config_path = argv[1], Path(argv[2])
    override = Path(argv[3]) if len(argv) > 3 else None
    root = Path(argv[4]) if len(argv) > 4 else None
    try:
        config = load_merged_config(config_path, override)
        if root is not None and uses_shared_odoo(root) and shared_worktree_database(root) is None:
            fail_config(
                f"{root} points .odoo at the primary checkout, but its folder "
                "name does not name a private database."
            )
        if root is not None:
            config = apply_shared_worktree_database(config, root)
    except ConfigError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    if command == "json":
        json.dump(config, sys.stdout, default=str)
        sys.stdout.write("\n")
        return 0
    text = shell_exports(config)
    if root is not None and uses_shared_odoo(root):
        text += "export ODOO_SHARED_DATABASE=1\n"
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
