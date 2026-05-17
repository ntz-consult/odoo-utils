#!/bin/bash
# init-direct.sh — Add odoo-direct credentials to .env in the current directory
#
# Usage:
#   odoo-direct-init              # Interactive prompts for odoo-direct credentials
#   odoo-direct-init --force      # Overwrite existing odoo-direct vars (backs up .env)
#
# IMPORTANT: Operates on .env in the CURRENT DIRECTORY ($PWD).
#   Creates .env if it does not exist. Works standalone or alongside odoo-init-env.

set -euo pipefail

ENV_DIR="$(pwd)"
ENV_FILE="$ENV_DIR/.env"

FORCE=false

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=true ;;
        *)
            echo "Unknown option: $arg"
            echo "Usage: $0 [--force]"
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Load existing .env for defaults (optional — works standalone)
# ---------------------------------------------------------------------------
DEFAULT_URL=""
DEFAULT_DB=""
DEFAULT_USER=""
DEFAULT_API_KEY=""

if [[ -f "$ENV_FILE" ]]; then
    # Source only the ODOO_DIRECT_* and DB_NAME vars we care about
    while IFS='=' read -r key value; do
        # Remove leading/trailing whitespace
        key="$(echo "$key" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
        value="$(echo "$value" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
        case "$key" in
            ODOO_DIRECT_URL) DEFAULT_URL="$value" ;;
            ODOO_DIRECT_DB) DEFAULT_DB="$value" ;;
            ODOO_DIRECT_USER) DEFAULT_USER="$value" ;;
            ODOO_DIRECT_API_KEY) DEFAULT_API_KEY="$value" ;;
            DB_NAME) [[ -z "$DEFAULT_DB" ]] && DEFAULT_DB="$value" ;;
        esac
    done < "$ENV_FILE"
fi

# ---------------------------------------------------------------------------
# Check if odoo-direct vars already exist
# ---------------------------------------------------------------------------
HAS_DIRECT_VARS=false
if [[ -f "$ENV_FILE" ]] && grep -qE "^ODOO_DIRECT_" "$ENV_FILE" 2>/dev/null; then
    HAS_DIRECT_VARS=true
fi

if $HAS_DIRECT_VARS && ! $FORCE; then
    echo "Error: odoo-direct credentials already exist in $ENV_FILE."
    echo "Use --force to overwrite (a backup will be created)."
    exit 1
fi

# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------
echo "=== Odoo Direct Credentials Setup ==="
echo ""
echo "Enter the connection details for odoo-direct (JSON-RPC):"
echo ""

ODOO_DIRECT_URL=$(prompt "Odoo instance URL" "$DEFAULT_URL")
ODOO_DIRECT_DB=$(prompt "Database name" "$DEFAULT_DB")
ODOO_DIRECT_USER=$(prompt "Username (email)" "$DEFAULT_USER")
ODOO_DIRECT_API_KEY=$(prompt "API key" "$DEFAULT_API_KEY")

# Validate
if [[ -z "$ODOO_DIRECT_URL" || -z "$ODOO_DIRECT_DB" || -z "$ODOO_DIRECT_USER" || -z "$ODOO_DIRECT_API_KEY" ]]; then
    echo "Error: All fields are required."
    exit 1
fi

# ---------------------------------------------------------------------------
# Backup and strip old vars
# ---------------------------------------------------------------------------
if [[ -f "$ENV_FILE" ]]; then
    if $FORCE && $HAS_DIRECT_VARS; then
        cp "$ENV_FILE" "$ENV_FILE.bak"
        echo "Backed up: $ENV_FILE.bak"
    fi

    # Remove any existing ODOO_DIRECT_* lines
    tmpfile=$(mktemp)
    grep -vE "^ODOO_DIRECT_" "$ENV_FILE" > "$tmpfile" || true
    mv "$tmpfile" "$ENV_FILE"
fi

# ---------------------------------------------------------------------------
# Append new section
# ---------------------------------------------------------------------------
cat >> "$ENV_FILE" <<EOF

# =============================================================================
# Odoo Direct (JSON-RPC Credentials)
# =============================================================================
# Used by odoo-direct for remote database access.
# Get an API key in Odoo: Settings → Users → Your User → Account Security → API Keys
ODOO_DIRECT_URL=$ODOO_DIRECT_URL
ODOO_DIRECT_DB=$ODOO_DIRECT_DB
ODOO_DIRECT_USER=$ODOO_DIRECT_USER
ODOO_DIRECT_API_KEY=$ODOO_DIRECT_API_KEY
EOF

echo ""
echo "Updated: $ENV_FILE"
echo ""
echo "=== Odoo Direct Configuration Summary ==="
echo "  URL      : $ODOO_DIRECT_URL"
echo "  Database : $ODOO_DIRECT_DB"
echo "  User     : $ODOO_DIRECT_USER"
echo ""
echo "Test the connection:"
echo "  odoo-direct --test"
