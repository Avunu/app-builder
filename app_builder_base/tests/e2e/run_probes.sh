#!/usr/bin/env bash
# End-to-end probes that cannot run as TransactionCase tests.
#
# ir_module._button_immediate_function raises when
# threading.current_thread().testing is set, so anything that installs,
# upgrades or reloads a module is unreachable from the normal suite. These
# probes drive real registries in a real process instead.
#
# Usage:  app_builder_base/tests/e2e/run_probes.sh [-c odoo.conf] [-t template_db]
#                                                  [-d dbname] [-l logfile]
# Honours $PYTHON and $PSQL so it runs outside the devenv shell too, e.g.
#   PYTHON=.devenv/profile/bin/python PSQL=.devenv/profile/bin/psql ...
#
# The database server is odoo.conf's unless $PGHOST / $PGPORT / $PGUSER say
# otherwise; then psql and Odoo both use those (scripts/ci-e2e.sh points them at
# a throwaway cluster on a unix socket). The HTTP and gevent ports are free
# ones the kernel picks, unless $E2E_HTTP_PORT / $E2E_GEVENT_PORT pin them, so
# two runs on one host never meet. CI runs this through scripts/ci-e2e.sh
# (.github/workflows/e2e.yml).
set -euo pipefail

CONF="odoo.conf"
TEMPLATE=""
# Unique per process and, on a shared CI host, per run.
DB="app_builder_e2e_${GITHUB_RUN_ID:+${GITHUB_RUN_ID}_${GITHUB_RUN_ATTEMPT:-1}_}$$"
LOG=""

while getopts "c:t:d:l:" opt; do
    case "$opt" in
        c) CONF="$OPTARG" ;;
        t) TEMPLATE="$OPTARG" ;;
        d) DB="$OPTARG" ;;
        l) LOG="$OPTARG" ;;
        *) echo "usage: $0 [-c conf] [-t template_db] [-d dbname] [-l logfile]" >&2; exit 2 ;;
    esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The repository root: every probe is named by its path from here, since the
# approval one lives with its own addon.
ROOT="$(cd "$HERE/../../.." && pwd)"
PROBES=(
    app_builder_base/tests/e2e/probe_reimport
    app_builder_base/tests/e2e/probe_reflection
    app_builder_base/tests/e2e/probe_scaffold
    app_builder_base/tests/e2e/probe_compose
    app_builder_base/tests/e2e/probe_console_apply
    app_builder_approval/tests/e2e/probe_approval
)
# What a database built from scratch gets: the builder, and the approval
# addon its probe drives.
INSTALL="app_builder,app_builder_approval"
PYTHON="${PYTHON:-python}"
# The probes import odoo as a script would, not through odoo-bin: with the
# checkout's own directory first, so a namespace package rooted at the
# workspace (the `odoo/` directory itself) does not shadow the real one.
export PYTHONPATH="$PWD/.odoo-nix/odoo${PYTHONPATH:+:$PYTHONPATH}"
PSQL="${PSQL:-psql}"
# The probes build packages, and run without odoo-bin's --dev, which is what
# turns writing on when nothing else says (SECURITY.md): so they say it, as an
# operator would. Unconditionally: a 0 inherited from the shell would only make
# every probe fail on the switch rather than on what it probes.
export APP_BUILDER_ENABLE_WRITE=1

# One option of odoo.conf's [options], or the fallback.
conf_get() {
    local value
    value="$(sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$CONF" 2>/dev/null | tail -n 1)"
    case "$value" in "" | False | false | None) value="$2" ;; esac
    printf '%s' "$value"
}

