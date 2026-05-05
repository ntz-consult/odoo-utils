#!/bin/bash
# init_env.sh — Bootstrap environment for Odoo project
#
# Usage:
#   odoo-init-env                    # Generate .env + odoo.conf (interactive prompts)
#   odoo-init-env --force            # Overwrite existing files (backs up to .bak)
#   odoo-init-env --venv-create      # Also create Python venv + install deps
#   odoo-init-env --venv-only        # Verify/create venv, update PYTHON_PATH
#   odoo-init-env --update-conf      # Regenerate odoo.conf from existing .env
#
# IMPORTANT: .env and odoo.conf are ALWAYS created in the CURRENT DIRECTORY ($PWD).

set -euo pipefail

ENV_DIR="$(pwd)"
PROJECT_ROOT="$ENV_DIR"

ENV_FILE="$ENV_DIR/.env"
CONF_FILE="$ENV_DIR/odoo.conf"

FORCE=false
VENV_CREATE=false
VENV_ONLY=false
UPDATE_CONF_ONLY=false

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=true ;;
        --venv-create) VENV_CREATE=true ;;
        --venv-only) VENV_ONLY=true ;;
        --update-conf) UPDATE_CONF_ONLY=true ;;
        *)
            echo "Unknown option: $arg"
            echo "Usage: $0 [--force] [--venv-create] [--venv-only] [--update-conf]"
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
backup_file() {
    local f="$1"
    if [[ -f "$f" ]]; then
        cp "$f" "$f.bak"
        echo "  Backed up: $f.bak"
    fi
}

prompt() {
    local msg="$1"
    local default="${2:-}"
    local val=""
    if [[ -n "$default" ]]; then
        read -rp "$msg [$default]: " val
        val="${val:-$default}"
    else
        read -rp "$msg: " val
    fi
    echo "$val"
}

generate_odoo_conf() {
    local out_file="$1"
    cat > "$out_file" <<EOF
[options]

; ── Network ────────────────────────────────────────────────
http_interface = 0.0.0.0
http_port      = ${HTTP_PORT}

; ── Database ─────────────────────────────────────────────
EOF

    if [[ -n "${DB_HOST:-}" ]]; then
        echo "db_host        = ${DB_HOST}" >> "$out_file"
    fi
    if [[ -n "${DB_PORT:-}" ]]; then
        echo "db_port        = ${DB_PORT}" >> "$out_file"
    fi
    if [[ -n "${DB_USER:-}" ]]; then
        echo "db_user        = ${DB_USER}" >> "$out_file"
    fi
    if [[ -n "${DB_PASSWORD:-}" ]]; then
        echo "db_password    = ${DB_PASSWORD}" >> "$out_file"
    fi

    cat >> "$out_file" <<EOF

; Uncomment the next line ONLY if you want to lock Odoo to one specific database
; (no database selector/manager will appear)
db_name        = ${DB_NAME}

; ── Addons ─────────────────────────────────────────────────
addons_path    = ${ODOO_ROOT}/odoo/addons,
                 ${ODOO_ROOT}/enterprise,
                 ${ODOO_ROOT}/themes,
                 ${PROJECT_ROOT}

; ── Security ─────────────────────────────────────────────
list_db        = False

; ── Proxy ──────────────────────────────────────────────────
; Set to True only when running behind nginx / apache with proper X-Forwarded-* headers
proxy_mode     = False

; ── Logging ─────────────────────────────────────────────
log_level      = info
; logfile      = ${PROJECT_ROOT}/${PROJECT_NAME}.log   ; uncomment if you want file logging

; ── Binary Path (for wkhtmltopdf and other tools) ─────────
bin_path = ${BIN_PATH}
EOF
}

# ---------------------------------------------------------------------------
# --update-conf only
# ---------------------------------------------------------------------------
if $UPDATE_CONF_ONLY; then
    if [[ ! -f "$ENV_FILE" ]]; then
        echo "Error: $ENV_FILE not found. Run without --update-conf first."
        exit 1
    fi
    echo "Regenerating $CONF_FILE from $ENV_FILE..."
    set -a
    source "$ENV_FILE"
    set +a
    generate_odoo_conf "$CONF_FILE"
    echo "Done."
    exit 0
fi

