#!/bin/bash
#
# Configure Odoo settings after module installation.
# Applies res.config.settings fields via odoo-bin shell.
#
# Usage:
#   ./configure_settings.sh --db <database> --modules <mod1,mod2>
#   ./configure_settings.sh --db <database> --modules <mod1,mod2> --non-interactive
#
# Environment (see .env in current directory):
#   ODOO_ROOT    - Odoo source root
#   PYTHON_PATH  - Python venv bin directory

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

DB_NAME="$PROJECT_NAME"
MODULES=""
NON_INTERACTIVE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --db)
            DB_NAME="$2"
            shift 2
            ;;
        --modules)
            MODULES="$2"
            shift 2
            ;;
        --non-interactive)
            NON_INTERACTIVE=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Helper to check if a module is in the installed list
module_installed() {
    local mod="$1"
    [[ ",$MODULES," == *",$mod,"* ]]
}

# Helper for Y/n prompt
prompt_yes_no() {
    local prompt="$1"
    local choice
    if [ "$NON_INTERACTIVE" = true ] || ! [ -t 0 ]; then
        return 0  # Default to Yes
    fi
    read -r -p "$prompt [Y/n]: " choice
    [[ -z "$choice" || "$choice" =~ ^[Yy]$ ]]
}

# Build associative array of settings to enable
declare -A SETTINGS

# Stock settings
if module_installed "stock"; then
    if [ "$NON_INTERACTIVE" = false ] && [ -t 0 ]; then
        echo ""
        echo "Configure Stock settings:"
    fi
    if prompt_yes_no "  Enable Packages"; then
        SETTINGS["group_stock_tracking_lot"]=True
    fi
    if prompt_yes_no "  Enable Variants"; then
        SETTINGS["group_product_variant"]=True
    fi
    if prompt_yes_no "  Enable Units of Measure & Packagings"; then
        SETTINGS["group_uom"]=True
    fi
    if prompt_yes_no "  Enable Storage Locations"; then
        SETTINGS["group_stock_multi_locations"]=True
    fi
    if prompt_yes_no "  Enable Multi-Step Routes"; then
        SETTINGS["group_stock_adv_location"]=True
    fi
    if prompt_yes_no "  Enable Lots & Serial Numbers"; then
        SETTINGS["group_stock_production_lot"]=True
    fi
fi

# Sale settings
if module_installed "sale_management" || module_installed "sale"; then
    if [ "$NON_INTERACTIVE" = false ] && [ -t 0 ]; then
        echo ""
        echo "Configure Sales settings:"
    fi
    if prompt_yes_no "  Enable Variant Grid Entry"; then
        SETTINGS["module_sale_product_matrix"]=True
    fi
fi

# Purchase settings
if module_installed "purchase"; then
    if [ "$NON_INTERACTIVE" = false ] && [ -t 0 ]; then
        echo ""
        echo "Configure Purchase settings:"
    fi
    if prompt_yes_no "  Enable Variant Grid Entry"; then
        SETTINGS["module_purchase_product_matrix"]=True
    fi
fi

# MRP settings
if module_installed "mrp"; then
    if [ "$NON_INTERACTIVE" = false ] && [ -t 0 ]; then
        echo ""
        echo "Configure Manufacturing settings:"
    fi
    if prompt_yes_no "  Enable Work Orders"; then
        SETTINGS["group_mrp_routings"]=True
    fi
fi

# If no settings to apply, exit
if [ ${#SETTINGS[@]} -eq 0 ]; then
    echo "No settings to configure."
    exit 0
fi

# Build Python script
PYTHON_SCRIPT="settings = env['res.config.settings'].create({"
for key in "${!SETTINGS[@]}"; do
    PYTHON_SCRIPT+="
    '$key': True,"
done
PYTHON_SCRIPT+="
})
settings.execute()
env.cr.commit()
print('Settings applied successfully.')
"

echo ""
echo "Applying settings..."

# Run via odoo-bin shell (no-http avoids starting the web server)
"$ODOO_BIN" shell -c "$CONF_FILE" -d "$DB_NAME" --no-http <<< "$PYTHON_SCRIPT"
