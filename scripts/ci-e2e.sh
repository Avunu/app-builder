#!/usr/bin/env bash
# The Apply path in CI (.github/workflows/e2e.yml): the end-to-end probes of
# app_builder_base/tests/e2e, which install, upgrade and reload modules in a
# real process -- what Odoo's test mode refuses to do, so `odoo-nix gate test`
# cannot cover it.
#
# Run it in the dev shell, from the repository's root:
#
#   nix develop --no-pure-eval -c scripts/ci-e2e.sh
#
# It starts a throwaway PostgreSQL cluster that listens on a unix socket only
# (as `odoo-nix gate test` does under ODOO_NIX_CI), so it needs no `devenv up`
# and takes no TCP port for the database; run_probes.sh picks free HTTP ports.
# Nothing here is shared between two runs on one host. The full output goes to
# .odoo-nix/e2e/probes.log, the verdict lines to the terminal.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

[ -f odoo.conf ] || { echo "ci-e2e: no odoo.conf here: run this in the dev shell" >&2; exit 3; }
[ -f .odoo-nix/odoo/odoo-bin ] || { echo "ci-e2e: no .odoo-nix/odoo: run this in the dev shell" >&2; exit 3; }

OUT="$ROOT/.odoo-nix/e2e"
DATA="$OUT/pg"
rm -rf "$OUT"
mkdir -p "$OUT"
# A unix socket path is at most 107 bytes: the socket goes in a short temp dir.
SOCK="$(mktemp -d "${TMPDIR:-/tmp}/ab-e2e-pg-XXXXXX")"

stop() {
    pg_ctl -D "$DATA" -m fast -w stop >/dev/null 2>&1 || true
    rm -rf "$SOCK" "$DATA"
}
trap stop EXIT

echo "==> a throwaway PostgreSQL cluster on $SOCK"
initdb -D "$DATA" -U odoo --auth=trust --encoding=UTF8 --no-sync >"$OUT/initdb.log" 2>&1 \
    || { cat "$OUT/initdb.log" >&2; exit 3; }
pg_ctl -D "$DATA" -l "$OUT/pg.log" -o "-k $SOCK -p 5432 -c listen_addresses=''" -w start >/dev/null \
    || { cat "$OUT/pg.log" >&2; exit 3; }

# The port only names the socket file (.s.PGSQL.5432); nothing listens on TCP.
PGHOST="$SOCK" PGPORT=5432 PGUSER=odoo \
    app_builder_base/tests/e2e/run_probes.sh -c odoo.conf -l "$OUT/probes.log" "$@"
