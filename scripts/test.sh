#!/bin/bash

# Test utility for Odoo modules
#
# Usage:
#   odoo-test --list                        # List all installed modules
#   odoo-test --list-tests <mod> [file]      # List test files and classes
#   odoo-test --test <mod> [file:class.test]   # Run Python tests
#   odoo-test --testall                     # Run all Python tests for all modules
#   odoo-test --test-js [mod]               # Run JS unit tests (fast, no module update)
#   odoo-test --test-js-all                 # Run JS unit tests for all modules (full suite)
#   odoo-test --log [filename]              # Log output to file
#   odoo-test --path <directory>            # Custom addons path
#
# Environment (see .env in current directory):
#   ODOO_ROOT    - Odoo source root
#   PROJECT_ROOT - Project addons root
#   PROJECT_NAME - Project db name
#   PYTHON_PATH  - Python venv bin directory

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

LOG_FILE="$ENV_DIR/${PROJECT_NAME}_test.log"

ADDONS_PATH="$PROJECT_ROOT"

discover_modules() {
    find "$ADDONS_PATH" -maxdepth 1 -type d ! -name ".*" ! -path "$ADDONS_PATH" | xargs -I {} basename {} | sort | tr '\n' ' '
}

ALL_MODULES=$(discover_modules)

usage() {
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  --path <directory>             Custom addons path (default: $PROJECT_ROOT)"
    echo "  --list                       List all installed modules"
    echo "  --list-tests <mod> [file]    List Python test files and classes"
    echo "  --test <mod> [file:class.test] Run Python tests"
    echo "  --testall                    Run all Python tests for all modules"
    echo "  --test-js [mod]              Run JS unit tests for project module(s)"
    echo "  --test-js-all                Run JS unit tests for all modules"
    echo "  --log [filename]              Log output to file (default: ${PROJECT_NAME}_test.log in current dir)"
    echo "  --help                        Show this help message"
    echo ""
    echo "Environment:"
    echo "  ODOO_ROOT=$ODOO_ROOT"
    echo "  PROJECT_ROOT=$PROJECT_ROOT"
    echo "  PROJECT_NAME=$PROJECT_NAME"
    echo "  PYTHON_PATH=$PYTHON_PATH"
    echo ""
    echo "Available modules: $ALL_MODULES"
    echo ""
    echo "Examples:"
    echo "  $0 --list-tests mymodule                          # Show all files and classes"
    echo "  $0 --list-tests mymodule test_unit.py           # Show classes in file"
    echo "  $0 --test mymodule                               # Run all Python tests in module"
    echo "  $0 --test mymodule TestClass                    # Run all tests in class"
    echo "  $0 --test mymodule test_unit.py:TestClass         # Run tests in specific class"
    echo "  $0 --test mymodule test_unit.py:TestClass.test_001 # Run specific test"
    echo "  $0 --test-js                                   # Run JS unit tests (project modules only)"
    echo "  $0 --test-js mymodule                          # Run JS unit tests for one module"
    echo "  $0 --test-js-all                               # Run JS unit tests for all modules (full suite, SLOW)"
    exit 0
}

get_db_name() {
    if [ -f "$CONF_FILE" ]; then
        grep -E "^db_name" "$CONF_FILE" | cut -d'=' -f2 | tr -d ' '
    else
        echo "$PROJECT_NAME"
    fi
}

# ---------------------------------------------------------------------------
# HOOT hash helpers — compute hashes for JS unit-test filtering so that
# --test-js only runs tests from the requested module(s).
# ---------------------------------------------------------------------------

file_to_hoot_path() {
    local rel_path="$1"
    # e.g. mymodule/static/tests/foo.test.js -> @mymodule/foo
    local path="${rel_path%.test.js}"
    path="${path//\/static\/tests\//\/}"
    echo "@${path}"
}

