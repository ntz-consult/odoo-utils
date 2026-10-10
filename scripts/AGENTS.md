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

With a port register (below) `--http-port` and `--test-range-start` are optional:
the command takes the first free slot of the project's pool.

The command symlinks `secrets.env` from the primary checkout. It records the
worktree database and ports in `.odoo/worktree.toml`; configuration never merges
from a parent repository.

When a worktree is finished, remove all of it: folder, database, filestore and
branch. Nothing of a finished worktree may remain.

```bash
odoo-worktree-remove --dry-run ../repo-feature   # show the plan
odoo-worktree-remove --yes ../repo-feature       # stop its Odoo, drop DB, remove, prune
```

It refuses the primary checkout, a database equal to the primary checkout's, and
uncommitted changes or commits that are in no other branch or remote ref (unless
`--force`, which discards that work). An optional hook (`--hook`,
`$ODOO_WORKTREE_REMOVE_HOOK`, or the pool's `remove_hook` in the port register)
runs afterwards, e.g. to regenerate a proxy configuration. Ports are never
reserved, so the worktree's ports are free as soon as it is gone.

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
requires an unchanged preview followed by `--confirm`. A tag may narrow its
policy per model with `[tags.<tag>.models."<model>"]` (optional `fields` and
`methods` tables); the most specific rule wins inside a tag, and the
strictest tag still wins across tags. See `direct/odoo-direct-spec.md`.
Executed changes are appended to `.odoo/odoo-direct-audit.log`. Odoo 17 and 18 use
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

## Port pools

`scripts/ports.py` reads a port register (TOML; `$ODOO_PORTS_REGISTER`, default
`~/Work/sys-admin/odoo/ports.toml`) that gives each project (`[project].name`)
its own non-overlapping pool: a main http port, worktree http ports, and test-port
blocks. The second (gevent/websocket) port is `http + gevent_offset` and is written
to `odoo.conf` as `gevent_port`. When a register exists:

- `odoo-run` refuses an http/gevent port outside the project's pool, a port that
  another checkout is assigned, and any project without a pool;
- `odoo-test` refuses test ports outside the project's test pool;
- `odoo-init-env --worktree` allocates the first slot that no checkout claims and
  nothing listens on, and writes `worktree.toml` under the port lock
  (`~/.cache/odoo-utils/ports.lock`, override `ODOO_PORTS_LOCK`), so two worktrees
  can never be given the same port.

A linked worktree (`git worktree add`) has its own `worktree.toml` or it does not
run. Its committed `config.toml` carries the primary checkout's ports, so
`odoo-run`, `odoo-test` and `odoo-init-env` (without `--worktree`) refuse a linked
worktree without `[ports] http` in its `worktree.toml`, and name the fix:
`odoo-init-env --worktree --db NAME`. A linked worktree claims only its own
`worktree.toml` ports. The primary checkout keeps its fixed ports.

```bash
ports.py show                      # pools, clashes, configs outside their pool
ports.py allocate PROJECT --root . # first free worktree slot (preview only)
ports.py assign PROJECT --root . --db NAME   # allocate and write worktree.toml, locked
ports.py guard --root .            # may this linked worktree run? (exit 1 if not)
ports.py check PROJECT --root . --http 8201
```

Without a register nothing is enforced. Never start Odoo on a port outside your
project's pool; add or change the pool in the register instead.
