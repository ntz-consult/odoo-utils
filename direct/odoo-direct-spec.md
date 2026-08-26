# odoo-direct contract

## Resolution

1. Resolve the current Git repository root.
2. Load `.odoo/config.yaml`.
3. Merge optional `.odoo/worktree.yaml` over it.
4. Load ignored `.odoo/secrets.env`.
5. Resolve the exact positional target name. No default target exists.

## Target

Each target declares `url`, `database`, `odoo_version`, and one or more tags.
Odoo 17 and 18 targets also declare `username`.
Its API-key variable is `ODOO_DIRECT_<NORMALIZED_TARGET>_API_KEY`. Normalization
uppercases the name and replaces non-alphanumeric characters with `_`.

`odoo_version` selects XML-RPC for versions 17 and 18. It selects JSON-2 for
version 19 and newer. Versions before 17 fail without transport or target
fallback.

## Policy

Every tag declares `read`, `create`, `write`, `unlink`, and `exec`. Valid values
are `allow`, `ask`, and `deny`. All keys are mandatory. Multiple tags resolve to
the strictest value using `deny > ask > allow`. The reserved `production` tag
cannot resolve a write-capable operation to `allow`.

- `allow` executes without a conversation pause.
- `ask` previews and requires the unchanged command with `--confirm`.
- `deny` stops before an Odoo call.

## Transport

JSON-2 calls use `POST /json/2/<model>/<method>`, bearer authorization, and an
explicit `X-Odoo-Database` header. XML-RPC calls authenticate with the target's
database, username, and API key, then call `/xmlrpc/2/object`. `test` compares
the configured major version with the server's major version. Configuration
mismatches and connection failures stop the command. The client does not switch
transports or retry a write automatically.
