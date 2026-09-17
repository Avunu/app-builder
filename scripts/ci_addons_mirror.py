#!/usr/bin/env python3
"""Make this repo's own addons resolve as ``odoo.addons.<name>`` in the OCA
CI container, for pyright (``pyrightconfig.ci.json``'s ``extraPaths``).

The container (``ghcr.io/oca/oca-ci/py3.10-odoo18.0``, built from
Avunu/oca-ci's ``Dockerfile`` -- read directly, not guessed at) checks
this repo out as ``$ADDONS_DIR`` (``.``) and tells Odoo's own runtime
loader about it with a plain ``addons_path=...,.`` line in ``odoo.cfg``.
That is enough for ``odoo-bin`` -- it scans every ``addons_path`` entry
for manifests at startup and builds the ``odoo.addons`` namespace package
dynamically -- but it does nothing for a standalone ``pyright`` run,
which resolves imports by walking real directories on ``sys.path``
*before* anything Odoo-specific ever executes.

An addon actually depended on by another addon here does get pip-installed
for real (``oca_install_addons__deps_and_addons_path`` turns the local
checkout into ``file://`` constraints, so a transitive dependency
resolves to this repo instead of the wheelhouse) and lands in the venv's
``site-packages/odoo/addons/<name>`` on its own. But nothing guarantees
*every* addon here is such a dependency -- a leaf nothing else depends on
would only ever be found by the runtime scan. This script covers all of
them the same way, dependency or not: one symlink each, so pyright sees
every addon here the same way it would see one already pip-installed.

Same idea as odoo-nix's own ``ide.enable`` mirror
(``modules/devenv.nix``), which solves the identical problem for OCA
repos that are siblings of ``odoo/`` rather than pip packages -- scoped
here to just this repo's own addons, since everything else this repo
depends on is either pip-installed for real (OCA wheelhouse packages) or
already sitting at ``/opt/odoo`` on ``sys.path`` via Odoo's own editable
install.
"""

import pathlib
import sys

#: Fixed, not configurable: `pyrightconfig.ci.json` names this exact path
#: in its own `extraPaths`, and the two must agree.
MIRROR_ROOT = pathlib.Path("/tmp/app-builder-addons-mirror")

#: This script lives in `scripts/`, a direct child of the addon repo root
#: -- the same root the OCA CI container checks out as `$ADDONS_DIR`.
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def main() -> int:
    addons_ns = MIRROR_ROOT / "odoo" / "addons"
    addons_ns.mkdir(parents=True, exist_ok=True)

    linked = []
    for candidate in sorted(REPO_ROOT.iterdir()):
        if not (candidate / "__manifest__.py").is_file():
            continue
        link = addons_ns / candidate.name
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(candidate)
        linked.append(candidate.name)

    if not linked:
        print(
            f"ci_addons_mirror: found no addons (with __manifest__.py) under "
            f"{REPO_ROOT}"
        )
        return 1

    print(f"ci_addons_mirror: linked {len(linked)} addon(s) under {addons_ns}")
    for name in linked:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
