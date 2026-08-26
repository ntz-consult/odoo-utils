#!/usr/bin/env python3
"""Move credentials from legacy utils/.env into .odoo/secrets.env."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path


def load_legacy(path: Path) -> dict[str, str]:
    result = subprocess.run(
        ["bash", "-c", 'set -a; source "$1"; env -0', "migrate-secrets", str(path)],
        check=True,
        capture_output=True,
    )
    return {
        item.partition(b"=")[0].decode(): item.partition(b"=")[2].decode()
        for item in result.stdout.split(b"\0") if b"=" in item
    }


def target_variable(name: str) -> str:
    return "ODOO_DIRECT_" + re.sub(r"[^A-Za-z0-9]", "_", name).upper() + "_API_KEY"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("mapping", nargs="+", help="TARGET=LEGACY_VARIABLE")
    args = parser.parse_args()
    legacy = load_legacy(args.repo / "utils/.env")
    values: dict[str, str] = {}
    for name in ("DB_PASSWORD", "TEST_PASSWORD", "ODOO_LOCAL_WOO_API_KEY"):
        if legacy.get(name):
            values[name] = legacy[name]
    for mapping in args.mapping:
        target, separator, source = mapping.partition("=")
        if not separator or not legacy.get(source):
            raise SystemExit(f"Missing legacy credential mapping: {mapping}")
        values[target_variable(target)] = legacy[source]

    destination = args.repo / ".odoo/secrets.env"
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".secrets.", dir=destination.parent, text=True)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write("# Local credentials. This file is ignored by Git.\n")
            for name, value in values.items():
                stream.write(f"{name}={value}\n")
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    main()