# ---------------------------------------------------------------------------
# --venv-only
# ---------------------------------------------------------------------------
if $VENV_ONLY; then
    # Load PROJECT_ROOT from existing .env if available
    if [[ -f "$ENV_FILE" ]]; then
        set -a
        source "$ENV_FILE"
        set +a
        PROJECT_ROOT="${PROJECT_ROOT:-$ENV_DIR}"
    fi

    VENV_PATH="$PROJECT_ROOT/.venv"
    if [[ ! -d "$VENV_PATH" ]]; then
        echo "Creating venv at $VENV_PATH..."
        python3 -m venv "$VENV_PATH"
    else
        echo "Venv exists at $VENV_PATH"
    fi

    if [[ -f "$ENV_FILE" ]]; then
        backup_file "$ENV_FILE"
        sed -i "s|PYTHON_PATH=.*|PYTHON_PATH=$VENV_PATH/bin|" "$ENV_FILE"
        echo "Updated PYTHON_PATH in $ENV_FILE"
    fi

    echo "Done."
    exit 0
fi

# ---------------------------------------------------------------------------
# Determine defaults
# ---------------------------------------------------------------------------
DEFAULT_ODOO_ROOT="$HOME/Odoo/V19"
DEFAULT_PROJECT_ROOT="$ENV_DIR"

DEFAULT_PYTHON_PATH="$PROJECT_ROOT/.venv/bin"

DEFAULT_PROJECT_NAME="$(basename "$PROJECT_ROOT")"
DEFAULT_HTTP_PORT="8096"
DEFAULT_DB_HOST=""
DEFAULT_DB_PORT=""
DEFAULT_DB_USER=""
DEFAULT_DB_PASSWORD=""
DEFAULT_BIN_PATH="/usr/local/bin"
DEFAULT_ODOO_SYNC_SCRIPT="rsync-v19.sh"

# ---------------------------------------------------------------------------
# Read existing .env if present (always load as defaults)
# ---------------------------------------------------------------------------
if [[ -f "$ENV_FILE" ]]; then
    if ! $FORCE; then
        echo "Found existing $ENV_FILE — loading defaults from it."
    fi
    set -a
    source "$ENV_FILE"
    set +a
    DEFAULT_PROJECT_ROOT="${PROJECT_ROOT:-$DEFAULT_PROJECT_ROOT}"
    DEFAULT_ODOO_ROOT="${ODOO_ROOT:-$DEFAULT_ODOO_ROOT}"
    DEFAULT_PYTHON_PATH="${PYTHON_PATH:-$DEFAULT_PYTHON_PATH}"
    DEFAULT_PROJECT_NAME="${PROJECT_NAME:-$DEFAULT_PROJECT_NAME}"
    DEFAULT_HTTP_PORT="${HTTP_PORT:-$DEFAULT_HTTP_PORT}"
    DEFAULT_DB_HOST="${DB_HOST:-$DEFAULT_DB_HOST}"
    DEFAULT_DB_PORT="${DB_PORT:-$DEFAULT_DB_PORT}"
    DEFAULT_DB_USER="${DB_USER:-$DEFAULT_DB_USER}"
    DEFAULT_DB_PASSWORD="${DB_PASSWORD:-$DEFAULT_DB_PASSWORD}"
    DEFAULT_BIN_PATH="${BIN_PATH:-$DEFAULT_BIN_PATH}"
    DEFAULT_ODOO_SYNC_SCRIPT="${ODOO_SYNC_SCRIPT:-$DEFAULT_ODOO_SYNC_SCRIPT}"
fi

# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------
echo "=== Environment Setup ==="
echo ""
echo "Press Enter to accept defaults, or type new values:"
echo ""

PROJECT_ROOT=$(prompt "Project root" "$DEFAULT_PROJECT_ROOT")
ODOO_ROOT=$(prompt "Odoo source root" "$DEFAULT_ODOO_ROOT")
PYTHON_PATH=$(prompt "Python venv bin directory" "${PYTHON_PATH:-$PROJECT_ROOT/.venv/bin}")
PROJECT_NAME=$(prompt "Project name (used as default DB name)" "${PROJECT_NAME:-$(basename "$PROJECT_ROOT")}")
HTTP_PORT=$(prompt "HTTP port" "$DEFAULT_HTTP_PORT")
DB_HOST=$(prompt "Database host (optional, empty for peer auth)" "$DEFAULT_DB_HOST")
DB_PORT=$(prompt "Database port (optional)" "$DEFAULT_DB_PORT")
DB_USER=$(prompt "Database user (optional)" "$DEFAULT_DB_USER")
DB_PASSWORD=$(prompt "Database password (optional)" "$DEFAULT_DB_PASSWORD")
BIN_PATH=$(prompt "Binary path (wkhtmltopdf etc.)" "$DEFAULT_BIN_PATH")
ODOO_SYNC_SCRIPT=$(prompt "Odoo source sync script (optional)" "$DEFAULT_ODOO_SYNC_SCRIPT")

