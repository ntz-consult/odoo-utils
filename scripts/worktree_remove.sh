#!/bin/bash
# Remove a finished linked worktree completely: its Odoo process, database,
# filestore, folder and branch. Nothing of the worktree remains.
#
# Usage:
#   odoo-worktree-remove [--dry-run] [--yes] [--force] [--hook CMD] PATH
#
#   --dry-run  print what would be removed and stop
#   --yes      do not ask for the typed confirmation (required without a TTY)
#   --force    also remove a worktree with uncommitted or unpushed work, and
#              delete its branch even when it is not merged (that work is lost)
#   --hook CMD run CMD after removal, e.g. to regenerate a proxy configuration.
#              Default: $ODOO_WORKTREE_REMOVE_HOOK, else `remove_hook` of the
#              project's pool in the port register (scripts/ports.py).
#              The hook sees ODOO_REMOVED_ROOT, ODOO_REMOVED_DB, ODOO_REMOVED_HTTP_PORT.
#
# Refuses the primary checkout, a database equal to the primary checkout's, and
# (without --force) uncommitted changes or commits not reachable from any other
# branch or remote-tracking ref.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() { sed -n '5,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }
die() { echo "odoo-worktree-remove: $*" >&2; exit 1; }

DRY_RUN=false YES=false FORCE=false HOOK="${ODOO_WORKTREE_REMOVE_HOOK:-}" HOOK_SET=false TARGET=""
[[ -n "$HOOK" ]] && HOOK_SET=true
while (($#)); do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --yes) YES=true; shift ;;
        --force) FORCE=true; shift ;;
        --hook) (($# >= 2)) || die "--hook needs a command"; HOOK="$2"; HOOK_SET=true; shift 2 ;;
        -*) die "unknown option '$1'" ;;
        *) [[ -z "$TARGET" ]] || die "only one PATH"; TARGET="$1"; shift ;;
    esac
done
[[ -n "$TARGET" ]] || { usage >&2; exit 2; }
[[ -d "$TARGET" ]] || die "not a directory: $TARGET"
ROOT="$(git -C "$TARGET" rev-parse --show-toplevel 2>/dev/null)" || die "not a Git worktree: $TARGET"
ROOT="$(cd "$ROOT" && pwd -P)"
MAIN="$(git -C "$ROOT" worktree list --porcelain | awk '/^worktree / {print substr($0, 10); exit}')"
MAIN="$(cd "$MAIN" && pwd -P)"
[[ "$ROOT" != "$MAIN" ]] || die "$ROOT is the primary checkout; only linked worktrees are removed"

