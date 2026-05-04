#!/bin/bash

# Install or update Odoo modules in a project database
# Installs if not installed, updates if already installed
#
# Usage:
#   ./install_odoo.sh              # Show help (no action)
#   ./install_odoo.sh --list      # List all modules with status
#   ./install_odoo.sh --all       # Install all uninstalled modules
#   ./install_odoo.sh --install <module_name>   # Install single module
#   ./install_odoo.sh --uninstall <module_name> # Uninstall single module
#   ./install_odoo.sh --update <module_name>    # Update single module
#   ./install_odoo.sh --path <directory>     # Custom addons path
#
# Environment (see .env):
#   ODOO_ROOT    - Odoo source root
#   PROJECT_ROOT - Project addons root
#   PROJECT_NAME - Project db name
#   PYTHON_PATH - Python venv bin directory

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

get_db_name() {
    if [ -f "$CONF_FILE" ]; then
        grep -E "^db_name" "$CONF_FILE" | cut -d'=' -f2 | tr -d ' '
    else
        echo "$PROJECT_NAME"
    fi
}

get_module_state() {
    local module="$1"
    psql "$DB_NAME" -t -c "SELECT state FROM ir_module_module WHERE name = '$module';" 2>/dev/null | tr -d ' '
}

get_all_modules() {
    local path="$1"
    find "$path" -maxdepth 1 -type d ! -name ".*" ! -path "$path" | xargs -I {} basename {} | sort -u
}

module_exists_in_folder() {
    local module="$1"
    [ -d "$ADDONS_PATH/$module" ]
}

list_modules() {
    echo "Modules in $ADDONS_PATH:"
    echo "--------------------------------------------------------------------------------"

    for module in $(get_all_modules "$ADDONS_PATH"); do
        state=$(get_module_state "$module")
        if [ "$state" = "installed" ]; then
            echo "  $module: installed"
        elif [ "$state" = "uninstalled" ]; then
            echo "  $module: uninstalled"
        elif [ "$state" = "to upgrade" ]; then
            echo "  $module: to upgrade"
        elif [ "$state" = "to install" ]; then
            echo "  $module: to install"
        else
            echo "  $module: not found in database"
        fi
    done
}

install_single_module() {
    local module="$1"

    if ! module_exists_in_folder "$module"; then
        echo "Error: Module '$module' not found in $ADDONS_PATH"
        exit 1
    fi

    state=$(get_module_state "$module")
    if [ "$state" = "installed" ]; then
        echo "Module '$module' is already installed. Use --update to upgrade."
        exit 1
    fi

    echo "Installing module: $module"
    echo "--------------------------------------------------------------------------------"
    "$ODOO_BIN" -c "$CONF_FILE" -i "$module" --stop-after-init
    echo ""
    echo "Install complete!"
}

uninstall_single_module() {
    local module="$1"

    state=$(get_module_state "$module")
    if [ "$state" != "installed" ]; then
        echo "Error: Module '$module' is not installed (state: $state)"
        exit 1
    fi

    echo "Uninstalling module: $module"
    echo "--------------------------------------------------------------------------------"
    "$ODOO_BIN" -c "$CONF_FILE" -u "$module" --stop-after-init
    echo ""
    echo "Uninstall complete!"
}

update_single_module() {
    local module="$1"

    if ! module_exists_in_folder "$module"; then
        echo "Error: Module '$module' not found in $ADDONS_PATH"
        exit 1
    fi

    state=$(get_module_state "$module")
    if [ "$state" != "installed" ]; then
        echo "Error: Module '$module' is not installed (state: $state). Use --install first."
        exit 1
    fi

    echo "Updating module: $module"
    echo "--------------------------------------------------------------------------------"
    "$ODOO_BIN" -c "$CONF_FILE" -u "$module" --stop-after-init
    echo ""
    echo "Update complete!"
}

install_all_uninstalled() {
    MODULES_LIST=$(get_all_modules "$ADDONS_PATH")

    TO_INSTALL=""

    for module in $MODULES_LIST; do
        state=$(get_module_state "$module")

        if [ "$state" = "installed" ]; then
            echo "Module $module: installed (skipping)"
        elif [ "$state" = "uninstalled" ] || [ -z "$state" ]; then
            echo "Module $module: uninstalled (will install)"
            TO_INSTALL="${TO_INSTALL:+$TO_INSTALL,}$module"
        fi
    done

    if [ -z "$TO_INSTALL" ]; then
        echo ""
        echo "No uninstalled modules to install."
        exit 0
    fi

    echo ""
    echo "Using configuration: $CONF_FILE"
    echo ""
    echo "Installing modules: $TO_INSTALL"
    echo "--------------------------------------------------------------------------------"
    "$ODOO_BIN" -c "$CONF_FILE" -i "$TO_INSTALL" --stop-after-init
    echo ""
    echo "Install complete!"
}

show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --path <directory>       Custom addons path (default: $PROJECT_ROOT)"
    echo "  --list                   List all modules with their installation status"
    echo "  --all                    Install all uninstalled modules"
    echo "  --install <module_name>  Install a single module"
    echo "  --uninstall <module_name> Uninstall a single module"
    echo "  --update <module_name>   Update a single module (must be already installed)"
    echo "  -h, --help               Show this help message"
    echo ""
    echo "Environment:"
    echo "  ODOO_ROOT=$ODOO_ROOT"
    echo "  PROJECT_ROOT=$PROJECT_ROOT"
    echo "  PROJECT_NAME=$PROJECT_NAME"
    echo "  PYTHON_PATH=$PYTHON_PATH"
    echo ""
    echo "With no arguments, shows this help message."
}

ADDONS_PATH="$PROJECT_ROOT"

DB_NAME=$(get_db_name)

if [ -z "$DB_NAME" ]; then
    echo "Error: Could not find db_name in config file"
    exit 1
fi

ACTION=""
MODULE_ARG=""

while [ $# -gt 0 ]; do
    case "$1" in
        --path)
            ADDONS_PATH="$2"
            shift 2
            ;;
        --list)
            ACTION="list"
            shift
            ;;
        --all)
            ACTION="all"
            shift
            ;;
        --install)
            ACTION="install"
            MODULE_ARG="$2"
            shift 2
            ;;
        --uninstall)
            ACTION="uninstall"
            MODULE_ARG="$2"
            shift 2
            ;;
        --update)
            ACTION="update"
            MODULE_ARG="$2"
            shift 2
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            echo "Error: Unknown option '$1'"
            show_usage
            exit 1
            ;;
    esac
done

case "$ACTION" in
    list)
        list_modules
        ;;
    all)
        install_all_uninstalled
        ;;
    install)
        if [ -z "$MODULE_ARG" ]; then
            echo "Error: --install requires a module name"
            exit 1
        fi
        install_single_module "$MODULE_ARG"
        ;;
    uninstall)
        if [ -z "$MODULE_ARG" ]; then
            echo "Error: --uninstall requires a module name"
            exit 1
        fi
        uninstall_single_module "$MODULE_ARG"
        ;;
    update)
        if [ -z "$MODULE_ARG" ]; then
            echo "Error: --update requires a module name"
            exit 1
        fi
        update_single_module "$MODULE_ARG"
        ;;
    *)
        show_usage
        ;;
esac