#!/bin/bash

# Test utility for Odoo modules
#
# Usage:
#   odoo-test --list                        # List all installed modules
#   odoo-test --list-tests <mod> [file]    # List test files and classes
#   odoo-test --test <mod> [file:class.test]   # Run Python tests
#   odoo-test --testall                     # Run all Python tests for all modules
#   odoo-test --test-js [mod]               # Run JS unit tests (fast, no module update)
#   odoo-test --test-js-all                 # Run JS unit tests for all modules (full suite)
#   odoo-test --log [filename]              # Log output to file
#   odoo-test --path <directory>            # Custom module discovery path and explicit Odoo addons path override
#   odoo-test --agent                       # Suppress wrapper output for AI agents
#   odoo-test --conf <file.conf>            # Use custom config file
#   odoo-test --upgrade                     # Upgrade tested Python module(s) before tests
#   odoo-test --test-http-port <port>       # Override test HTTP port
#   odoo-test --test-gevent-port <port>     # Override test gevent port
#
# Configuration comes from <git-root>/.odoo/.
#   ODOO_ROOT    - Odoo source root
#   PROJECT_ROOT - Project addons root
#   DB_NAME      - Project database name
#   PYTHON_PATH  - Python venv bin directory
#   TEST_HTTP_PORT   - Optional dedicated HTTP port for test runs
#   TEST_GEVENT_PORT - Optional dedicated gevent port for test runs
#   TEST_PORT_RANGE_START - Optional first HTTP port for automatic allocation
#   TEST_PORT_RANGE_END   - Optional last port for automatic allocation

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

LOG_FILE="$ENV_DIR/${DB_NAME}_test.log"

ADDONS_PATH="$PROJECT_ROOT"
ADDONS_PATH_OVERRIDDEN=false
ADDONS_ARGS=()

discover_modules() {
    find "$ADDONS_PATH" -maxdepth 1 -type d ! -name ".*" ! -path "$ADDONS_PATH" | xargs -I {} basename {} | sort | tr '\n' ' '
}

ALL_MODULES=$(discover_modules)

usage() {
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  --path <directory>             Custom module discovery path and explicit Odoo addons path override"
    echo "  --list                       List all installed modules"
    echo "  --list-tests <mod> [file]    List Python test files and classes"
    echo "  --test <mod> [file:class.test] Run Python tests"
    echo "  --testall                    Run all Python tests for all modules"
    echo "  --test-js [mod]              Run JS unit tests for project module(s)"
    echo "  --test-js-all                Run JS unit tests for all modules"
    echo "  --log [filename]              Log output to file (default: utils/${DB_NAME}_test.log)"
    echo "  --agent                        Suppress wrapper output for AI agents"
    echo "  --conf <file.conf>            Use custom config file"
    echo "  --upgrade                     Upgrade tested Python module(s) before tests"
    echo "  --test-http-port <port>       Override HTTP port used by Odoo's test server"
    echo "  --test-gevent-port <port>     Override gevent port used by Odoo's test server"
    echo "  --help                        Show this help message"
    echo ""
    echo "Environment:"
    echo "  ODOO_ROOT=$ODOO_ROOT"
    echo "  PROJECT_ROOT=$PROJECT_ROOT"
    echo "  DB_NAME=$DB_NAME"
    echo "  PYTHON_PATH=$PYTHON_PATH"
    echo "  TEST_HTTP_PORT=${TEST_HTTP_PORT:-$(( ${HTTP_PORT:-8069} + 1000 ))}"
    echo "  TEST_GEVENT_PORT=${TEST_GEVENT_PORT:-auto}"
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
    echo "  $0 --test mymodule --agent                     # Run tests, suppress wrapper output"
    echo "  $0 --test mymodule --upgrade                   # Upgrade module before running tests"
    echo "  $0 --test mymodule --test-http-port 9096       # Run tests on a dedicated HTTP port"
    exit 0
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
    local mod_path="$ADDONS_PATH/$mod"
    local filter=""
    while IFS= read -r -d '' file; do
        local rel_path="${file#$ADDONS_PATH/}"
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
AGENT_MODE=false
CUSTOM_CONF=""
UPGRADE_MODULES=false
TEST_HTTP_PORT_ARG=""
TEST_GEVENT_PORT_ARG=""
ODOO_TEST_ARGS=()
TEST_PORT_LOCK_PATH=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --path)
            ADDONS_PATH="$2"
            ADDONS_PATH_OVERRIDDEN=true
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
        --agent)
            AGENT_MODE=true
            shift
            ;;
        --conf)
            CUSTOM_CONF="$2"
            shift 2
            ;;
        --upgrade)
            UPGRADE_MODULES=true
            shift
            ;;
        --test-http-port)
            TEST_HTTP_PORT_ARG="$2"
            shift 2
            ;;
        --test-gevent-port)
            TEST_GEVENT_PORT_ARG="$2"
            shift 2
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

