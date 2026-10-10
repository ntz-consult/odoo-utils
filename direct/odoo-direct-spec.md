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

### Model rules

A tag may override its policies for one model. Rules are optional; a tag
without `models` behaves exactly as above.

```toml
[tags.production]
read = "allow"
create = "ask"
write = "ask"
unlink = "ask"
exec = "ask"

[tags.production.models."helpdesk.ticket"]
create = "allow"
write = "allow"
fields = { stage_id = "ask" }          # create/write touching stage_id asks
methods = { message_post = "ask" }     # exec of one method

[tags.production.models."res.partner"]
write = "deny"
```

A model table accepts the five operation keys plus `fields` and `methods`.
Every value is `allow`, `ask`, or `deny`; unknown keys and invalid values fail
the command.

Precedence:

1. Inside one tag the most specific matching rule wins: tag operation, then
   model operation, then `fields.<name>` (create and write) or
   `methods.<name>` (exec). A specific rule may loosen or tighten.
2. A create or write that touches several fields takes the strictest of the
   touched fields.
3. Across a target's tags the strictest result still wins. Add a tag such as
   `locked` to impose a deny no model rule can lift.
4. `exec` of an ORM CRUD method (`create`, `copy`, `write`, `web_save`,
   `unlink`, `read`, `web_read`, `search`, `search_read`, `web_search_read`,
   `search_count`, `fields_get`) must also pass that operation's policy for
   the model, so `exec` cannot bypass `unlink` or `write`.
5. When `allow` comes from a model or field rule and the values contain x2many
   command lists such as `[(2, 5)]`, the command falls back to `ask`. Tag-level
   `allow` is unaffected.

The output `Policy:` line and the JSON `rule` key name the deciding rule.
Older odoo-direct versions ignore `models`, so a loosening rule fails closed
(the tag policy applies) but a tightening rule is ignored there; impose hard
denies with an extra tag until every machine runs this version.

### Audit log

Every executed `create`, `write`, `unlink`, or `exec` (allowed or confirmed)
appends one JSON line to `.odoo/odoo-direct-audit.log`: UTC time, target,
database, operation, model, method, IDs, touched field names, policy, rule,
whether `--confirm` was given, and the new ID for creates. Values are never
logged. Previews and reads are not logged. Keep the file Git-ignored.

## Transport

JSON-2 calls use `POST /json/2/<model>/<method>`, bearer authorization, and an
explicit `X-Odoo-Database` header. XML-RPC calls authenticate with the target's
database, username, and API key, then call `/xmlrpc/2/object`. `test` compares
the configured major version with the server's major version, including SaaS
strings such as `saas~19.3.1.3`. Configuration mismatches and connection
failures stop the command. The client does not switch transports or retry a
write automatically.