# Validate
if [[ ! -d "$ODOO_ROOT" ]]; then
    echo "Error: ODOO_ROOT does not exist: $ODOO_ROOT"
    exit 1
fi

DB_NAME="$PROJECT_NAME"

# ---------------------------------------------------------------------------
# Write .env
# ---------------------------------------------------------------------------
if [[ -f "$ENV_FILE" ]]; then
    if $FORCE; then
        backup_file "$ENV_FILE"
    else
        echo "Error: $ENV_FILE already exists. Use --force to overwrite (with backup)."
        exit 1
    fi
fi

cat > "$ENV_FILE" <<EOF
# Odoo Project Environment Variables
# Source this file before running scripts: source .env
# Generated by init_env.sh — edit with care.

# =============================================================================
# Project Root
# =============================================================================
PROJECT_ROOT=$PROJECT_ROOT

# =============================================================================
# Odoo Source Configuration
# =============================================================================
ODOO_ROOT=$ODOO_ROOT

# Python runtime (venv with Odoo dependencies)
PYTHON_PATH=$PYTHON_PATH

# =============================================================================
# Project Configuration
# =============================================================================
PROJECT_NAME=$PROJECT_NAME

# =============================================================================
# Database
# =============================================================================
DB_NAME=\${PROJECT_NAME}
EOF

if [[ -n "$DB_HOST" || -n "$DB_PORT" || -n "$DB_USER" || -n "$DB_PASSWORD" ]]; then
    cat >> "$ENV_FILE" <<EOF
DB_HOST=$DB_HOST
DB_PORT=$DB_PORT
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
EOF
else
    cat >> "$ENV_FILE" <<'EOF'

# Optional: Database connection (if not using peer auth)
# DB_HOST=localhost
# DB_USER=odoo
# DB_PASSWORD=odoo
EOF
fi

cat >> "$ENV_FILE" <<EOF

# =============================================================================
# Server
# =============================================================================
HTTP_PORT=$HTTP_PORT
BIN_PATH=$BIN_PATH

# =============================================================================
# Optional Odoo Source Sync Script
# =============================================================================
# Path to a script that refreshes the Odoo source tree (e.g. rsync, git pull).
# Used by fresh.sh / reset_db.sh when --update is passed.
ODOO_SYNC_SCRIPT=$ODOO_SYNC_SCRIPT
EOF

echo "Written: $ENV_FILE"

# ---------------------------------------------------------------------------
# Generate odoo.conf
# ---------------------------------------------------------------------------
if [[ -f "$CONF_FILE" ]] && $FORCE; then
    backup_file "$CONF_FILE"
fi

generate_odoo_conf "$CONF_FILE"
echo "Generated: $CONF_FILE"

# ---------------------------------------------------------------------------
# --venv-create
# ---------------------------------------------------------------------------
if $VENV_CREATE; then
    VENV_DIR="$PROJECT_ROOT/.venv"
    if [[ ! -d "$VENV_DIR" ]]; then
        echo "Creating Python venv at $VENV_DIR..."
        python3 -m venv "$VENV_DIR"
    else
        echo "Venv already exists at $VENV_DIR"
    fi

    REQUIREMENTS="$ODOO_ROOT/odoo/requirements.txt"
    if [[ ! -f "$REQUIREMENTS" ]]; then
        REQUIREMENTS="$ODOO_ROOT/requirements.txt"
    fi
    if [[ -f "$REQUIREMENTS" ]]; then
        echo "Installing requirements from $REQUIREMENTS..."
        "$VENV_DIR/bin/pip" install -r "$REQUIREMENTS"
    else
        echo "Warning: requirements.txt not found at $ODOO_ROOT/odoo/requirements.txt or $ODOO_ROOT/requirements.txt"
    fi

    # Ensure .env PYTHON_PATH points to the new venv
    sed -i "s|PYTHON_PATH=.*|PYTHON_PATH=$VENV_DIR/bin|" "$ENV_FILE"
    echo "Updated PYTHON_PATH in $ENV_FILE"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=== Configuration Summary ==="
echo "  PROJECT_ROOT : $PROJECT_ROOT"
echo "  ODOO_ROOT    : $ODOO_ROOT"
echo "  PYTHON_PATH  : $PYTHON_PATH"
echo "  PROJECT_NAME : $PROJECT_NAME"
echo "  DB_NAME      : $DB_NAME"
echo "  HTTP_PORT    : $HTTP_PORT"
echo ""
echo "Files created in: $ENV_DIR"
echo "Next steps:"
echo "  odoo-run        # Start Odoo server"
echo "  odoo-test       # Run tests"