if [[ -n "$CUSTOM_CONF" ]]; then
    CONF_FILE="$CUSTOM_CONF"
fi

if [[ "$ADDONS_PATH_OVERRIDDEN" == "true" ]]; then
    ADDONS_ARGS=(--addons-path "$ADDONS_PATH")
fi

if [[ -z "$COMMAND" ]]; then
    echo "Error: No command specified"
    usage
fi

if [[ "$UPGRADE_MODULES" == "true" && "$COMMAND" != "test" && "$COMMAND" != "testall" ]]; then
    echo "Error: --upgrade is only supported with --test and --testall"
    exit 1
fi

run_test_with_log() {
    if [[ "$USE_LOGFILE" == "true" ]]; then
        rm -f "$LOG_FILE"
        if [[ "$AGENT_MODE" != "true" ]]; then
            echo "Logging test output to: $LOG_FILE"
        fi
        "$@" --logfile="$LOG_FILE"
    else
        "$@"
    fi
}

is_valid_port() {
    local port="$1"
    [[ "$port" =~ ^[0-9]+$ ]] && (( port >= 1 && port <= 65535 ))
}

port_available() {
    local port="$1"
    if ! command -v python3 >/dev/null 2>&1; then
        return 0
    fi
    python3 - "$port" <<'PY'
import socket
import sys

port = int(sys.argv[1])
for host in ("127.0.0.1", "0.0.0.0"):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except PermissionError:
        # Some sandboxes block socket creation. In that case, let Odoo try the
        # dedicated test port instead of looping through every possible port.
        sys.exit(0)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except PermissionError:
        sys.exit(0)
    except OSError:
        sys.exit(1)
    finally:
        sock.close()
sys.exit(0)
PY
}

release_test_port_lock() {
    if [[ -n "${TEST_PORT_LOCK_PATH:-}" && -d "$TEST_PORT_LOCK_PATH" ]]; then
        rm -rf "$TEST_PORT_LOCK_PATH"
        TEST_PORT_LOCK_PATH=""
    fi
}

reserve_test_port_pair() {
    local http_port="$1"
    local gevent_port="$2"
    local lock_namespace
    local lock_root
    local lock_path

    lock_namespace=$(printf "%s" "$DB_NAME" | tr -c 'A-Za-z0-9_.-' '_')
    lock_root="${TMPDIR:-/tmp}/odoo-test-ports-${lock_namespace}"
    lock_path="$lock_root/${http_port}-${gevent_port}.lock"
    mkdir -p "$lock_root"

    if mkdir "$lock_path" 2>/dev/null; then
        printf "%s\n" "$$" > "$lock_path/pid"
        TEST_PORT_LOCK_PATH="$lock_path"
        trap release_test_port_lock EXIT INT TERM
        return 0
    fi

    if [[ -f "$lock_path/pid" ]]; then
        local lock_pid
        lock_pid=$(cat "$lock_path/pid" 2>/dev/null || true)
        if [[ ! "$lock_pid" =~ ^[0-9]+$ ]] || ! kill -0 "$lock_pid" 2>/dev/null; then
            rm -rf "$lock_path"
            if mkdir "$lock_path" 2>/dev/null; then
                printf "%s\n" "$$" > "$lock_path/pid"
                TEST_PORT_LOCK_PATH="$lock_path"
                trap release_test_port_lock EXIT INT TERM
                return 0
            fi
        fi
    fi

    return 1
}

