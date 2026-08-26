# odoo-direct contract

## Resolution

1. Resolve the current Git repository root.
2. Load `.odoo/config.yaml`.
3. Merge optional `.odoo/worktree.yaml` over it.
4. Load ignored `.odoo/secrets.env`.
5. Resolve the exact positional target name. No default target exists.

## Target

Each target declares `url`, `database`, `odoo_version`, and one or more tags.
Its API-key variable is `ODOO_DIRECT_<NORMALIZED_TARGET>_API_KEY`. Normalization
uppercases the name and replaces non-alphanumeric characters with `_`.

JSON-2 requires Odoo 19 or newer. A lower version fails without transport or
target fallback.

## Policy

Every tag declares `read`, `create`, `write`, `unlink`, and `exec`. Valid values
are `allow`, `ask`, and `deny`. All keys are mandatory. Multiple tags resolve to
the strictest value using `deny > ask > allow`. The reserved `production` tag
cannot resolve a write-capable operation to `allow`.

- `allow` executes without a conversation pause.
- `ask` previews and requires the unchanged command with `--confirm`.
- `deny` stops before an Odoo call.

## Transport

Calls use `POST /json/2/<model>/<method>`, bearer authorization, and an explicit
`X-Odoo-Database` header. Redirects, configuration mismatches, and connection
failures stop the command. The client never retries a write automatically.