build_hoot_filter_for_module() {
    local mod="$1"
    local mod_path="$PROJECT_ROOT/$mod"
    local filter=""
    while IFS= read -r -d '' file; do
        local rel_path="${file#$PROJECT_ROOT/}"
        local hoot_path
        hoot_path=$(file_to_hoot_path "$rel_path")
        if [ -n "$filter" ]; then
            filter="${filter},${hoot_path}"
        else
            filter="${hoot_path}"
        fi
    done < <(find "$mod_path" -path "*/static/tests/*.test.js" -print0 2>/dev/null)
    echo "$filter"
}

COMMAND=""
MODULE=""
TEST=""
FILE=""
USE_LOGFILE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --path)
            ADDONS_PATH="$2"
            ALL_MODULES=$(discover_modules)
            shift 2
            ;;
        --list)
            COMMAND="list"
            shift
            ;;
        --list-tests)
            COMMAND="list-tests"
            if [[ $# -gt 1 && ! "$2" =~ ^-- ]]; then
                MODULE="$2"
                shift 2
                if [[ $# -gt 0 && ! "$1" =~ ^-- ]]; then
                    FILE="$1"
                    shift
                fi
            else
                shift
            fi
            ;;
        --test)
            COMMAND="test"
            if [[ $# -gt 1 && ! "$2" =~ ^-- ]]; then
                MODULE="$2"
                shift 2
                if [[ $# -gt 0 && ! "$1" =~ ^-- ]]; then
                    TEST="$1"
                    shift
                fi
            else
                shift
            fi
            ;;
        --testall)
            COMMAND="testall"
            shift
            ;;
        --test-js)
            COMMAND="test-js"
            if [[ $# -gt 1 && ! "$2" =~ ^-- ]]; then
                MODULE="$2"
                shift 2
            else
                shift
            fi
            ;;
        --test-js-all)
            COMMAND="test-js-all"
            shift
            ;;
        --log)
            USE_LOGFILE=true
            if [[ $# -gt 1 && ! "$2" =~ ^-- ]]; then
                LOG_FILE="$2"
                shift 2
            else
                shift
            fi
            ;;
        --help|-h)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

if [[ -z "$COMMAND" ]]; then
    echo "Error: No command specified"
    usage
fi

run_test_with_log() {
    if [[ "$USE_LOGFILE" == "true" ]]; then
        rm -f "$LOG_FILE"
        echo "Running tests with logging to: $LOG_FILE (failures only)"
        echo ""
        local in_traceback=false
        local capture_next=false
        "$@" 2>&1 | while IFS= read -r line; do
            echo "$line"
            if [[ "$line" =~ (FAIL|FAILED|ERROR|AssertionError|Traceback) ]]; then
                echo "$line" >> "$LOG_FILE"
                in_traceback=true
                capture_next=true
            elif [[ "$in_traceback" == "true" && "$line" =~ ^[[:space:]] ]]; then
                echo "$line" >> "$LOG_FILE"
            elif [[ "$capture_next" == "true" && ! "$line" =~ ^[[:space:]] ]]; then
                if [[ "$line" =~ ^(test_|=) ]]; then
                    echo "$line" >> "$LOG_FILE"
                fi
                in_traceback=false
                capture_next=false
            else
                in_traceback=false
            fi
        done
    else
        "$@"
    fi
}

DB_NAME=$(get_db_name)

if [[ -z "$DB_NAME" ]]; then
    echo "Error: Could not find db_name in config file"
    exit 1
fi

MODULES_SQL_LIST=$(echo "$ALL_MODULES" | tr ' ' ',' | sed "s/[^,]*/'\&'/g")

case $COMMAND in
    list)
        echo "Installed modules in database: $DB_NAME"
        echo "================================================================================"
        echo ""
        echo "All installed modules:"
        psql "$DB_NAME" -c "SELECT name, state FROM ir_module_module WHERE state = 'installed' ORDER BY name;" 2>/dev/null | grep -E "^\s+[a-z_]+\s+\|" | head -50
        echo ""
        echo "Modules in $ADDONS_PATH:"
        echo "--------------------------------------------------------------------------------"
        psql "$DB_NAME" -c "SELECT name, state FROM ir_module_module WHERE name IN ($MODULES_SQL_LIST) ORDER BY name;" 2>/dev/null | tail -n +3 | head -n -1
        ;;

    list-tests)
        if [[ -z "$MODULE" ]]; then
            echo "Error: Module name required for --list-tests"
            exit 1
        fi

        MODULE_PATH="$ADDONS_PATH/$MODULE"
        if [[ ! -d "$MODULE_PATH" ]]; then
            echo "Error: Module directory not found: $MODULE_PATH"
            exit 1
        fi

        if [[ -n "$FILE" ]]; then
            TEST_FILE="$MODULE_PATH/tests/$FILE"
            if [[ ! -f "$TEST_FILE" ]]; then
                echo "Error: Test file not found: tests/$FILE"
                exit 1
            fi

            echo "Tests in file: tests/$FILE"
            echo "================================================================================"

            grep -E "^class.*Test|^\s+def test_" "$TEST_FILE" | while read -r line; do
                if [[ "$line" =~ ^class[[:space:]]+([A-Za-z0-9_]+) ]]; then
                    echo "Class: ${BASH_REMATCH[1]}"
                elif [[ "$line" =~ def[[:space:]]+(test_[A-Za-z0-9_]+) ]]; then
                    echo "  - ${BASH_REMATCH[1]}"
                fi
            done
        else
            echo "Test files and classes in module: $MODULE"
            echo "================================================================================"

            find "$MODULE_PATH" -name "test_*.py" -type f | sort | while read -r test_file; do
                rel_path=$(echo "$test_file" | sed "s|$MODULE_PATH/||")
                echo "File: $rel_path"

                grep -E "^class.*Test" "$test_file" | while read -r line; do
                    if [[ "$line" =~ ^class[[:space:]]+([A-Za-z0-9_]+) ]]; then
                        echo "  Class: ${BASH_REMATCH[1]}"
                    fi
                done
                echo ""
            done

            if [[ ! $(find "$MODULE_PATH" -name "test_*.py" -type f 2>/dev/null) ]]; then
                echo "No test files found in $MODULE"
            fi
        fi
        ;;

    test)
        if [[ -z "$MODULE" ]]; then
            echo "Error: Module name required for --test"
            exit 1
        fi

        if [[ -n "$TEST" ]]; then
            echo "Running test: $TEST in module: $MODULE"
            echo "================================================================================"

            if [[ "$TEST" =~ ^([^:]+)\.py:([^:]+)\.(.+)$ ]]; then
                FILE="${BASH_REMATCH[1]}.py"
                CLASS="${BASH_REMATCH[2]}"
                METHOD="${BASH_REMATCH[3]}"
                TEST_TAG="/${MODULE}:${CLASS}.${METHOD}"
            elif [[ "$TEST" =~ ^([^:]+)\.py:([^:]+)$ ]]; then
                FILE="${BASH_REMATCH[1]}.py"
                CLASS="${BASH_REMATCH[2]}"
                TEST_TAG="/${MODULE}:${CLASS}"
            elif [[ "$TEST" =~ ^([^:]+)\.py$ ]]; then
                FILE="$TEST"
                MODULE_PATH="$ADDONS_PATH/$MODULE"
                TEST_FILE="$MODULE_PATH/tests/$FILE"

                if [[ ! -f "$TEST_FILE" ]]; then
                    echo "Error: Test file not found: tests/$FILE"
                    exit 1
                fi

                CLASSES=$(grep -E "^class.*Test" "$TEST_FILE" | sed -E 's/class +([A-Za-z0-9_]+).*/\1/')

                if [[ -z "$CLASSES" ]]; then
                    echo "Error: No test classes found in tests/$FILE"
                    exit 1
                fi

                TEST_TAG=""
                for CLASS in $CLASSES; do
                    if [[ -n "$TEST_TAG" ]]; then
                        TEST_TAG="${TEST_TAG},/${MODULE}:${CLASS}"
                    else
                        TEST_TAG="/${MODULE}:${CLASS}"
                    fi
                done
            elif [[ "$TEST" =~ ^([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)$ ]]; then
                CLASS="${BASH_REMATCH[1]}"
                METHOD="${BASH_REMATCH[2]}"
                TEST_TAG="/${MODULE}:${CLASS}.${METHOD}"
            else
                TEST_TAG="/${MODULE}:${TEST}"
            fi

            run_test_with_log "$ODOO_BIN" -c "$CONF_FILE" -u "$MODULE" --test-enable --test-tags="$TEST_TAG" --stop-after-init
        else
            echo "Running all tests for module: $MODULE"
            echo "================================================================================"
            run_test_with_log "$ODOO_BIN" -c "$CONF_FILE" -u "$MODULE" --test-enable --test-tags="/${MODULE}" --stop-after-init
        fi
        ;;

    testall)
        echo "Running all tests for all modules"
        echo "Modules: $ALL_MODULES"
        echo "================================================================================"
        ALL_MODULES_LIST=$(echo "$ALL_MODULES" | tr ' ' ',')
        ALL_TAGS=$(echo "$ALL_MODULES" | tr ' ' '\n' | sed 's|^|/|' | tr '\n' ',' | sed 's/,$//')
        run_test_with_log "$ODOO_BIN" -c "$CONF_FILE" -u "$ALL_MODULES_LIST" --test-enable --test-tags="$ALL_TAGS" --stop-after-init
        ;;

    test-js)
        if [[ -n "$MODULE" ]]; then
            echo "Running JS unit tests for module: $MODULE"
            echo "================================================================================"
            HOOT_FILTER=$(build_hoot_filter_for_module "$MODULE")
            if [[ -z "$HOOT_FILTER" ]]; then
                echo "Warning: No .test.js files found in $MODULE/static/tests/"
                echo "Falling back to full desktop suite."
                TAG="-at_install,web:WebSuite.test_unit_desktop"
            else
                TAG="-at_install,web:WebSuite.test_unit_desktop[${HOOT_FILTER}]"
            fi
            run_test_with_log "$ODOO_BIN" -c "$CONF_FILE" --test-enable --test-tags="$TAG" --stop-after-init
        else
            echo "Running JS unit tests for all project modules"
            echo "================================================================================"
            ALL_FILTER=""
            for mod in $ALL_MODULES; do
                mod_filter=$(build_hoot_filter_for_module "$mod")
                if [[ -n "$mod_filter" ]]; then
                    if [[ -n "$ALL_FILTER" ]]; then
                        ALL_FILTER="${ALL_FILTER},${mod_filter}"
                    else
                        ALL_FILTER="${mod_filter}"
                    fi
                fi
            done
            if [[ -z "$ALL_FILTER" ]]; then
                echo "Warning: No .test.js files found in any project module."
                TAG="-at_install,web:WebSuite.test_unit_desktop"
            else
                TAG="-at_install,web:WebSuite.test_unit_desktop[${ALL_FILTER}]"
            fi
            run_test_with_log "$ODOO_BIN" -c "$CONF_FILE" --test-enable --test-tags="$TAG" --stop-after-init
        fi
        ;;

    test-js-all)
        echo "Running JS unit tests for all modules"
        echo "Modules: $ALL_MODULES"
        echo "================================================================================"
        ALL_MODULES_LIST=$(echo "$ALL_MODULES" | tr ' ' ',')
        run_test_with_log "$ODOO_BIN" -c "$CONF_FILE" --test-enable --test-tags="-at_install,web:WebSuite.test_unit_desktop" --stop-after-init
        ;;

    *)
        echo "Unknown command: $COMMAND"
        usage
        ;;
esac

echo ""
echo "Done!"
