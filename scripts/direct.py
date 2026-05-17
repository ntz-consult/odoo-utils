#!/usr/bin/env python3
"""
odoo-direct CLI — Minimal wrapper around OdooDirect for AI agents.

Usage:
    odoo-direct --test    # Verify connection using .env credentials
"""

import argparse
import os
import sys

# direct/ is on PYTHONPATH via direct.sh
try:
    from odoo_direct import OdooDirect, OdooError, OdooAuthError
except ImportError as e:
    print(f"Error: cannot import odoo_direct: {e}", file=sys.stderr)
    sys.exit(1)


def build_config_from_env():
    """Build config dict from environment variables."""
    return {
        "url": os.environ.get("ODOO_DIRECT_URL", ""),
        "database": os.environ.get("ODOO_DIRECT_DB", ""),
        "username": os.environ.get("ODOO_DIRECT_USER", ""),
        "api_key": os.environ.get("ODOO_DIRECT_API_KEY", ""),
    }


def cmd_test():
    """Test connection and print basic info."""
    config = build_config_from_env()

    env_names = {
        'url': 'ODOO_DIRECT_URL',
        'database': 'ODOO_DIRECT_DB',
        'username': 'ODOO_DIRECT_USER',
        'api_key': 'ODOO_DIRECT_API_KEY',
    }
    missing = [k for k, v in config.items() if not v]
    if missing:
        print("Error: Missing environment variables:", file=sys.stderr)
        for key in missing:
            print(f"  {env_names[key]}", file=sys.stderr)
        print("\nRun 'odoo-direct-init' to configure credentials.", file=sys.stderr)
        sys.exit(1)

    try:
        odoo = OdooDirect(config=config)
    except OdooError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        # Trigger authentication
        uid = odoo.uid
    except OdooAuthError as e:
        print(f"Authentication failed: {e}", file=sys.stderr)
        sys.exit(1)
    except OdooError as e:
        print(f"Connection error: {e}", file=sys.stderr)
        sys.exit(1)

    print("Connection successful!")
    print(f"  URL      : {config['url']}")
    print(f"  Database : {config['database']}")
    print(f"  User     : {config['username']}")
    print(f"  UID      : {uid}")

    # Try a lightweight RPC call to confirm full functionality
    try:
        version = odoo.execute_kw("res.partner", "search_count", [[]])
        print(f"  res.partner count: {version}")
    except OdooError as e:
        print(f"  Warning: RPC test call failed: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="odoo-direct — AI agent tool for Odoo JSON-RPC access"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test connection using credentials from .env",
    )
    args = parser.parse_args()

    if args.test:
        cmd_test()
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
