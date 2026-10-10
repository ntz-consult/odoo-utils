# Odoo global commands

Every `odoo-*` command resolves the current Git repository root and reads its
shared runtime from `.odoo/`:

```text
.odoo/config.toml    committed runtime, targets, tags, and policies
.odoo/secrets.env    ignored database passwords and target API keys
.odoo/worktree.toml  optional ignored explicit database and port overrides
.odoo/dump.sql       ignored source used by odoo-fresh
.odoo/odoo.conf      ignored generated Odoo server configuration
```

Run `odoo-init-env` to create a new runtime. A linked worktree must receive an
explicit allocation:

```bash
odoo-init-env --worktree --db REPO_BRANCH --http-port 8201 --test-range-start 9700
```

The command symlinks `secrets.env` from the primary checkout. It records the
worktree database and ports in `.odoo/worktree.toml`; configuration never merges
from a parent repository.

## Model access

Use `odoo-direct targets` before choosing an unfamiliar target. Address every
target by its configured name:

```bash
odoo-direct local test
odoo-direct production search-read res.company "[]" "['name']"
odoo-direct upgrade write res.partner '[1]' "{'name': 'Example'}"
```

The target's tags in `.odoo/config.toml` decide the policy for `read`, `create`,
`write`, `unlink`, and `exec`. Valid values are `allow`, `ask`, and `deny`; the
strictest value wins. Target and tag names add no extra restrictions. `ask`
requires an unchanged preview followed by `--confirm`. Odoo 17 and 18 use
XML-RPC. Odoo 19 and newer use JSON-2. The command never falls back to another
transport or target.

Target API keys use the derived name `ODOO_DIRECT_<TARGET>_API_KEY` in
`.odoo/secrets.env`, replacing non-alphanumeric target-name characters with `_`.

## Runtime commands

```bash
odoo-run
odoo-test --test MODULE
odoo-install --update MODULE
odoo-fresh
odoo-sync --module MODULE
```

`odoo-run`, tests, installation, linting, sync, initialization, and refresh all
use the same `.odoo/config.toml`. `odoo-fresh` reads `.odoo/dump.sql` unless the
caller supplies `--dump`.
