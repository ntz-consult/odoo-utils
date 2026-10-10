#!/usr/bin/env python3
"""Deterministic JSON-2 access to explicitly configured Odoo targets."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from odoo_direct import (
    OdooAuthError,
    OdooConfigError,
    OdooDirect,
    OdooError,
    OdooXmlRpc,
    parse_major_version,
)


MAX_ROWS = 50
MAX_CELL = 100
COMMANDS = frozenset(
    {"test", "search", "read", "search-read", "count", "fields", "exec", "create", "write", "unlink"}
)
READ_COMMANDS = frozenset({"test", "search", "read", "search-read", "count", "fields"})
POLICY_VALUES = {"allow": 0, "ask": 1, "deny": 2}
POLICY_KEYS = frozenset({"read", "create", "write", "unlink", "exec"})
RULE_KEYS = POLICY_KEYS | {"fields", "methods"}
FIELD_OPERATIONS = frozenset({"create", "write"})
# exec of an ORM CRUD method must also pass the policy of that operation.
EXEC_ALIASES = {
    "create": "create", "copy": "create",
    "write": "write", "web_save": "write",
    "unlink": "unlink",
    "read": "read", "web_read": "read", "search": "read", "search_read": "read",
    "web_search_read": "read", "search_count": "read", "fields_get": "read",
}
AUDIT_LOG = "odoo-direct-audit.log"
TARGET_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class TargetError(RuntimeError):
    """The requested target or command is incomplete or unsafe."""


def parse_literal(raw: str, label: str, expected_type):
    if raw.startswith("@"):
        payload_path = Path(raw[1:])
        try:
            raw = payload_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise TargetError(f"Unable to read {label} payload file.") from exc
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as exc:
        raise TargetError(f"Invalid {label}: provide a Python literal.") from exc
    if not isinstance(value, expected_type):
        raise TargetError(f"Invalid {label}: expected {expected_type.__name__}.")
    return value


def resolve_git_root() -> Path:
    configured = os.environ.get("ODOO_DIRECT_PROJECT_ROOT")
    if configured:
        return Path(configured).resolve()
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True, stderr=subprocess.DEVNULL
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise TargetError("odoo-direct must run inside a Git repository.") from exc
    return Path(output.strip()).resolve()


def _config_loader():
    spec = importlib.util.spec_from_file_location(
        "odoo_runtime_config", Path(__file__).with_name("config.py")
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def load_project_config() -> dict:
    root = resolve_git_root()
    config_path = Path(os.environ.get("ODOO_DIRECT_CONFIG_FILE", root / ".odoo/config.toml"))
    worktree_path = Path(os.environ.get("ODOO_DIRECT_WORKTREE_FILE", root / ".odoo/worktree.toml"))
    loader = _config_loader()
    try:
        return loader.load_merged_config(config_path, worktree_path)
    except loader.ConfigError as exc:
        raise TargetError(str(exc)) from exc


def secret_variable(target_name: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]", "_", target_name).upper()
    return f"ODOO_DIRECT_{token}_API_KEY"


def _policy(value, where: str) -> str:
    if value not in POLICY_VALUES:
        raise TargetError(f"{where} has invalid policy {value!r}")
    return value


def validate_model_rules(tag_name: str, tag: dict) -> dict:
    """Validate the optional ``models`` table of one tag and return it."""
    models = tag.get("models", {})
    if not isinstance(models, dict):
        raise TargetError(f"tags.{tag_name}.models must be a table")
    for model, rule in models.items():
        where = f'tags.{tag_name}.models."{model}"'
        if not isinstance(rule, dict):
            raise TargetError(f"{where} must be a table")
        unknown = sorted(set(rule) - RULE_KEYS)
        if unknown:
            raise TargetError(f"{where} has unknown keys: {', '.join(unknown)}")
        for key in sorted(POLICY_KEYS & rule.keys()):
            _policy(rule[key], f"{where}.{key}")
        for section in ("fields", "methods"):
            entries = rule.get(section, {})
            if not isinstance(entries, dict):
                raise TargetError(f"{where}.{section} must be a table")
            for name, value in entries.items():
                _policy(value, f"{where}.{section}.{name}")
    return models


def tag_rule(tag_name: str, tag: dict, operation: str, model=None, method=None, fields=None):
    """Return ``(policy, source)`` for one tag; the most specific matching rule wins."""
    policy, source = tag[operation], f"tags.{tag_name}.{operation}"
    models = validate_model_rules(tag_name, tag)
    rule = models.get(model) if model else None
    if rule is None:
        return policy, source
    base = f'tags.{tag_name}.models."{model}"'
    if operation in rule:
        policy, source = rule[operation], f"{base}.{operation}"
    if operation == "exec" and method in rule.get("methods", {}):
        return rule["methods"][method], f"{base}.methods.{method}"
    field_rules = rule.get("fields", {})
    if operation in FIELD_OPERATIONS and fields and field_rules:
        candidates = [
            (field_rules[name], f"{base}.fields.{name}") if name in field_rules else (policy, source)
            for name in fields
        ]
        policy, source = max(candidates, key=lambda item: POLICY_VALUES[item[0]])
    return policy, source


def resolve_rule(config: dict, target_name: str, operation: str, model=None, method=None, fields=None):
    """Return ``(policy, source)``: most specific rule per tag, strictest across tags."""
    target = config["targets"][target_name]
    tag_names = target.get("tags")
    if not isinstance(tag_names, list) or not tag_names:
        raise TargetError(f"Target {target_name!r} must declare at least one tag.")
    results = []
    for tag_name in tag_names:
        tag = config.get("tags", {}).get(tag_name)
        if not isinstance(tag, dict):
            raise TargetError(f"Target {target_name!r} references unknown tag {tag_name!r}.")
        missing = sorted(POLICY_KEYS - tag.keys())
        if missing:
            raise TargetError(f"Tag {tag_name!r} is missing policies: {', '.join(missing)}")
        invalid = {key: tag[key] for key in POLICY_KEYS if tag[key] not in POLICY_VALUES}
        if invalid:
            raise TargetError(f"Tag {tag_name!r} has invalid policies: {invalid}")
        results.append(tag_rule(tag_name, tag, operation, model, method, fields))
    if operation == "exec" and method in EXEC_ALIASES:
        aliased, via = resolve_rule(config, target_name, EXEC_ALIASES[method], model)
        results.append((aliased, f"{via} (via exec {method})"))
    return max(results, key=lambda item: POLICY_VALUES[item[0]])


def resolve_policy(config: dict, target_name: str, operation: str, **scope) -> str:
    return resolve_rule(config, target_name, operation, **scope)[0]


def has_relational_commands(values: dict) -> bool:
    """True when any value is an x2many command list such as ``[(2, 5)]``."""
    return any(
        isinstance(value, (list, tuple)) and any(isinstance(item, (list, tuple)) for item in value)
        for value in values.values()
    )


def scoped_policy(config: dict, args: argparse.Namespace):
    """Resolve the policy for a parsed command. Returns ``(policy, source, fields)``."""
    values = parse_literal(args.values, "values", dict) if args.command in FIELD_OPERATIONS else None
    fields = sorted(values) if values else None
    policy, source = resolve_rule(
        config, args.target, args.operation,
        model=getattr(args, "model", None), method=getattr(args, "method", None), fields=fields,
    )
    if policy == "allow" and ".models." in source and values and has_relational_commands(values):
        policy, source = "ask", f"{source} (relational commands need approval)"
    return policy, source, fields


def audit(args, label: str, target_config: dict, policy: str, source: str, fields, result) -> None:
    """Append one JSON line per executed change. Values are never logged."""
    if args.operation == "read" or (isinstance(result, dict) and result.get("status") == "preview"):
        return
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target": label,
        "database": target_config["database"],
        "operation": args.operation,
        "model": getattr(args, "model", None),
        "method": getattr(args, "method", None),
        "ids": getattr(args, "ids", None),
        "fields": fields,
        "policy": policy,
        "rule": source,
        "confirmed": bool(getattr(args, "confirm", False)),
        "result_id": result.get("result") if args.operation == "create" and isinstance(result, dict) else None,
    }
    try:
        path = resolve_git_root() / ".odoo" / AUDIT_LOG
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
    except (OSError, TargetError) as exc:
        print(f"Warning: audit log not written: {exc}", file=sys.stderr)


def target_client(config: dict, target_name: str):
    if not TARGET_NAME_RE.fullmatch(target_name):
        raise TargetError(f"Invalid target name: {target_name!r}")
    targets = config.get("targets")
    if not isinstance(targets, dict) or target_name not in targets:
        declared = ", ".join(sorted(targets or {})) or "none"
        raise TargetError(f"Unknown target {target_name!r}. Declared targets: {declared}")
    target = targets[target_name]
    if not isinstance(target, dict):
        raise TargetError(f"Target {target_name!r} must be a mapping.")
    try:
        version = parse_major_version(target.get("odoo_version"))
    except ValueError as exc:
        raise TargetError(
            f"Target {target_name!r} must declare odoo_version as a major number "
            "or version string (for example 19 or saas~19.3.1.3)."
        ) from exc
    if version < 17:
        raise TargetError(f"Target {target_name!r} runs unsupported Odoo {version}; minimum is 17.")
    variable = secret_variable(target_name)
    resolved = {
        "url": target.get("url", ""),
        "database": target.get("database", ""),
        "api_key": os.environ.get(variable, ""),
        "odoo_version": version,
    }
    if version < 19:
        resolved["username"] = target.get("username", "")
    missing = [key for key, value in resolved.items() if not value]
    if missing:
        detail = variable if "api_key" in missing else ", ".join(missing)
        raise TargetError(f"Target {target_name!r} is missing configuration: {detail}")
    client = OdooDirect(config=resolved) if version >= 19 else OdooXmlRpc(config=resolved)
    return client, resolved, target_name


def print_targets(config: dict, as_json: bool) -> None:
    targets = config.get("targets", {})
    rows = []
    for name, target in sorted(targets.items()):
        rows.append({
            "target": name,
            "database": target.get("database", ""),
            "endpoint": urlsplit(target.get("url", "")).netloc,
            "tags": ", ".join(target.get("tags", [])),
            "odoo": target.get("odoo_version", ""),
            "credentials": "configured" if os.environ.get(secret_variable(name)) else "missing",
        })
    if as_json:
        print(json.dumps(rows, sort_keys=True))
    else:
        print_table(rows)


def clean_cell(value) -> str:
    if isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], int):
        rendered = f"{value[1]} ({value[0]})"
    else:
        rendered = str(value if value is not None else "")
    rendered = rendered.replace("|", "\\|").replace("\n", " ")
    return rendered if len(rendered) <= MAX_CELL else rendered[: MAX_CELL - 3] + "..."


def print_table(rows: list[dict]) -> None:
    if not rows:
        print("No records found.")
        return
    shown = rows[:MAX_ROWS]
    columns: list[str] = []
    for row in shown:
        columns.extend(key for key in row if key not in columns)
    print("| " + " | ".join(columns) + " |")
    print("| " + " | ".join("---" for _ in columns) + " |")
    for row in shown:
        print("| " + " | ".join(clean_cell(row.get(key, "")) for key in columns) + " |")


def render_result(command: str, result) -> None:
    if command == "fields" and isinstance(result, dict):
        print_table([
            {
                "field": name,
                "type": details.get("type", ""),
                "required": bool(details.get("required")),
                "readonly": bool(details.get("readonly")),
                "label": details.get("string", ""),
            }
            for name, details in sorted(result.items())
        ])
    elif command == "search" and isinstance(result, list):
        print_table([{"id": record_id} for record_id in result])
    elif isinstance(result, list) and (not result or isinstance(result[0], dict)):
        print_table(result)
    elif isinstance(result, dict):
        print_table([result])
    elif result is not None:
        print(result)


def execute_command(client: OdooDirect, args: argparse.Namespace, policy: str = "ask"):
    approved = policy == "allow" or getattr(args, "confirm", False)
    if policy == "deny":
        raise TargetError(f"The selected target denies {args.operation} operations.")
    if args.operation == "read" and not approved:
        return {"status": "approval-required", "operation": "read", "command": args.command}
    if args.command == "test":
        actual_version = client.server_major_version()
        if actual_version != client.odoo_version:
            raise TargetError(
                f"Target declares Odoo {client.odoo_version}, but the server reports Odoo {actual_version}."
            )
        context = client.context_get()
        count = client.search_count("res.partner", [])
        return {
            "status": "connected", "transport": client.transport,
            "odoo version": actual_version, "uid": context.get("uid"), "res.partner count": count,
        }
    if args.command == "search":
        return client.search(args.model, parse_literal(args.domain, "domain", list), limit=args.limit)
    if args.command == "read":
        fields = parse_literal(args.fields, "fields", list) if args.fields else None
        return client.read(args.model, parse_literal(args.ids, "IDs", list), fields)
    if args.command == "search-read":
        fields = parse_literal(args.fields, "fields", list) if args.fields else None
        return client.search_read(
            args.model, parse_literal(args.domain, "domain", list), fields, limit=args.limit
        )
    if args.command == "count":
        return client.search_count(args.model, parse_literal(args.domain, "domain", list))
    if args.command == "fields":
        return client.call(args.model, "fields_get")

    if args.command == "create":
        values = parse_literal(args.values, "values", dict)
        preview = {"status": "preview", "operation": "create", "model": args.model, "values": values}
        if not args.json:
            print_table([{"field": key, "new": value} for key, value in values.items()])
        if not approved:
            if not args.json:
                print("No changes made. Re-run with --confirm only after explicit user approval.")
            return preview
        record_id = client.create(args.model, values)
        return {"result": record_id, "readback": client.read(args.model, [record_id])}

    ids = parse_literal(args.ids, "IDs", list)
    if args.command == "write":
        values = parse_literal(args.values, "values", dict)
        records = client.read(args.model, ids, list(values))
        preview = {
            "status": "preview", "operation": "write", "model": args.model,
            "ids": ids, "current": records, "values": values,
        }
        if not args.json:
            print_table([
                {"id": record["id"], "field": field, "current": record.get(field), "new": value}
                for record in records
                for field, value in values.items()
            ])
        if not approved:
            if not args.json:
                print("No changes made. Re-run with --confirm only after explicit user approval.")
            return preview
        result = client.write(args.model, ids, values)
        return {"result": result, "readback": client.read(args.model, ids, list(values))}
    if args.command == "unlink":
        records = client.read(args.model, ids, ["display_name"])
        preview = {
            "status": "preview", "operation": "unlink", "model": args.model,
            "ids": ids, "current": records,
        }
        if not args.json:
            print_table(records)
        if not approved:
            if not args.json:
                print("No changes made. Re-run with --confirm only after explicit user approval.")
            return preview
        return client.unlink(args.model, ids)

    kwargs = parse_literal(args.kwargs, "keyword arguments", dict)
    context = parse_literal(args.context, "context", dict) if args.context else None
    preview = {
        "status": "preview", "operation": "exec", "model": args.model,
        "method": args.method, "ids": ids, "context": context or {}, "kwargs": kwargs,
    }
    if not args.json:
        print_table([{
        "model": args.model,
        "method": args.method,
        "ids": ids,
        "context": context or {},
        "kwargs": kwargs,
        }])
    if not approved:
        if not args.json:
            print("No method called. Re-run with --confirm only after explicit user approval.")
        return preview
    return client.call(args.model, args.method, ids=ids or None, context=context, **kwargs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odoo-direct",
        description="Deterministic Odoo model access to a named target from .odoo/config.toml.",
    )
    parser.add_argument("--json", action="store_true", help="Emit one machine-readable JSON object")
    parser.add_argument("target", help="Target name declared in .odoo/config.toml")
    subparsers = parser.add_subparsers(dest="command", required=True)
    def add_read_approval(command_parser):
        command_parser.add_argument("--confirm", action="store_true")
        command_parser.set_defaults(operation="read")

    test = subparsers.add_parser("test", help="Verify the selected connection and Odoo version")
    add_read_approval(test)
    search = subparsers.add_parser("search")
    search.add_argument("model")
    search.add_argument("domain")
    search.add_argument("--limit", type=int)
    add_read_approval(search)
    read = subparsers.add_parser("read")
    read.add_argument("model")
    read.add_argument("ids")
    read.add_argument("fields", nargs="?")
    add_read_approval(read)
    search_read = subparsers.add_parser("search-read")
    search_read.add_argument("model")
    search_read.add_argument("domain")
    search_read.add_argument("fields", nargs="?")
    search_read.add_argument("--limit", type=int)
    add_read_approval(search_read)
    count = subparsers.add_parser("count")
    count.add_argument("model")
    count.add_argument("domain", nargs="?", default="[]")
    add_read_approval(count)
    fields = subparsers.add_parser("fields")
    fields.add_argument("model")
    add_read_approval(fields)
    execute = subparsers.add_parser("exec")
    execute.add_argument("model")
    execute.add_argument("method")
    execute.add_argument("--ids", default="[]")
    execute.add_argument("--context")
    execute.add_argument("--kwargs", default="{}")
    execute.add_argument("--confirm", action="store_true")
    execute.set_defaults(operation="exec")
    create = subparsers.add_parser("create")
    create.add_argument("model")
    create.add_argument("values")
    create.add_argument("--confirm", action="store_true")
    create.set_defaults(operation="create")
    write = subparsers.add_parser("write")
    write.add_argument("model")
    write.add_argument("ids")
    write.add_argument("values")
    write.add_argument("--confirm", action="store_true")
    write.set_defaults(operation="write")
    unlink = subparsers.add_parser("unlink")
    unlink.add_argument("model")
    unlink.add_argument("ids")
    unlink.add_argument("--confirm", action="store_true")
    unlink.set_defaults(operation="unlink")
    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw in (["-h"], ["--help"]):
        build_parser().parse_args(raw)
        return 0
    config = load_project_config()
    if raw and raw[0] == "targets":
        print_targets(config, "--json" in raw[1:])
        return 0
    args = build_parser().parse_args(raw)
    client, target_config, label = target_client(config, args.target)
    policy, source, fields = scoped_policy(config, args)
    endpoint = urlsplit(target_config["url"]).netloc or "invalid-host"
    if not args.json:
        print(f"Target: {label}")
        print(f"Database: {target_config['database']}")
        print(f"Endpoint: {endpoint}", flush=True)
        print(f"Policy: {args.operation}={policy} ({source})", flush=True)
    result = execute_command(client, args, policy)
    audit(args, label, target_config, policy, source, fields, result)
    if args.json:
        print(json.dumps({
            "target": label,
            "database": target_config["database"],
            "endpoint": endpoint,
            "policy": policy,
            "result": result,
            "rule": source,
        }, sort_keys=True))
    else:
        render_result(args.command, result)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (TargetError, OdooAuthError, OdooConfigError, OdooError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
