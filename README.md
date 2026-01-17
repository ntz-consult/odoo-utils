# odoo-utils

A collection of small utilities for working with Odoo projects.

This repository contains two main subprojects:

- odoo-project-sync: a CLI-driven toolkit to extract Odoo Studio customizations, generate module-style source files, map features to user stories, and synchronize these with a development Odoo instance.
- odoo-direct: a minimal, lightweight JSON-RPC client for direct access to Odoo models (convenience wrapper around the Odoo JSON-RPC API).

This top-level README gives a quick overview and quickstart. Each subproject contains its own README with more detailed documentation and examples.

Contents
- odoo-project-sync/  — Full-featured sync and extraction toolkit (CLI)
- odoo-direct/        — Lightweight JSON-RPC client module

Quickstart (developer)
1. Clone this repository:

   git clone <repo-url> && cd odoo-utils

2. Review the subproject README you want to use:

   - odoo-project-sync: `odoo-project-sync/README.md`
   - odoo-direct: `odoo-direct/README.md`

3. Create a Python virtual environment and install dependencies for the subproject you need. Example for odoo-project-sync:

   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r odoo-project-sync/requirements.txt

   Or for the lightweight client:

   pip install -r odoo-direct/requirements.txt

odoo-project-sync (summary)
- Purpose: Extract Odoo Studio customizations (fields, views, server actions, automations, reports), generate module structure, create feature → user story maps, optionally enrich stories with AI, estimate effort, and sync with an Odoo development instance.
- Entry point: `odoo-project-sync/shared/python/cli.py` (the installer `odoo-project-sync/install.sh` creates a project-local wrapper at `./.odoo-sync/cli.py`).
- Typical workflow:
  - `./.odoo-sync/cli.py init`  — interactive setup
  - `./.odoo-sync/cli.py extract --execute`  — extract Studio customizations
  - `./.odoo-sync/cli.py generate-modules --execute`  — create module files
  - `./.odoo-sync/cli.py generate-feature-user-story-map --execute`  — build feature/user-story map
  - `./.odoo-sync/cli.py sync --execute`  — sync with Odoo tasks (bidirectional)
- See `odoo-project-sync/README.md` and `odoo-project-sync/Odoo_Sync_HowTo.md` for detailed guides and examples.

odoo-direct (summary)
- Purpose: Minimal API client that loads configuration from `config.json` and exposes simple methods: `search`, `search_read`, `read`, `create`, `write`, `unlink`, `search_count`, and `execute_kw`.
- Example usage is in `odoo-direct/README.md` and `odoo-direct/example.py`.
- Main module: `odoo-direct/odoo_direct.py` (provides a global `odoo` instance for convenience).

Configuration
- odoo-project-sync stores project config in `.odoo-sync/odoo-instances.json` and `.odoo-sync/.env` (API keys). Use the `init` command or follow `odoo-project-sync/README.md`.
- odoo-direct uses `odoo-direct/config.json` (copy `config.json.example` to `config.json`). Do not commit actual credentials.

Testing
- The `odoo-project-sync` subproject includes a test suite. With a venv active run:

   pip install -r odoo-project-sync/requirements.txt
   pytest -q

Contributing
- Please keep changes focused to the appropriate subproject and include tests for new functionality. Each subproject maintains its own README and tests.

License
- See individual subproject files for license details. If not present, please add a LICENSE file in the subproject you intend to use.

More documentation
- odoo-project-sync/README.md — detailed documentation and workflows
- odoo-direct/README.md — API reference and examples

If you want, I can:
- update or expand the `odoo-project-sync` README with additional quick examples or a condensed CLI reference;
- add a short CONTRIBUTING.md or LICENSE at repository root.
