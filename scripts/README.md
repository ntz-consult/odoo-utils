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

Refresh a local database from an Odoo.sh daily backup (no project data in this repo):

```bash
odoo_sh_refresh.py --config CONFIG.toml --check      # read-only preflight
odoo_sh_refresh.py --config CONFIG.toml --rehearse   # everything up to the swap; never swaps
odoo_sh_refresh.py --config CONFIG.toml              # full run
```

The config names the SSH source, the target database and checkout, the lock, the state
folder and the project SQL (see the docstring). A run never triggers an Odoo.sh backup,
never starts an Odoo server. At the swap it stops the live Odoo of the checkout, if one is running, and does not restart it.
