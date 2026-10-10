# Odoo utilities

Global `odoo-*` commands for running, testing, refreshing, and accessing Odoo
projects. Install the wrappers under `~/.local/share/odoo/bin` with
`scripts/install.sh`.

Every command resolves the current Git repository and reads `.odoo/config.toml`.
Credentials stay in ignored `.odoo/secrets.env`; linked worktrees use an explicit
ignored `.odoo/worktree.toml` allocation.

See [scripts/README.md](scripts/README.md) for runtime commands and
[direct/README.md](direct/README.md) for named Odoo targets.
