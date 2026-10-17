#!/bin/bash
# Post-restore repair for filestore-less dev DBs: rebuild menu icons, drop asset bundles.
# Usage: odoo-fix-icons [project_dir ...]   (default: cwd). Dev DBs only (uses .odoo/odoo.conf, local PG).
set -u
here="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
/workspace/Work/sys-admin/odoo/pg-local.sh start >/dev/null 2>&1
rc=0
for d in "${@:-$PWD}"; do
  conf="$d/.odoo/odoo.conf"; [ -f "$conf" ] || { echo "skip $d (no .odoo/odoo.conf)"; continue; }
  host=$(awk -F' *= *' '$1=="db_host"{print $2}' "$conf"); port=$(awk -F' *= *' '$1=="db_port"{print $2}' "$conf")
  case "$host" in localhost|127.0.0.1|"") ;; *) echo "REFUSE $d: db_host=$host is not local"; rc=1; continue;; esac
  [ "$port" = 5432 ] || { echo "REFUSE $d: db_port=$port"; rc=1; continue; }
  root=$(awk -F' *= *' '$1=="addons_path"{print $2}' "$conf" | tr , '\n' | grep -m1 '/odoo/addons$' | sed 's#/addons$##')
  py="$d/.venv/bin/python"; [ -x "$py" ] || py=python3
  echo "== $d ($(awk -F' *= *' '$1=="db_name"{print $2}' "$conf"))"
  "$py" "$root/odoo-bin" shell -c "$conf" --no-http --log-level=warn < "$here/fix_icons.py" 2>&1 | grep -E 'FIX_ICONS|Error|Traceback' || rc=1
done
exit $rc
