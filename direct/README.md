# odoo-direct

`odoo-direct` provides deterministic model access for Odoo 17 and newer. It uses
XML-RPC for Odoo 17 and 18, and JSON-2 for Odoo 19 and newer. Run it inside a
configured Git repository.

```bash
odoo-direct targets
odoo-direct local test
odoo-direct production search-read res.company "[]" "['name']"
```

The repository owns two files:

- `.odoo/config.toml` is committed. It defines runtime settings, targets, tags,
  and operation policies.
- `.odoo/secrets.env` is ignored. A target named `upgrade-19` reads
  `ODOO_DIRECT_UPGRADE_19_API_KEY` from this file.

An XML-RPC target includes the login associated with its API key:

```toml
[targets.production]
odoo_version = 17
url = "https://example.odoo.com"
database = "example"
username = "agent@example.com"
tags = ["production"]
```

Every tag defines `read`, `create`, `write`, `unlink`, and `exec` as `allow`,
`ask`, or `deny`. With multiple tags, `deny > ask > allow`. Target names and tag
names have no extra rules; only the values in `.odoo/config.toml` apply.

An `ask` operation previews without changing records. After explicit approval,
rerun the unchanged command with `--confirm`. An `allow` write previews, applies,
and reads back without pausing. A `deny` operation stops before calling Odoo.

Targets for Odoo 17 and 18 must declare `username`. Their API key is the XML-RPC
password. The configured `odoo_version` selects one transport. A SaaS string such as
`saas~19.3.1.3` is major 19. The command does not fall back to another
transport after an error.
