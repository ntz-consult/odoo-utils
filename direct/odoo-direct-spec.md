# odoo-direct contract

## Resolution

1. Resolve the current Git repository root.
2. Load `.odoo/config.toml`.
3. Merge optional `.odoo/worktree.toml` over it.
4. Load ignored `.odoo/secrets.env`.
5. Resolve the exact positional target name. No default target exists.

## Target

Each target declares `url`, `database`, `odoo_version`, and one or more tags.
Odoo 17 and 18 targets also declare `username`.
Its API-key variable is `ODOO_DIRECT_<NORMALIZED_TARGET>_API_KEY`. Normalization
uppercases the name and replaces non-alphanumeric characters with `_`.

`odoo_version` selects XML-RPC for versions 17 and 18. It selects JSON-2 for
version 19 and newer. Dotted and SaaS strings such as `19.3.1.3` and
`saas~19.3.1.3` use the major number. Versions before 17 fail without transport
or target fallback.

## Policy

Every tag declares `read`, `create`, `write`, `unlink`, and `exec`. Valid values
are `allow`, `ask`, and `deny`. All keys are mandatory. Multiple tags resolve to
the strictest value using `deny > ask > allow`. Policy comes only from
`.odoo/config.toml`. Target and tag names do not add extra restrictions.

- `allow` executes without a conversation pause.
- `ask` previews and requires the unchanged command with `--confirm`.
- `deny` stops before an Odoo call.

## Transport

JSON-2 calls use `POST /json/2/<model>/<method>`, bearer authorization, and an
explicit `X-Odoo-Database` header. XML-RPC calls authenticate with the target's
database, username, and API key, then call `/xmlrpc/2/object`. `test` compares
the configured major version with the server's major version, including SaaS
strings such as `saas~19.3.1.3`. Configuration mismatches and connection
failures stop the command. The client does not switch transports or retry a
write automatically.