# Runtime identity from the worktree's own .odoo configuration.
json_of() { [[ -f "$1/.odoo/config.toml" ]] && python3 "$SCRIPT_DIR/config.py" json "$1/.odoo/config.toml" "$1/.odoo/worktree.toml" 2>/dev/null || echo '{}'; }
read_key() { python3 -c 'import json,sys
d=json.loads(sys.argv[1])
for k in sys.argv[2].split("."):
    d = d.get(k) if isinstance(d, dict) else None
print("" if d is None else d)' "$1" "$2"; }
CONFIG="$(json_of "$ROOT")"
MAIN_CONFIG="$(json_of "$MAIN")"
DB="$(read_key "$CONFIG" database.name)"
MAIN_DB="$(read_key "$MAIN_CONFIG" database.name)"
HTTP="$(read_key "$CONFIG" ports.http)"
PROJECT="$(read_key "$CONFIG" project.name)"; PROJECT="${PROJECT:-$(basename "$MAIN")}"
DATA_DIR="$(read_key "$CONFIG" odoo.data_dir)"; DATA_DIR="${DATA_DIR:-$ROOT/.odoo/data}"
DB_HOST="$(read_key "$CONFIG" database.host)"
DB_PORT="$(read_key "$CONFIG" database.port)"
DB_USER="$(read_key "$CONFIG" database.user)"
BRANCH="$(git -C "$ROOT" symbolic-ref --quiet --short HEAD || true)"
if [[ -n "$DB" && "$DB" == "$MAIN_DB" ]]; then
    die "database '$DB' is the primary checkout's database; give the worktree its own database first"
fi
if [[ "$HOOK_SET" != true ]]; then
    HOOK="$(python3 "$SCRIPT_DIR/ports.py" hook "$PROJECT" 2>/dev/null || true)"
fi

# Work that would be lost.
PROBLEMS=()
if [[ -n "$(git -C "$ROOT" status --porcelain)" ]]; then
    PROBLEMS+=("uncommitted changes or untracked files (git status)")
fi
OTHER_REFS=()
while IFS= read -r ref; do
    [[ -n "$BRANCH" && "$ref" == "refs/heads/$BRANCH" ]] && continue
    OTHER_REFS+=("$ref")
done < <(git -C "$ROOT" for-each-ref --format='%(refname)' refs/heads refs/remotes)
UNPUSHED="$(git -C "$ROOT" rev-list --count HEAD --not "${OTHER_REFS[@]}" -- 2>/dev/null || git -C "$ROOT" rev-list --count HEAD)"
if [[ "$UNPUSHED" != 0 ]]; then
    PROBLEMS+=("$UNPUSHED commit(s) on ${BRANCH:-HEAD} not in any other branch or remote")
fi

CONF="$ROOT/.odoo/odoo.conf"
PIDS="$(pgrep -f -- "-c $CONF" || true)"

echo "Worktree removal plan"
echo "  Worktree:  $ROOT (primary: $MAIN)"
echo "  Branch:    ${BRANCH:-detached} (deleted)"
echo "  Database:  ${DB:-none} (dropped)"
echo "  Filestore: $DATA_DIR/filestore/${DB:-?}"
if [[ -n "$PIDS" ]]; then
    echo "  Odoo:      running, pid(s) $(echo $PIDS) will be stopped"
else
    echo "  Odoo:      not running"
fi
echo "  Hook:      ${HOOK:-none}"
for problem in "${PROBLEMS[@]}"; do echo "  WORK AT RISK: $problem"; done
if ((${#PROBLEMS[@]})) && [[ "$FORCE" != true ]]; then
    die "refusing: commit and push (or merge) the work first, or pass --force to discard it"
fi
if [[ "$DRY_RUN" == true ]]; then
    echo "Dry run; nothing was changed."
    exit 0
fi
if [[ "$YES" != true ]]; then
    [[ -t 0 ]] || die "no terminal to confirm on; pass --yes"
    read -r -p "Type '$(basename "$ROOT")' to remove it: " answer
    [[ "$answer" == "$(basename "$ROOT")" ]] || { echo "Cancelled; nothing was changed."; exit 1; }
fi

if [[ -n "$PIDS" ]]; then
    echo "Stopping Odoo ($(echo $PIDS))"
    kill $PIDS 2>/dev/null || true
    for _ in $(seq 20); do pgrep -f -- "-c $CONF" >/dev/null || break; sleep 1; done
    if pgrep -f -- "-c $CONF" >/dev/null; then
        kill -9 $(pgrep -f -- "-c $CONF") 2>/dev/null || true
    fi
fi

if [[ -n "$DB" ]]; then
    PG_ARGS=()
    [[ -n "$DB_HOST" ]] && PG_ARGS+=(--host "$DB_HOST")
    [[ -n "$DB_PORT" ]] && PG_ARGS+=(--port "$DB_PORT")
    [[ -n "$DB_USER" ]] && PG_ARGS+=(--username "$DB_USER")
    PASSWORD=""
    if [[ -f "$ROOT/.odoo/secrets.env" ]]; then
        PASSWORD="$(set -a; source "$ROOT/.odoo/secrets.env" >/dev/null 2>&1; printf '%s' "${DB_PASSWORD:-}")"
    fi
    echo "Dropping database $DB"
    PGPASSWORD="$PASSWORD" dropdb "${PG_ARGS[@]}" --if-exists --force "$DB"
fi

# A filestore outside the worktree folder is removed on its own; inside, it goes with the folder.
FILESTORE="$DATA_DIR/filestore/$DB"
if [[ -n "$DB" && -d "$FILESTORE" && "$(cd "$FILESTORE" && pwd -P)" != "$ROOT"/* ]]; then
    echo "Removing filestore $FILESTORE"
    rm -rf -- "$FILESTORE"
fi

echo "Removing worktree $ROOT"
# Ignored runtime files (.odoo/data, secrets, logs) go with the folder.
git -C "$MAIN" worktree remove --force "$ROOT"
[[ ! -e "$ROOT" ]] || rm -rf -- "$ROOT"
git -C "$MAIN" worktree prune
if [[ -n "$BRANCH" ]]; then
    # Without --force every commit of the branch was checked to be in another ref.
    git -C "$MAIN" branch -D "$BRANCH" >/dev/null && echo "Deleted branch $BRANCH"
fi

if [[ -n "$HOOK" ]]; then
    echo "Running hook: $HOOK"
    ODOO_REMOVED_ROOT="$ROOT" ODOO_REMOVED_DB="$DB" ODOO_REMOVED_HTTP_PORT="$HTTP" bash -c "$HOOK"
fi
echo "Removed $ROOT${DB:+ and database $DB}; its ports are free again."
