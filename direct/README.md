# odoo-direct

`odoo-direct` provides deterministic Odoo 19 JSON-2 model access. Run it inside
a configured Git repository.

```bash
odoo-direct targets
odoo-direct local test
odoo-direct production search-read res.company "[]" "['name']"
```

The repository owns two files:

- `.odoo/config.yaml` is committed. It defines runtime settings, targets, tags,
  and operation policies.
- `.odoo/secrets.env` is ignored. A target named `upgrade-19` reads
  `ODOO_DIRECT_UPGRADE_19_API_KEY` from this file.

Every tag defines `read`, `create`, `write`, `unlink`, and `exec` as `allow`,
`ask`, or `deny`. With multiple tags, `deny > ask > allow`. The reserved
`production` tag cannot allow automatic writes.

An `ask` operation previews without changing records. After explicit approval,
rerun the unchanged command with `--confirm`. An `allow` write previews, applies,
and reads back without pausing. A `deny` operation stops before calling Odoo.

Odoo versions before 19 do not provide JSON-2. Declaring `odoo_version` below 19
makes the command fail clearly; it does not fall back to another protocol.
