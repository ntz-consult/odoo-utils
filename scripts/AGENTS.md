# Odoo global commands

## Interaction and instruction portability

These owner instructions apply to every coding agent, regardless of provider or interface. Preserve the project's safety and approval rules.

- Keep `AGENTS.md` as the canonical instruction file. `CLAUDE.md` is only a compatibility symlink to `AGENTS.md`; never keep separate rules there.
- Keep shared policies, skills, and workflows agent agnostic. Provider-specific launchers and configuration are adapters, not separate sources of behavioral rules. Do not require a named provider for ordinary work or review.
- Ask one question at a time, using the existing question-count convention when applicable.
- Put every answer option in its own paragraph, beginning with a bold letter label such as **A.**, **B.**, **C.**, or **D.**
- Leave a blank line between options. Never combine several options into one paragraph or put the question in a code block.
- Mark one recommended option when a recommendation is useful. Use short, plain explanations.

These instructions supersede older option-formatting examples and agent-specific wording. Read the shared `one-question-at-a-time` skill when available.


Every `odoo-*` command resolves the current Git repository root and reads its
shared runtime from `.odoo/`:

```text
.odoo/config.toml    committed runtime, targets, tags, and policies
.odoo/secrets.env    ignored database passwords and target API keys
.odoo/worktree.toml  optional ignored explicit database and port overrides
.odoo/dump.sql       ignored source used by odoo-fresh
.odoo/odoo.conf      ignored generated Odoo server configuration
```

When a `port-tool` command is installed, `odoo-run` records its HTTP port (and
the gevent port when workers are requested) in that shared reservation register
under the owner `odoo-<database>` before starting, and refuses to start if another
owner holds the port. `odoo-test` records each test pair under
`odoo-test-<database>` and releases it when the run ends. Set `ODOO_PORT_TOOL`
to another executable to override the command, or to `none` in test suites that
must not consult host sockets. Without the command nothing is recorded.

Run `odoo-init-env` to create a new runtime. A linked worktree must receive an
explicit allocation:

```bash
odoo-init-env --worktree --db REPO_BRANCH --http-port 8201 --test-range-start 9700
```

With a port register (below) `--http-port` and `--test-range-start` are optional:
the command takes the first free slot of the project's pool.

The command also installs the primary checkout's untracked agent-rules overlay
(`PROJECT_RULES.md`, `AGENTS.md`, `.odoo-sh-rules`) when it has one, through its
`scripts/link-repository`.

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

A linked worktree (`git worktree add`) with its own `.odoo` directory has its own
`worktree.toml` or it does not run. Its committed `config.toml` carries the primary
checkout's ports, so `odoo-run`, `odoo-test` and `odoo-init-env` (without
`--worktree`) refuse that worktree without `[ports] http` in its `worktree.toml`,
and name the fix: `odoo-init-env --worktree --db NAME`. That worktree claims only
its own `worktree.toml` ports. The primary checkout keeps its fixed ports.

A worktree whose `.odoo` is a symlink to the primary checkout's `.odoo` uses that
folder and the primary ports. Its database name comes from the directory name
(`ibcorr-ticket-00017` uses `ibcorr_ticket_00017`). The generated `odoo.conf` for
that database is written under `~/.cache/odoo-utils/conf/`, so starting the worktree
does not rewrite the primary `odoo.conf`. `odoo-init-env --worktree` sets up this
link for the `ibcorr` project. `PROJECT_RULES.md` in a new worktree is a symlink to
the primary checkout's file.

```bash
ports.py show                      # pools, clashes, configs outside their pool
ports.py allocate PROJECT --root . # first free worktree slot (preview only)
ports.py assign PROJECT --root . --db NAME   # allocate and write worktree.toml, locked
ports.py guard --root .            # may this linked worktree run? (exit 1 if not)
ports.py check PROJECT --root . --http 8201
```

Without a register nothing is enforced. Never start Odoo on a port outside your
project's pool; add or change the pool in the register instead.
