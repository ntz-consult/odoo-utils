#!/bin/bash
# python-lint.sh — Unified Python static analysis for Odoo project modules
#
# Usage:
#   ./python-lint.sh                          # lint + dead code + complexity (all modules)
#   ./python-lint.sh --fix                    # auto-fix lint issues
#   ./python-lint.sh --ci                     # CI mode (fail on issues)
#   ./python-lint.sh --module <module_name>   # lint a single module

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

if [ $# -eq 0 ]; then
    echo "Usage: $0 [--fix] [--ci] [--module <module_name>]"
    exit 0
fi

FIX=false
CI=false
MODULE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --fix) FIX=true; shift ;;
        --ci) CI=true; shift ;;
        --module)
            MODULE="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--fix] [--ci] [--module <module_name>]"
            exit 1
            ;;
    esac
done

if [[ -n "$MODULE" ]]; then
    LINT_PATH="$PROJECT_ROOT/$MODULE"
    if [[ ! -d "$LINT_PATH" ]]; then
        echo "Error: Module not found: $LINT_PATH"
        exit 1
    fi
else
    LINT_PATH="$PROJECT_ROOT"
fi

cd "$PROJECT_ROOT"

header() { echo -e "\n\033[1;34m── $1 ──\033[0m"; }

# ──────────────────────────────────────────────────────────
# 1. Import sorting (always run first — can cascade fixes)
# ──────────────────────────────────────────────────────────
header "Ruff: import sorting"
if $FIX; then
    ruff check "$LINT_PATH" --select I --fix
else
    ruff check "$LINT_PATH" --select I
fi

# ──────────────────────────────────────────────────────────
# 2. Full lint
# ──────────────────────────────────────────────────────────
header "Ruff: full lint"
if $FIX; then
    ruff check "$LINT_PATH" --fix
else
    ruff check "$LINT_PATH"
fi

# ──────────────────────────────────────────────────────────
# 3. Dead code (high-confidence only — avoids Odoo noise)
# ──────────────────────────────────────────────────────────
header "Vulture: dead code (min-confidence 80)"
vulture "$LINT_PATH" --min-confidence 80

# ──────────────────────────────────────────────────────────
# 4. Complexity hotspots (functions B grade and above)
# ──────────────────────────────────────────────────────────
header "Radon: complexity hotspots (B+)"
echo "Score key: A=1-5  B=6-10  C=11-20  D=21-30  E=31-40  F=41+"
echo ""
radon cc "$LINT_PATH" -n B

# ──────────────────────────────────────────────────────────
# 5. Maintainability index (low scores = hard to maintain)
# ──────────────────────────────────────────────────────────
header "Radon: maintainability index"
radon mi "$LINT_PATH" -s

if $CI; then
    echo -e "\nCI mode: failing on any issues."
    # vulture exits non-zero if it finds anything (--min-confidence 80 is strict)
fi