resolve_test_ports() {
    local http_port="${TEST_HTTP_PORT_ARG:-${TEST_HTTP_PORT:-}}"
    local gevent_port="${TEST_GEVENT_PORT_ARG:-${TEST_GEVENT_PORT:-}}"
    local fixed_ports=false
    local live_http_port="${HTTP_PORT:-8069}"
    local range_start="${TEST_PORT_RANGE_START:-}"
    local range_end="${TEST_PORT_RANGE_END:-}"

    if [[ -n "$TEST_HTTP_PORT_ARG" || -n "$TEST_GEVENT_PORT_ARG" ]]; then
        fixed_ports=true
    fi

    if [[ -z "$http_port" ]]; then
        if is_valid_port "$live_http_port" && (( live_http_port <= 64535 )); then
            http_port=$(( live_http_port + 1000 ))
        else
            http_port=9069
        fi
    fi

    if [[ "$fixed_ports" != "true" && ( -n "$range_start" || -n "$range_end" ) ]]; then
        range_start="${range_start:-$http_port}"
        range_end="${range_end:-65535}"
        if ! is_valid_port "$range_start"; then
            echo "Error: Invalid test port range start: $range_start"
            exit 1
        fi
        if ! is_valid_port "$range_end"; then
            echo "Error: Invalid test port range end: $range_end"
            exit 1
        fi
        if (( range_start >= range_end )); then
            echo "Error: Test port range must contain at least one HTTP/gevent pair."
            exit 1
        fi
        http_port="$range_start"
        gevent_port=$(( http_port + 1 ))
    else
        if [[ -z "$gevent_port" ]]; then
            gevent_port=$(( http_port + 1 ))
            if (( gevent_port > 65535 )); then
                echo "Error: Test gevent port would exceed 65535. Set TEST_GEVENT_PORT or use --test-gevent-port."
                exit 1
            fi
        fi
        range_end=65535
    fi

    if ! is_valid_port "$http_port"; then
        echo "Error: Invalid test HTTP port: $http_port"
        exit 1
    fi

    if ! is_valid_port "$gevent_port"; then
        echo "Error: Invalid test gevent port: $gevent_port"
        exit 1
    fi

    if [[ "$http_port" == "$gevent_port" ]]; then
        echo "Error: Test HTTP and gevent ports must be different."
        exit 1
    fi

    if [[ "$fixed_ports" != "true" ]]; then
        local original_http_port="$http_port"
        local original_gevent_port="$gevent_port"
        while true; do
            if reserve_test_port_pair "$http_port" "$gevent_port"; then
                if port_available "$http_port" && port_available "$gevent_port"; then
                    break
                fi
                release_test_port_lock
            fi

            http_port=$(( http_port + 2 ))
            gevent_port=$(( gevent_port + 2 ))
            if (( gevent_port > range_end )); then
                echo "Error: Could not find available automatic test ports."
                exit 1
            fi
        done

        if [[ "$http_port" != "$original_http_port" && "$AGENT_MODE" != "true" ]]; then
            echo "Test ports $original_http_port/$original_gevent_port are busy; using $http_port/$gevent_port."
        fi
    else
        if ! port_available "$http_port"; then
            echo "Error: Test HTTP port $http_port is already in use."
            exit 1
        fi
        if ! port_available "$gevent_port"; then
            echo "Error: Test gevent port $gevent_port is already in use."
            exit 1
        fi
    fi

    # The pair must come from this project's test pool (scripts/ports.py).
    if ! odoo_enforce_port_pool "$HTTP_PORT" "" "$http_port" "$gevent_port"; then
        release_test_port_lock
        exit 1
    fi

    ODOO_TEST_ARGS=(
        --http-port "$http_port"
        --gevent-port "$gevent_port"
        --workers 0
        --max-cron-threads 0
    )
}

