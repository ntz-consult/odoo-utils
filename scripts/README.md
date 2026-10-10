# Global Odoo commands

Run commands from any directory inside a configured Git repository:

```bash
odoo-init-env
odoo-run
odoo-test --test MODULE
odoo-install --update MODULE
odoo-fresh
odoo-direct targets
odoo-direct local test
```

The shared layout is:

```text
.odoo/config.toml    committed project and target configuration
.odoo/secrets.env    ignored credentials
.odoo/worktree.toml  ignored explicit worktree database and ports
.odoo/dump.sql       ignored odoo-fresh source
.odoo/odoo.conf      ignored generated server configuration
```

Create a linked-worktree runtime with explicit ports:

```bash
odoo-init-env --worktree --db REPO_BRANCH --http-port 8201 --test-range-start 10000
```

Configure a declared target's API key with `odoo-direct-init TARGET`. Inspect
targets and their credential status with `odoo-direct targets`.

Run each command with `--help` for its complete options.
