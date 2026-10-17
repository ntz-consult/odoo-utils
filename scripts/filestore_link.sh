#!/bin/bash
# Worktrees share the primary checkout's filestore (Gerhard, 2026-10-15): the filestore is never
# copied into a worktree; <data_dir>/filestore/<worktree_db> is a symlink to the primary
# checkout's <data_dir>/filestore/<main_db>. Without it logos, images and attachments break.
#
# Source it and call `odoo_link_main_filestore ROOT`, or run it: filestore_link.sh [ROOT]
# Idempotent. A real (copied) directory in the way is never deleted: an empty one is removed,
# a non-empty one is renamed to <name>.bak-YYYYMMDD. The primary checkout is left untouched.

_fsl_key() { python3 -c 'import json,sys
d=json.loads(sys.argv[1])
for k in sys.argv[2].split("."):
    d = d.get(k) if isinstance(d, dict) else None
print("" if d is None else d)' "$1" "$2"; }

_fsl_json() {
    local root="$1" cfg="$1/.odoo/config.toml" wt="$1/.odoo/worktree.toml"
    local here; here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    [[ -f "$cfg" ]] || { echo '{}'; return; }
    python3 "$here/config.py" json "$cfg" "$wt" "$root" 2>/dev/null || echo '{}'
}

# Print "<data_dir>|<db>" for a checkout (defaults as in common.sh).
odoo_filestore_identity() {
    local root="$1" json data db
    json="$(_fsl_json "$root")"
    data="$(_fsl_key "$json" odoo.data_dir)"; data="${data:-$root/.odoo/odoo-data}"
    db="$(_fsl_key "$json" database.name)"; db="${db:-$(basename "$root")}"
    printf '%s|%s\n' "${data/#\~/$HOME}" "$db"
}

odoo_link_main_filestore() {
    local root main id mid data db mdata mdb link target cur bak
    root="$(cd "${1:-.}" && git rev-parse --show-toplevel 2>/dev/null)" || { echo "filestore-link: not a Git worktree: ${1:-.}" >&2; return 1; }
    root="$(cd "$root" && pwd -P)"
    main="$(git -C "$root" worktree list --porcelain | awk '/^worktree / {print substr($0, 10); exit}')"
    main="$(cd "$main" && pwd -P)"
    [[ "$root" != "$main" ]] || return 0   # the primary checkout owns the real filestore
    id="$(odoo_filestore_identity "$root")"; data="${id%%|*}"; db="${id#*|}"
    mid="$(odoo_filestore_identity "$main")"; mdata="${mid%%|*}"; mdb="${mid#*|}"
    target="$mdata/filestore/$mdb"
    link="$data/filestore/$db"
    if [[ "$db" == "$mdb" && "$data" == "$mdata" ]] || [[ "$link" -ef "$target" && ! -L "$link" ]]; then
        echo "filestore-link: $link is the primary filestore itself; nothing to do" >&2; return 0
    fi
    mkdir -p -- "$target" "$data/filestore" || return 1
    if [[ -L "$link" ]]; then
        cur="$(readlink -- "$link")"
        [[ "$cur" == "$target" ]] && return 0
        echo "filestore-link: repairing $link (was -> $cur)" >&2
        rm -f -- "$link"
    elif [[ -d "$link" ]]; then
        if rmdir -- "$link" 2>/dev/null; then :; else
            bak="$link.bak-$(date +%Y%m%d)"
            [[ -e "$bak" ]] && bak="$bak-$(date +%H%M%S)"
            echo "filestore-link: keeping copied filestore as $bak ($(du -sh -- "$link" | cut -f1))" >&2
            mv -- "$link" "$bak" || return 1
        fi
    elif [[ -e "$link" ]]; then
        echo "filestore-link: $link exists and is not a directory; leaving it" >&2; return 1
    fi
    ln -s -- "$target" "$link" && echo "filestore-link: $link -> $target" >&2
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    odoo_link_main_filestore "${1:-.}"
fi