run_odoo_test() {
    if [[ ${#ODOO_TEST_ARGS[@]} -eq 0 ]]; then
        resolve_test_ports
    fi
    run_test_with_log "$ODOO_BIN" -c "$CONF_FILE" "${ODOO_TEST_ARGS[@]}" --no-http "$@"
}

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
            if [[ "$AGENT_MODE" != "true" ]]; then
                echo "Running test: $TEST in module: $MODULE"
                echo "================================================================================"
            fi

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

            UPGRADE_ARGS=()
            if [[ "$UPGRADE_MODULES" == "true" ]]; then
                UPGRADE_ARGS=(-u "$MODULE")
            fi
            run_odoo_test -d "$DB_NAME" "${ADDONS_ARGS[@]}" "${UPGRADE_ARGS[@]}" --test-enable --test-tags="$TEST_TAG" --stop-after-init
        else
            if [[ "$AGENT_MODE" != "true" ]]; then
                echo "Running all tests for module: $MODULE"
                echo "================================================================================"
            fi
            UPGRADE_ARGS=()
            if [[ "$UPGRADE_MODULES" == "true" ]]; then
                UPGRADE_ARGS=(-u "$MODULE")
            fi
            run_odoo_test -d "$DB_NAME" "${ADDONS_ARGS[@]}" "${UPGRADE_ARGS[@]}" --test-enable --test-tags="/${MODULE}" --stop-after-init
        fi
        ;;

    testall)
        if [[ "$AGENT_MODE" != "true" ]]; then
            echo "Running all tests for all modules"
            echo "Modules: $ALL_MODULES"
            echo "================================================================================"
        fi
        ALL_MODULES_LIST=$(echo "$ALL_MODULES" | tr ' ' ',')
        ALL_TAGS=$(echo "$ALL_MODULES" | tr ' ' '\n' | sed 's|^|/|' | tr '\n' ',' | sed 's/,$//')
        UPGRADE_ARGS=()
        if [[ "$UPGRADE_MODULES" == "true" ]]; then
            UPGRADE_ARGS=(-u "$ALL_MODULES_LIST")
        fi
        run_odoo_test -d "$DB_NAME" "${ADDONS_ARGS[@]}" "${UPGRADE_ARGS[@]}" --test-enable --test-tags="$ALL_TAGS" --stop-after-init
        ;;

    test-js)
        # Check for websocket-client needed by JS HOOT tests
        if ! "$PYTHON_PATH"/python -c "import websocket" 2>/dev/null; then
            echo "Error: websocket-client not installed. JS HOOT tests cannot run."
            echo "Run: odoo-init  (or: pip install websocket-client)"
            exit 1
        fi

        if [[ -n "$MODULE" ]]; then
            if [[ "$AGENT_MODE" != "true" ]]; then
                echo "Running JS unit tests for module: $MODULE"
                echo "================================================================================"
            fi
            HOOT_FILTER=$(build_hoot_filter_for_module "$MODULE")
            if [[ -z "$HOOT_FILTER" ]]; then
                if [[ "$AGENT_MODE" != "true" ]]; then
                    echo "Warning: No .test.js files found in $MODULE/static/tests/"
                    echo "Falling back to full desktop suite."
                fi
                TAG="-at_install,web:WebSuite.test_unit_desktop"
            else
                TAG="-at_install,web:WebSuite.test_unit_desktop[${HOOT_FILTER}]"
            fi
            run_odoo_test -d "$DB_NAME" "${ADDONS_ARGS[@]}" --test-enable --test-tags="$TAG" --stop-after-init
        else
            if [[ "$AGENT_MODE" != "true" ]]; then
                echo "Running JS unit tests for all project modules"
                echo "================================================================================"
            fi
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
                if [[ "$AGENT_MODE" != "true" ]]; then
                    echo "Warning: No .test.js files found in any project module."
                fi
                TAG="-at_install,web:WebSuite.test_unit_desktop"
            else
                TAG="-at_install,web:WebSuite.test_unit_desktop[${ALL_FILTER}]"
            fi
            run_odoo_test -d "$DB_NAME" "${ADDONS_ARGS[@]}" --test-enable --test-tags="$TAG" --stop-after-init
        fi
        ;;

    test-js-all)
        if [[ "$AGENT_MODE" != "true" ]]; then
            echo "Running JS unit tests for all modules"
            echo "Modules: $ALL_MODULES"
            echo "================================================================================"
        fi
        ALL_MODULES_LIST=$(echo "$ALL_MODULES" | tr ' ' ',')
        run_odoo_test -d "$DB_NAME" "${ADDONS_ARGS[@]}" --test-enable --test-tags="-at_install,web:WebSuite.test_unit_desktop" --stop-after-init
        ;;

    *)
        echo "Unknown command: $COMMAND"
        usage
        ;;
esac

if [[ "$AGENT_MODE" != "true" ]]; then
    echo ""
    echo "Done!"
fi
