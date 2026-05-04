# Run Scripts

Helper scripts for running, testing, and managing an Odoo project environment.

Scripts are installed globally and run from any project directory that has a `run-scrips/` directory with `.env` and `odoo.conf`.

## Quick Start

```bash
# 1. Generate .env and odoo.conf (run once, or whenever paths change)
odoo-init-env

# 2. Start the Odoo server
odoo-run

# 3. Run tests
odoo-test --test mymodule
```

## Available Commands

| Command | Script | Purpose |
|---------|--------|---------|
| `odoo-init-env` | `init_env.sh` | Bootstrap `.env` and `odoo.conf` from template. Use `--force` to overwrite (backs up to `.bak`), `--venv-create` to build a Python venv. |
| `odoo-run` | `run.sh` | Start the Odoo server. Pass `--log` for file logging or `--conf <file>` for a custom config. |
| `odoo-test` | `test.sh` | Run Python or JS unit tests. Supports `--test <module>`, `--testall`, `--test-js`, `--list`, etc. |
| `odoo-init` | `init.sh` | Drop and recreate the database, then initialize with `-i base`. |
| `odoo-install` | `install.sh` | Install, update, or uninstall modules. Use `--list` to see statuses, `--all` to install everything. |
| `odoo-reset-db` | `reset_db.sh` | Reset the database from an SQL dump. Use `--update` to also sync Odoo source and refresh the dump. |
| `odoo-fresh` | `fresh.sh` | Quick database refresh from dump. |
| `odoo-cloc` | `cloc.sh` | Count lines of code for all project modules via `odoo-bin cloc`. |
| `odoo-lint` | `python-lint.sh` | Run ruff, vulture, and radon on project modules. Use `--fix` to auto-fix. |
| `odoo-sync` | `sync.sh` | Compare DB records against XML data files (preview/update). |

## Configuration

- **`.env`** — environment variables (paths, DB name, ports). Edit directly or regenerate via `init_env.sh`.
- **`odoo.conf`** — generated from `odoo.conf.template` by `init_env.sh`. **Do not edit directly**; it will be overwritten.
- **`common.sh`** — shared library sourced by all bash scripts. Loads `.env`, validates vars, and sets `PROJECT_ROOT` automatically.

## Environment Variables

| Var | Description |
|-----|-------------|
| `ODOO_ROOT` | Path to Odoo source |
| `PYTHON_PATH` | Path to venv `bin/` directory |
| `PROJECT_NAME` | Project name (default DB name prefix) |
| `DB_NAME` | Database name (usually `${PROJECT_NAME}`) |
| `HTTP_PORT` | Odoo HTTP port |
| `ODOO_SYNC_SCRIPT` | Optional path to a script that syncs/refreshes the Odoo source tree |
| `INIT_MODULES` | Optional comma-separated modules for `init.sh` (default: `base`) |

All scripts resolve paths relative to the repo root, so the project can be moved without changing `.env`.