DB_HOST="${PGHOST:-$(conf_get db_host 127.0.0.1)}"
DB_PORT="${PGPORT:-$(conf_get db_port 5432)}"
DB_USER="${PGUSER:-$(conf_get db_user odoo)}"
PSQL_ARGS=(-h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER")
# Odoo reads odoo.conf; the flags only say what the environment overrode.
ODOO_DB_ARGS=()
[ -z "${PGHOST:-}" ] || ODOO_DB_ARGS+=(--db_host "$PGHOST")
[ -z "${PGPORT:-}" ] || ODOO_DB_ARGS+=(--db_port "$PGPORT")
[ -z "${PGUSER:-}" ] || ODOO_DB_ARGS+=(--db_user "$PGUSER")

# Two distinct ports nothing listens on: both probes stay open until both are
# chosen. Another process can still take one before Odoo binds it; the window
# is the few seconds of start-up, against a fixed port's every concurrent run.
free_ports() {
    "$PYTHON" -I -c '
import socket
probes = [socket.socket() for _ in range(2)]
for probe in probes:
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    probe.bind(("127.0.0.1", 0))
print(*(probe.getsockname()[1] for probe in probes))
for probe in probes:
    probe.close()
'
}
read -r FREE_HTTP FREE_GEVENT < <(free_ports)
HTTP_PORT="${E2E_HTTP_PORT:-$FREE_HTTP}"
GEVENT_PORT="${E2E_GEVENT_PORT:-$FREE_GEVENT}"
PORT_ARGS=(--http-port "$HTTP_PORT" --gevent-port "$GEVENT_PORT")

if [ -n "$LOG" ]; then
    mkdir -p "$(dirname "$LOG")"
    : >"$LOG"
else
    LOG="$(mktemp)"
    KEEP_LOG=0
fi

# The builder stages what it writes when the addons directory is inside a git
# repository (tools/gitrepo.py), and Apply commits the package before it writes
# ("builder: before apply") whenever the repository's hooks let it. The probes
# delete their packages afterwards. So, in a checkout: the probes' index
# entries go back to what HEAD held before the run (absent), and if a builder
# commit moved HEAD, the way back is printed -- never taken for you.
START_HEAD="$(git rev-parse -q --verify HEAD 2>/dev/null || true)"
# shellcheck disable=SC2329  # called by cleanup, which the trap calls
unstage() {
    git rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0
    [ -n "$START_HEAD" ] || return 0
    local pkg now
    for pkg in x_reimport_probe x_reflect_probe x_scaffold_probe x_compose_probe x_console_probe x_approval_probe; do
        [ -e "$pkg" ] || git reset -q "$START_HEAD" -- "$pkg" >/dev/null 2>&1 || true
    done
    now="$(git rev-parse -q --verify HEAD 2>/dev/null || true)"
    if [ -n "$now" ] && [ "$now" != "$START_HEAD" ]; then
        echo "==> WARNING: HEAD moved during the probes (${START_HEAD:0:12} -> ${now:0:12})." >&2
        echo "    The builder committed probe packages into this checkout:" >&2
        git log --oneline "$START_HEAD..$now" >&2 || true
        echo "    To drop those commits and keep your working tree and index:" >&2
        echo "      git reset --soft $START_HEAD" >&2
    fi
}

# shellcheck disable=SC2329  # called by the trap
cleanup() {
    "$PSQL" "${PSQL_ARGS[@]}" -d postgres -c "DROP DATABASE IF EXISTS \"$DB\";" >/dev/null 2>&1 || true
    unstage
    [ "${KEEP_LOG:-1}" = 1 ] || rm -f "$LOG"
}
trap cleanup EXIT

# The last lines of the full output, when a step dies without a verdict.
tail_log() { echo "---- last lines of the output ----" >&2; tail -n 60 "$LOG" >&2; }

echo "==> database $DB on $DB_HOST:$DB_PORT, http $HTTP_PORT, gevent $GEVENT_PORT"
if [ -n "$TEMPLATE" ]; then
    echo "==> cloning $TEMPLATE -> $DB"
    "$PSQL" "${PSQL_ARGS[@]}" -d postgres -c "CREATE DATABASE \"$DB\" TEMPLATE \"$TEMPLATE\";" >/dev/null
else
    echo "==> building $DB from scratch (install $INSTALL)"
    if ! "$PYTHON" .odoo-nix/odoo/odoo-bin -c "$CONF" -d "$DB" "${ODOO_DB_ARGS[@]}" \
        -i "$INSTALL" --stop-after-init "${PORT_ARGS[@]}" >>"$LOG" 2>&1; then
        echo "  FAIL installing $INSTALL into a fresh database" >&2
        tail_log
        exit 1
    fi
fi
# A template made before the approval probe joined may not carry its addon
# (it is not part of `app_builder`, and does not auto-install).
approval_state="$("$PSQL" "${PSQL_ARGS[@]}" -d "$DB" -tA \
    -c "SELECT state FROM ir_module_module WHERE name = 'app_builder_approval';" 2>/dev/null || true)"
if [ "$approval_state" != "installed" ]; then
    echo "==> installing app_builder_approval into $DB"
    if ! "$PYTHON" .odoo-nix/odoo/odoo-bin -c "$CONF" -d "$DB" "${ODOO_DB_ARGS[@]}" \
        -i app_builder_approval --stop-after-init "${PORT_ARGS[@]}" >>"$LOG" 2>&1; then
        echo "  FAIL installing app_builder_approval into $DB" >&2
        tail_log
        exit 1
    fi
fi

rc=0
failed=()
for probe in "${PROBES[@]}"; do
    echo "==> probe: $probe"
    echo "==> probe: $probe" >>"$LOG"
    out="$(mktemp)"
    status=0
    "$PYTHON" "$ROOT/$probe.py" -c "$CONF" -d "$DB" "${ODOO_DB_ARGS[@]}" \
        "${PORT_ARGS[@]}" >"$out" 2>&1 || status=$?
    cat "$out" >>"$LOG"
    # A probe passes when it exits 0 *and* printed its verdict: a probe that
    # died early, or printed nothing this filter knows, is a failure too.
    grep -E "^  (PASS|FAIL|NOTE)|^ +->|^RESULT" "$out" || status=1
    grep -q "^RESULT" "$out" || status=1
    if grep -q "^  FAIL" "$out"; then status=1; fi
    if [ "$status" -ne 0 ]; then
        rc=1
        failed+=("$probe")
        echo "  FAIL $probe (exit or verdict)" >&2
        echo "---- last lines of $probe ----" >&2
        tail -n 40 "$out" >&2
    fi
    rm -f "$out"
done

if [ "$rc" -ne 0 ]; then
    echo "==> FAILED: ${failed[*]}" >&2
else
    echo "==> all probes passed"
fi
exit $rc
