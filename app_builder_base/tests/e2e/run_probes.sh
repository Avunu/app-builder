#!/usr/bin/env bash
# End-to-end probes that cannot run as TransactionCase tests.
#
# ir_module._button_immediate_function raises when
# threading.current_thread().testing is set, so anything that installs,
# upgrades or reloads a module is unreachable from the normal suite. These
# probes drive real registries in a real process instead.
#
# Usage:  app_builder_base/tests/e2e/run_probes.sh [-c odoo.conf] [-t template_db]
# Honours $PYTHON and $PSQL so it runs outside the devenv shell too, e.g.
#   PYTHON=.devenv/profile/bin/python PSQL=.devenv/profile/bin/psql ...
set -euo pipefail

CONF="odoo.conf"
TEMPLATE=""
DB="app_builder_e2e_$$"

while getopts "c:t:d:" opt; do
    case "$opt" in
        c) CONF="$OPTARG" ;;
        t) TEMPLATE="$OPTARG" ;;
        d) DB="$OPTARG" ;;
        *) echo "usage: $0 [-c conf] [-t template_db] [-d dbname]" >&2; exit 2 ;;
    esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python}"
# The probes import odoo as a script would, not through odoo-bin: with the
# checkout's own directory first, so a namespace package rooted at the
# workspace (the `odoo/` directory itself) does not shadow the real one.
export PYTHONPATH="$PWD/odoo${PYTHONPATH:+:$PYTHONPATH}"
PSQL="${PSQL:-psql}"
PSQL_ARGS="-h 127.0.0.1 -p 5442 -U odoo"

cleanup() { "$PSQL" $PSQL_ARGS -d postgres -c "DROP DATABASE IF EXISTS \"$DB\";" >/dev/null 2>&1 || true; }
trap cleanup EXIT

if [ -n "$TEMPLATE" ]; then
    echo "==> cloning $TEMPLATE -> $DB"
    "$PSQL" $PSQL_ARGS -d postgres -c "CREATE DATABASE \"$DB\" TEMPLATE \"$TEMPLATE\";" >/dev/null
else
    echo "==> building $DB from scratch (install app_builder)"
    "$PYTHON" odoo/odoo-bin -c "$CONF" -d "$DB" -i app_builder --stop-after-init \
        --http-port 8298 --gevent-port 8297 >/dev/null
fi

rc=0
for probe in probe_reimport probe_reflection probe_scaffold probe_compose probe_console_apply; do
    echo "==> probe: $probe"
    "$PYTHON" "$HERE/$probe.py" -c "$CONF" -d "$DB" \
        --http-port 8298 --gevent-port 8297 2>&1 \
        | grep -E "^  (PASS|FAIL|NOTE)|^ +->|^RESULT" || rc=1
done
exit $rc
