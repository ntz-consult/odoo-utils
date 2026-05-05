#!/bin/bash
# Odoo Project Sync - Installer
#
# Usage:
#   ./install.sh [target_project_path]
#
# If no path is provided, the installer will exit and ask for a target folder.

set -e

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Require an explicit target path. Do not default to current directory.
if [ -z "$1" ]; then
    echo "Odoo Project Sync - Installer"
    echo "================================"
    echo ""
    echo "Error: No target path provided."
    echo "Usage: $0 /path/to/your/target-project"
    echo "Please provide the target project directory where files should be installed."
    exit 2
fi

# Resolve target to absolute path
TARGET_DIR="$1"
TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"

echo "Odoo Project Sync - Installer"
echo "=============================="
echo ""
echo "Plugin directory: $PLUGIN_DIR"
echo "Target project:   $TARGET_DIR"
echo ""


# Create .odoo-sync directory structure
echo "Creating .odoo-sync directory structure..."
mkdir -p "$TARGET_DIR/.odoo-sync/config"

# Create studio directory for feature maps
mkdir -p "$TARGET_DIR/studio"

# Create virtual environment for Python dependencies
echo "Creating virtual environment..."
if python3 -c "import venv" 2>/dev/null; then
    python3 -m venv "$TARGET_DIR/.odoo-sync/venv" && VENV_AVAILABLE=true || VENV_AVAILABLE=false
    if [ "$VENV_AVAILABLE" = true ]; then
        echo "  Created: .odoo-sync/venv"
    else
        echo "  Warning: Failed to create virtual environment. Falling back to user install."
    fi
else
    echo "  Warning: python3-venv not available. Install it with: sudo apt install python3-venv"
    echo "  Falling back to user install (may fail on externally managed environments)"
    VENV_AVAILABLE=false
fi

# Copy templates (don't overwrite existing config)
echo "Copying templates..."

if [ ! -f "$TARGET_DIR/.odoo-sync/odoo-instances.json" ]; then
    cp "$PLUGIN_DIR/templates/odoo-instances.json.template" \
       "$TARGET_DIR/.odoo-sync/odoo-instances.json"
    echo "  Created: .odoo-sync/odoo-instances.json"
else
    echo "  Skipped: .odoo-sync/odoo-instances.json (already exists)"
fi

if [ ! -f "$TARGET_DIR/.odoo-sync/config/time_metrics.json" ]; then
    cp "$PLUGIN_DIR/templates/time_metrics.json" \
       "$TARGET_DIR/.odoo-sync/config/time_metrics.json"
    echo "  Created: .odoo-sync/config/time_metrics.json"
else
    echo "  Skipped: .odoo-sync/config/time_metrics.json (already exists)"
fi

# Copy .env.example template (always update to ensure latest config)
cp "$PLUGIN_DIR/templates/.env.example" \
   "$TARGET_DIR/.odoo-sync/.env.example"
echo "  Updated: .odoo-sync/.env.example"

# Copy HowTo to .odoo-sync directory (always overwrite to keep updated)
cp "$PLUGIN_DIR/Odoo_Sync_HowTo.md" "$TARGET_DIR/.odoo-sync/Odoo_Sync_HowTo.md"
echo "  Updated: .odoo-sync/Odoo_Sync_HowTo.md"

# Create CLI launcher (no commands directory - using direct Python execution)
echo "Creating CLI launcher..."

launcher="$TARGET_DIR/.odoo-sync/cli.py"

# Determine Python executable to use
if [ "$VENV_AVAILABLE" = true ]; then
    VENV_PYTHON="$TARGET_DIR/.odoo-sync/venv/bin/python"
else
    VENV_PYTHON="python3"
fi

# Always recreate the launcher to ensure it's up to date
cat > "$launcher" <<EOF
#!/usr/bin/env python3
import os
import sys

PLUGIN_DIR = "$PLUGIN_DIR"
script = os.path.join(PLUGIN_DIR, "shared", "python", "cli.py")

# Execute the real Python CLI
try:
    os.execv("$VENV_PYTHON", ["$VENV_PYTHON", script] + sys.argv[1:])
except Exception as e:
    print(f"Error executing CLI: {e}", file=sys.stderr)
    sys.exit(1)
EOF
chmod +x "$launcher"
echo "  Created: .odoo-sync/cli.py"

# Add .env to .gitignore if git repo exists
echo "Updating .gitignore..."
if [ -d "$TARGET_DIR/.git" ]; then
    if [ -f "$TARGET_DIR/.gitignore" ]; then
        if ! grep -q "^\.odoo-sync/\.env$" "$TARGET_DIR/.gitignore"; then
            echo ".odoo-sync/.env" >> "$TARGET_DIR/.gitignore"
            echo "  Added: .odoo-sync/.env to .gitignore"
        else
            echo "  Skipped: .odoo-sync/.env already in .gitignore"
        fi
        if ! grep -q "^\.odoo-sync/venv$" "$TARGET_DIR/.gitignore"; then
            echo ".odoo-sync/venv" >> "$TARGET_DIR/.gitignore"
            echo "  Added: .odoo-sync/venv to .gitignore"
        else
            echo "  Skipped: .odoo-sync/venv already in .gitignore"
        fi
    else
        cat > "$TARGET_DIR/.gitignore" <<EOF
.odoo-sync/.env
.odoo-sync/venv
EOF
        echo "  Created: .gitignore with .odoo-sync exclusions"
    fi
else
    echo "  Skipped: Not a git repository"
fi

# Install Python dependencies
echo "Installing Python dependencies..."
if command -v python3 >/dev/null 2>&1; then
    if [ "$VENV_AVAILABLE" = true ]; then
        "$TARGET_DIR/.odoo-sync/venv/bin/pip" install -q -r "$PLUGIN_DIR/requirements.txt" && \
            echo "  Installed: All dependencies in virtual environment" || \
            echo "  Warning: pip install failed. Run manually: $TARGET_DIR/.odoo-sync/venv/bin/pip install -r $PLUGIN_DIR/requirements.txt"
    else
        python3 -m pip install -q --user -r "$PLUGIN_DIR/requirements.txt" && \
            echo "  Installed: All dependencies (user install)" || \
            echo "  Warning: pip install failed. Run manually: python3 -m pip install --user -r $PLUGIN_DIR/requirements.txt"
    fi
else
    echo "  Warning: python3 not found. Install requirements manually:"
    if [ "$VENV_AVAILABLE" = true ]; then
        echo "    $TARGET_DIR/.odoo-sync/venv/bin/pip install -r $PLUGIN_DIR/requirements.txt"
    else
        echo "    python3 -m pip install --user -r $PLUGIN_DIR/requirements.txt"
    fi
fi

echo ""
echo "=========================================="
echo "Installation complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Copy .odoo-sync/.env.example to .odoo-sync/.env"
echo "  2. Edit .odoo-sync/.env and add your API keys"
echo "  3. Run: ./.odoo-sync/cli.py init"
echo "  4. Follow the interactive setup wizard"
echo ""
echo "After initialization:"
echo "  - Run: ./.odoo-sync/cli.py status       (verify configuration)"
echo "  - Run: ./.odoo-sync/cli.py extract      (extract customizations)"
echo "  - Run: ./.odoo-sync/cli.py --help       (see all commands)"
echo ""
