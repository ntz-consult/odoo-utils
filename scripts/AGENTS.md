# Odoo global commands

Every `odoo-*` command resolves the current Git repository root and reads its
shared runtime from `.odoo/`:

```text
.odoo/config.yaml    committed runtime, targets, tags, and policies
.odoo/secrets.env    ignored database passwords and target API keys
.odoo/worktree.yaml  optional ignored explicit database and port overrides
.odoo/dump.sql       ignored source used by odoo-fresh
.odoo/odoo.conf      ignored generated Odoo server configuration
```

Run `odoo-init-env` to create a new runtime. A linked worktree must receive an
explicit allocation:

```bash
odoo-init-env --worktree --db REPO_BRANCH --http-port 8201 --test-range-start 9700
```

The command symlinks `secrets.env` from the primary checkout. It records the
worktree database and ports in `.odoo/worktree.yaml`; configuration never merges
from a parent repository.

## Model access

Use `odoo-direct targets` before choosing an unfamiliar target. Address every
target by its configured name:

```bash
odoo-direct local test
odoo-direct production search-read res.company "[]" "['name']"
odoo-direct upgrade write res.partner '[1]' "{'name': 'Example'}"
```

The target's tags decide the policy for `read`, `create`, `write`, `unlink`, and
`exec`. Valid values are `allow`, `ask`, and `deny`; the strictest value wins.
The `production` tag cannot allow automatic writes. `ask` requires an unchanged
preview followed by `--confirm`. JSON-2 requires Odoo 19 or newer and never falls
back to another transport or target.

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
use the same `.odoo/config.yaml`. `odoo-fresh` reads `.odoo/dump.sql` unless the
caller supplies `--dump`.
