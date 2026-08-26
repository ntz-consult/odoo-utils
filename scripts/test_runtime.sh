#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf -- "$TEST_ROOT"' EXIT
PROJECT="$TEST_ROOT/project"
git -C "$TEST_ROOT" init -q project
mkdir -p "$PROJECT/.odoo" "$PROJECT/nested/deeper" "$PROJECT/fake-odoo/odoo"
touch "$PROJECT/fake-odoo/odoo/odoo-bin"

cat > "$PROJECT/.odoo/config.yaml" <<EOF
version: 1
project:
  name: runtime-test
odoo:
  root: $PROJECT/fake-odoo
  data_dir: $PROJECT/.odoo/data
database:
  name: runtime_test
  user: odoo
ports:
  http: 8181
  test_http: 9181
  test_gevent: 9182
  test_range_start: 9181
  test_range_end: 9282
tags:
  develop:
    read: allow
    create: allow
    write: allow
    unlink: ask
    exec: ask
targets:
  local:
    odoo_version: 19
    url: http://127.0.0.1:8181
    database: runtime_test
    tags: [develop]
EOF
printf 'DB_PASSWORD=not-printed\nODOO_DIRECT_LOCAL_API_KEY=test-key\n' > "$PROJECT/.odoo/secrets.env"
chmod 600 "$PROJECT/.odoo/secrets.env"

(
    cd "$PROJECT/nested/deeper"
    source "$SCRIPT_DIR/common.sh"
    [[ "$PROJECT_ROOT" == "$PROJECT" ]]
    [[ "$ODOO_CONFIG_FILE" == "$PROJECT/.odoo/config.yaml" ]]
    [[ "$CONF_FILE" == "$PROJECT/.odoo/odoo.conf" ]]
    [[ "$HTTP_PORT" == 8181 ]]
)
grep -q '^db_name = runtime_test$' "$PROJECT/.odoo/odoo.conf"
grep -q '^http_port = 8181$' "$PROJECT/.odoo/odoo.conf"
[[ "$(stat -c '%a' "$PROJECT/.odoo/odoo.conf")" == 600 ]]

cat > "$PROJECT/.odoo/worktree.yaml" <<EOF
database:
  name: runtime_worktree
ports:
  http: 8282
targets:
  local:
    url: http://127.0.0.1:8282
    database: runtime_worktree
EOF
(
    cd "$PROJECT"
    source "$SCRIPT_DIR/common.sh"
    [[ "$DB_NAME" == runtime_worktree ]]
    [[ "$HTTP_PORT" == 8282 ]]
)

for command in run run-script test init install init-env fresh lint cloc sync direct direct-init; do
    (cd /tmp && "$HOME/.local/share/odoo/bin/odoo-$command" --help >/dev/null)
done

echo "runtime configuration tests passed"
