# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""What the console's home, package switcher and Changes pane read and do.

A package is the workspace: everything the studio writes lands in one, and
the console scopes every pane to the one in its top bar. This model is the
one place the client asks about packages as a whole -- which exist, what
state each is in, what one owns, what has changed on disk or in git, what
was applied and can be rolled back -- so that the answers are dicts shaped
for a screen rather than the recordsets and actions ``studio.package``'s
own methods hand back to Odoo's form view.

Everything here is guarded: reads need a Studio Builder, anything that
writes a file, a record or the registry needs a Studio Administrator, the
same line ``studio.security.mixin`` draws everywhere else.
"""

from __future__ import annotations

import difflib
import json
import os
from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast

from typing_extensions import NotRequired

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.base.models.ir_model import IrModel, IrModelData
from odoo.addons.base.models.ir_module import Module as IrModuleModule
from odoo.addons.base.models.ir_ui_view import View

from ..tools import gitrepo, typed
from .studio_model_draft import StudioModelDraft
from .studio_package import RESERVED_NAMES, StudioPackage
from .studio_package_apply import StudioPackageApply

if TYPE_CHECKING:
    # Only for the annotations/casts below; with `from __future__ import
    # annotations` nothing here needs these at runtime, the same bargain
    # every other Phase 1c file's `TYPE_CHECKING` block makes.
    from odoo.models import BaseModel

    from odoo.addons.base.models.ir_model import IrModelFields

    from .res_users import ResUsers
    from .studio_package import StudioPackageFile
    from .studio_package_apply import StudioPackageApplyFile
    from .studio_package_model import StudioPackageModel
    from .studio_serializer import StudioSerializer

# Keys a user may keep about their own use of the studio. Whitelisted so
# the preference blob stays a small, known shape rather than a scratchpad.
PREF_KEYS = ("last_package_id", "checklist_dismissed", "recent_models", "sidebar_width")
RECENT_MODELS = 8
DIFF_LIMIT = 200_000
APPLY_LIMIT = 50
LOG_LIMIT = 20


# -- wire types ---------------------------------------------------------
#
# Traced from what each method below actually builds. `PackageJSON`/
# `ApplyJSON`/`UserPrefsJSON` mirror `app_builder_view/static/src/console
# /wire.ts`'s own `PackageEntryJSON`/`ApplyEntryJSON`/`UserPrefsJSON`
# field-for-field (TypeScript conversion 2b, cluster 2, which traced them
# from this file before it was itself converted); the rest have no TS
# reader yet and are traced from this file's own bodies only. Named
# `<Thing>JSON` per this migration's own convention.


class UserRefJSON(TypedDict):
    """Who did something: the ``{"id", "name"}`` pair ``_apply_dict``/
    ``_drafts`` both build for their own ``"user"`` key."""

    id: int
    name: str


class ApplyFileRefJSON(TypedDict):
    """One file touched by an apply, in ``ApplyJSON``'s own ``"files"``."""

    path: str
    existed: bool


class ApplyJSON(TypedDict):
    """Returned by ``_apply_dict()`` -- ``wire.ts:ApplyEntryJSON``."""

    id: int
    reason: str
    state: str
    error: str
    # `create_date` is a magic field (`_add_magic_fields`, see the read
    # site below) read through `apply["create_date"]`, so
    # `fields.Datetime.to_string()` is called with an `Any` argument --
    # its own real, honest return shape (`str | Literal[False]`, matching
    # `wire.ts:ApplyEntryJSON.create_date`) is kept here rather than
    # narrowed to plain `str`.
    create_date: str | Literal[False]
    user: UserRefJSON
    backup_path: str
    has_backup: bool
    files: list[ApplyFileRefJSON]
    can_rollback: bool


class PackageGitJSON(TypedDict):
    """The ``"git"`` block in ``PackageJSON``."""

    is_git: bool
    branch: str
    dirty: int
    untracked: int


class ModelsCountJSON(TypedDict):
    """The ``"models"`` block in ``PackageJSON``: counts by source."""

    python: int
    frozen: int
    extends: int
    xml: int


class AppliesSummaryJSON(TypedDict):
    """The ``"applies"`` block in ``PackageJSON``: counts plus the newest one."""

    pending: int
    failed: int
    awaiting_restart: int
    last: ApplyJSON | None


class PackageJSON(TypedDict):
    """Returned by ``_package_dict()`` -- ``wire.ts:PackageEntryJSON``."""

    id: int
    name: str
    title: str
    summary: str
    version: str
    root_path: str
    writable: bool
    reload_mode: str
    state: str
    drift_count: int
    file_count: int
    record_count: int
    module_state: str
    git: PackageGitJSON
    models: ModelsCountJSON
    applies: AppliesSummaryJSON
    drafts: int
    health: list[str]
    suggested: bool


class PackageFileEntryJSON(TypedDict):
    """One file of the package, in ``PackageDetailJSON``'s own ``"files"``."""

    path: str
    drifted: bool


class PackageDetailJSON(PackageJSON):
    """Returned by ``package()``/``create_package()``: ``PackageJSON`` plus
    the manifest and file detail only one package's own page needs."""

    depends: list[str]
    category: str
    author: str
    license: str
    auto_commit: str
    files: list[PackageFileEntryJSON]


class AddonsDirJSON(TypedDict):
    """One entry of ``addons_dirs()``: a directory on the addons path."""

    path: str
    writable: bool
    kind: str


class InventoryEntryJSON(TypedDict):
    """One owned record, in ``inventory()``'s own per-group lists."""

    id: int
    model: str
    subject: str
    xmlid: str
    display_name: str
    file: str | None


class InventoryModelJSON(TypedDict):
    """One row of ``inventory()``'s own ``"models"`` list, from
    ``_inventory_models``."""

    model: str
    display_name: str
    id: int | Literal[False]
    source: str
    parse_error: str
    python_path: str
    in_registry: bool
    field_count: int
    owned_field_count: int
    views: list[str]
    counts: dict[str, int]


class InventoryJSON(TypedDict):
    """Returned by ``inventory()``: every group, plus ``"models"``."""

    models: list[InventoryModelJSON]
    fields: list[InventoryEntryJSON]
    views: list[InventoryEntryJSON]
    actions: list[InventoryEntryJSON]
    menus: list[InventoryEntryJSON]
    automations: list[InventoryEntryJSON]
    access: list[InventoryEntryJSON]
    rules: list[InventoryEntryJSON]
    approvals: list[InventoryEntryJSON]
    reports: list[InventoryEntryJSON]
    other: list[InventoryEntryJSON]


class DefinedModelJSON(TypedDict):
    """One of ``models_for_picker()``'s own ``"defined"`` entries."""

    model: str
    display_name: str
    source: str


class ExtendedModelJSON(TypedDict):
    """One of ``models_for_picker()``'s own ``"extended"`` entries."""

    model: str
    display_name: str
    count: int


class RecentModelJSON(TypedDict):
    """One of ``models_for_picker()``'s own ``"recent"`` entries."""

    model: str
    display_name: str


class ModelsForPickerJSON(TypedDict):
    """Returned by ``models_for_picker()``."""

    defined: list[DefinedModelJSON]
    extended: list[ExtendedModelJSON]
    recent: list[RecentModelJSON]


class FileStatusEntryJSON(TypedDict):
    """One file's sync status: ``changes()``'s own ``"drift"``/``"files"``
    lists both hold this same shape."""

    path: str
    status: str


class GitStatusEntryJSON(TypedDict):
    """One porcelain status entry, package-relative -- ``_git_status()``."""

    path: str
    state: str


class ChangesGitInfoJSON(TypedDict):
    """The ``"git"`` block in ``ChangesJSON`` -- a different shape than
    ``PackageGitJSON``: the Changes pane wants the status/log, not counts."""

    is_git: bool
    branch: str
    status: list[GitStatusEntryJSON]
    log: list[gitrepo.LogEntryJSON]
    auto_commit: str


class DraftEntryJSON(TypedDict):
    """One of ``changes()``'s own ``"drafts"`` entries -- ``_drafts()``."""

    id: int
    model: str
    change_count: int
    user: UserRefJSON
    mine: bool
    write_date: str | Literal[False]


class ChangesJSON(TypedDict):
    """Returned by ``changes()``: everything the Changes pane needs at once."""

    package: PackageJSON
    drift: list[FileStatusEntryJSON]
    files: list[FileStatusEntryJSON]
    pending_write: bool
    git: ChangesGitInfoJSON
    applies: list[ApplyJSON]
    drafts: list[DraftEntryJSON]


class DiffResultJSON(TypedDict):
    """Returned by ``git_diff()``."""

    diff: str
    truncated: bool


class DriftDiffJSON(TypedDict):
    """Returned by ``drift_diff()``/``apply_diff()``: one unified diff."""

    diff: str


class CommitResultJSON(TypedDict):
    """Returned by ``commit()``: a sha only when something was committed."""

    committed: bool
    reason: NotRequired[str]
    sha: NotRequired[str]


class GitInitResultJSON(TypedDict):
    """Returned by ``git_init()``."""

    is_git: bool


class SetAutoCommitJSON(TypedDict):
    """Returned by ``set_auto_commit()``."""

    auto_commit: str


class PackageStateJSON(TypedDict):
    """Returned by ``write_files()``/``delete_records()``: just the state
    the action left the package in."""

    state: str


class CheckDriftJSON(TypedDict):
    """Returned by ``check_drift()``."""

    state: str
    drift_count: int


class ReloadJSON(TypedDict):
    """Returned by ``reload()``: ``"state"`` only when a reload actually ran."""

    restart_required: bool
    reloaded: bool
    state: NotRequired[str]


class RollbackJSON(TypedDict):
    """Returned by ``rollback()``: ``action_rollback()``'s own dict plus the
    apply it rolled back."""

    rolled_back: bool
    restart_required: bool
    apply: ApplyJSON


class UserPrefsJSON(TypedDict):
    """Returned by ``user_prefs()``/``set_user_pref()``/``remember_model()``:
    every key in ``PREF_KEYS``, always present, ``None`` when never set."""

    last_package_id: int | Literal[False] | None
    checklist_dismissed: bool | None
    recent_models: list[str] | None
    sidebar_width: int | Literal[False] | None


class ChecklistJSON(TypedDict):
    """Returned by ``checklist()``: which getting-started steps have happened."""

    package: bool
    app: bool
    field: bool
    automation: bool
    commit: bool


class StudioWorkspace(models.AbstractModel):
    _name = "studio.workspace"
    _inherit = ["studio.security.mixin"]
    _description = "Studio Workspace"

    # -- packages -----------------------------------------------------------

    @api.model
    def packages(self, include_git: bool = True) -> list[PackageJSON]:
        """Every package, with what the home and the switcher need to say.

        Abandoned applies are reaped first, so a process that died mid-apply
        shows up here as a failed apply with a rollback on offer rather than
        as a row that stays pending for ever.
        """
        typed.security(self)._assert_studio_user()
        # Read as superuser once the guard has passed: the facts a builder
        # sees here (xmlids, module rows, applies) are ones the ACLs of
        # those models do not grant a plain user, and nothing is written.
        packages = typed.model(self.env, StudioPackage).sudo().search([])
        typed.model(self.env, StudioPackageApply).sudo()._reap_abandoned(packages)
        suggested = typed.model(self.env, StudioPackage).sudo()._suggested()
        return [
            self._package_dict(package, include_git=include_git, suggested=suggested)
            for package in packages
        ]

    @api.model
    def package(self, package_id: int) -> PackageDetailJSON:
        """One package, with its manifest and files as well."""
        typed.security(self)._assert_studio_user()
        package = self._package(package_id)
        typed.model(self.env, StudioPackageApply).sudo()._reap_abandoned(package)
        out = cast(
            "PackageDetailJSON",
            self._package_dict(
                package,
                suggested=typed.model(self.env, StudioPackage).sudo()._suggested(),
            ),
        )
        out.update(
            {
                "depends": [d.strip() for d in (package.depends or "").split(",") if d],
                "category": package.category or "",
                "author": package.author or "",
                "license": package.license or "",
                "auto_commit": cast("str", package.auto_commit),
                "files": [
                    {"path": cast("str", f.path), "drifted": f.drifted}
                    for f in cast("StudioPackageFile", package.file_ids).sorted("path")
                ],
            }
        )
        return out

    @api.model
    def _package(self, package_id: int) -> StudioPackage:
        """The package, as superuser: the guard is on the caller, and what
        is read about a package -- xmlids, module rows, applies -- is more
        than a Studio Builder's own ACLs grant."""
        package = (
            typed.model(self.env, StudioPackage).sudo().browse(package_id).exists()
        )
        if not package:
            raise UserError(_("That package no longer exists."))
        return package

    @api.model
    def _package_dict(
        self,
        package: StudioPackage,
        include_git: bool = True,
        suggested: StudioPackage | None = None,
    ) -> PackageJSON:
        Apply = typed.model(self.env, StudioPackageApply).sudo()
        applies = Apply.search([("package_id", "=", package.id)])
        by_state: dict[str | Literal[False], int] = {}
        for apply in applies:
            by_state[apply.state] = by_state.get(apply.state, 0) + 1
        last = applies[:1]
        module = (
            typed.model(self.env, IrModuleModule)
            .sudo()
            .search([("name", "=", package.name)], limit=1)
        )
        module_state = cast("str", module.state) if module else "unknown"
        python = cast("StudioPackageModel", package.model_ids).filtered(
            lambda m: not m.extends
        )
        models: ModelsCountJSON = {
            "python": len(python.filtered(lambda m: m.source == "python")),
            "frozen": len(python.filtered(lambda m: m.source == "frozen")),
            "extends": len(
                cast("StudioPackageModel", package.model_ids).filtered("extends")
            ),
            "xml": len(package._owned_model_names() - package._python_model_set()),
        }
        git: dict[str, object] = {
            "is_git": package.is_git,
            "branch": package.git_branch or "",
        }
        if include_git and package.is_git:
            status = self._git_status(package)
            git["dirty"] = len([e for e in status if e["state"] != "??"])
            git["untracked"] = len([e for e in status if e["state"] == "??"])
        else:
            git["dirty"] = git["untracked"] = 0
        drafts = self._drafts(package)
        drift_count = len(
            cast("StudioPackageFile", package.file_ids).filtered("drifted")
        )

        health: list[str] = []
        if not package.writable:
            health.append("read_only")
        if package.state == "missing":
            health.append("missing")
        if module_state != "installed":
            health.append("not_installed")
        if by_state.get("failed"):
            health.append("failed_apply")
        if by_state.get("awaiting_restart"):
            health.append("restart_required")
        if package.state == "drifted" or drift_count:
            health.append("drifted")
        if drafts:
            health.append("pending")
        if package.state == "dirty":
            health.append("pending_write")
        if git["is_git"] and (git["dirty"] or git["untracked"]):
            health.append("uncommitted")
        if not git["is_git"]:
            health.append("no_git")
        if package.reload_mode == "manual":
            health.append("manual_reload")

        return {
            "id": cast("int", package.id),
            "name": cast("str", package.name),
            "title": cast("str", package.display_name_ or package.name),
            "summary": package.summary or "",
            "version": cast("str", package.version),
            "root_path": package.root_path or "",
            "writable": package.writable,
            "reload_mode": cast("str", package.reload_mode),
            "state": cast("str", package.state),
            "drift_count": drift_count,
            "file_count": len(cast("StudioPackageFile", package.file_ids)),
            "record_count": package.record_count,
            "module_state": module_state,
            "git": cast("PackageGitJSON", git),
            "models": models,
            "applies": {
                "pending": by_state.get("pending", 0),
                "failed": by_state.get("failed", 0),
                "awaiting_restart": by_state.get("awaiting_restart", 0),
                "last": self._apply_dict(last, package) if last else None,
            },
            "drafts": len(drafts),
            "health": health,
            "suggested": bool(suggested) and package == suggested,
        }

    @api.model
    def addons_dirs(self) -> list[AddonsDirJSON]:
        """Where a package may be created: the addons path, as it is.

        Odoo builds ``odoo.addons.__path__`` once at start-up, so a package
        has to live directly under one of these to be found at all. Core's
        own directories are listed and never offered: a package written
        into ``odoo/addons`` would be a patch on the upstream checkout.
        """
        typed.security(self)._assert_studio_user()
        import odoo

        import odoo.addons

        core_root = os.path.dirname(
            os.path.dirname(os.path.abspath(cast("str", odoo.__file__)))
        )
        Package = typed.model(self.env, StudioPackage)
        out: list[AddonsDirJSON] = []
        for path in odoo.addons.__path__:
            real = os.path.realpath(path)
            if real.startswith(core_root + os.sep):
                kind = "core"
            elif os.path.basename(real.rstrip(os.sep)) == "custom":
                kind = "custom"
            else:
                kind = "config"
            out.append(
                {
                    "path": real,
                    "writable": kind != "core"
                    and os.path.isdir(real)
                    and Package._can_write_to(real),
                    "kind": kind,
                }
            )
        # custom first, then the rest in path order; core last.
        order = {"custom": 0, "config": 1, "core": 2}
        return sorted(out, key=lambda d: (order[d["kind"]], d["path"]))

    @api.model
    def create_package(self, values: dict[str, Any]) -> PackageDetailJSON:
        """Make a package from the console, refusing what would not load.

        ``studio.package`` validates the name; everything else about where
        a package can live was found out later -- by ``_find_or_create_module``
        raising on the first install. Checked here instead, with a sentence
        each, so the first thing a user does in the studio cannot fail
        twenty minutes later.
        """
        typed.security(self)._assert_studio_manager()
        Package = typed.model(self.env, StudioPackage)
        name = (values.get("name") or "").strip()
        if not name or not name.isidentifier() or name != name.lower():
            raise UserError(
                _(
                    "'%s' is not a valid module name: lowercase letters, digits "
                    "and underscores, starting with a letter.",
                    name,
                )
            )
        if name in RESERVED_NAMES:
            raise UserError(
                _("'%s' is reserved by Odoo core and cannot be used.", name)
            )
        if Package.search_count([("name", "=", name)]):
            raise UserError(_("A package called %s already exists.", name))
        module = (
            typed.model(self.env, IrModuleModule)
            .sudo()
            .search([("name", "=", name)], limit=1)
        )
        if module:
            raise UserError(
                _(
                    "'%s' is already the name of a module Odoo knows about; a "
                    "package with that name would shadow it.",
                    name,
                )
            )

        dirs = {d["path"]: d for d in self.addons_dirs()}
        root_dir = values.get("root_dir") or Package._default_addons_dir()
        root_dir = os.path.realpath(root_dir) if root_dir else ""
        if not root_dir or root_dir not in dirs:
            raise UserError(
                _(
                    "%s is not on the addons path. Odoo only loads addons from "
                    "directories that were on the path when the server started.",
                    root_dir or _("that directory"),
                )
            )
        if dirs[root_dir]["kind"] == "core":
            raise UserError(
                _(
                    "%s belongs to Odoo itself; a package cannot be created there.",
                    root_dir,
                )
            )
        if not dirs[root_dir]["writable"]:
            raise UserError(_("%s cannot be written to.", root_dir))
        root_path = os.path.join(root_dir, name)
        if os.path.exists(root_path) and (
            not os.path.isdir(root_path) or os.listdir(root_path)
        ):
            raise UserError(
                _(
                    "%s already exists and is not empty. Adopt it as a package "
                    "from its own directory, or pick another name.",
                    root_path,
                )
            )
        depends = {d.strip() for d in (values.get("depends") or "").split(",") if d}
        depends.add("base")
        package = Package.create(
            {  # pyright: ignore[reportArgumentType] -- `@api.model_create_multi`
                # (`odoo/api.py`) is a bare passthrough decorator that does not
                # widen `create()`'s own declared `list[ValuesType]`-only
                # signature to also cover the single-dict form it genuinely
                # accepts at runtime (TYPING.md's own "Known traps").
                "name": name,
                "display_name_": (values.get("title") or name).strip(),
                "summary": (values.get("summary") or "").strip(),
                "root_path": root_path,
                "depends": ",".join(sorted(depends)),
                "auto_commit": values.get("auto_commit") or "stage",
            }
        )
        package._render_bootstrap_files()
        if values.get("git_init"):
            gitrepo.init(cast("str", package.root_path))
            package.invalidate_recordset(["is_git", "git_branch"])
        return self.package(cast("int", package.id))

    # -- what a package owns --------------------------------------------------

    INVENTORY_GROUPS = (
        "models",
        "fields",
        "views",
        "actions",
        "menus",
        "automations",
        "access",
        "rules",
        "approvals",
        "reports",
        "other",
    )

    @api.model
    def _inventory_group(self, model_name: str, record: BaseModel | None) -> str:
        """Which list of the inventory a record belongs in.

        Overridden by the addons that know a model this one does not:
        ``base.automation`` lands in ``automations`` and ``tier.definition``
        in ``approvals`` only when those addons say so.
        """
        # `record` is unused by this base implementation (every branch below
        # only inspects `model_name`) but has to stay `BaseModel | None`, not
        # `BaseModel`: `app_builder_ui/models/studio_workspace.py`'s own
        # override checks `record is not None` before reading a field off
        # it, and its `super()._inventory_group(model_name, record)` call
        # needs this base's own parameter to accept exactly what it passes.
        if model_name in ("ir.model", "ir.model.fields", "ir.model.fields.selection"):
            return "models" if model_name == "ir.model" else "fields"
        if model_name == "ir.ui.view":
            return "views"
        if model_name in ("ir.actions.act_window", "ir.actions.act_window.view"):
            return "actions"
        if model_name == "ir.actions.server":
            return "actions"
        if model_name == "ir.ui.menu":
            return "menus"
        if model_name == "ir.model.access":
            return "access"
        if model_name == "ir.rule":
            return "rules"
        if model_name == "ir.actions.report":
            return "reports"
        return "other"

    @api.model
    def inventory(self, package_id: int) -> InventoryJSON:
        """Everything the package owns, grouped by what it is, plus its models.

        Ownership is ``ir.model.data.module``, the same rule the serializer
        uses, so this lists exactly what the files declare. A model appears
        whether it is defined in Python, extended, frozen or still a set of
        data records the package owns but has not adopted.
        """
        typed.security(self)._assert_studio_user()
        package = self._package(package_id)
        serializers = package._serializer_env()
        groups: dict[str, list[InventoryEntryJSON]] = {
            key: [] for key in self.INVENTORY_GROUPS
        }
        subject_counts: dict[str, dict[str, int]] = {}
        for model_name, entries in package._owned_records().items():
            serializer = serializers._for_model(model_name)
            for xmlid, record in entries:
                group = self._inventory_group(model_name, record)
                # An AbstractModel recordset is empty and therefore falsy;
                # the question is whether a serializer exists at all.
                has_serializer = serializer is not None
                subject = (
                    cast("StudioSerializer", serializer)._group_model(record)
                    if has_serializer
                    else None
                )
                target = (
                    cast("StudioSerializer", serializer)._target_file(record)
                    if has_serializer
                    else None
                )
                entry: InventoryEntryJSON = {
                    "id": cast("int", record.id),
                    "model": model_name,
                    "subject": subject or "",
                    "xmlid": xmlid,
                    "display_name": record.display_name or xmlid,
                    "file": target,
                }
                groups[group].append(entry)
                if subject:
                    counts = subject_counts.setdefault(subject, {})
                    counts[group] = counts.get(group, 0) + 1
        for key in self.INVENTORY_GROUPS:
            groups[key].sort(key=lambda e: (e["file"] or "", e["display_name"]))
        result = cast("InventoryJSON", groups)
        result["models"] = self._inventory_models(package, subject_counts)
        return result

    @api.model
    def _inventory_models(
        self, package: StudioPackage, subject_counts: dict[str, dict[str, int]]
    ) -> list[InventoryModelJSON]:
        IrModelSudo = typed.model(self.env, IrModel).sudo()
        # Named `view_model`, not `View` (the real class this file's own
        # `typed.model()` call is typed against): a local `View = self.env
        # [...]` would shadow that import for the rest of this function --
        # and, worse, `View = typed.model(self.env, View)` would try to
        # read the not-yet-assigned local `View` on its own right-hand side
        # (Python's own scoping: a name assigned anywhere in a function is
        # local for the whole function), an `UnboundLocalError` this
        # conversion must not introduce. Same shape as `studio_package.py`'s
        # own `IrModel`/`IrModelSudo` rename and `studio_view_editor.py`'s
        # own `View`/`view_model` rename.
        view_model = typed.model(self.env, View).sudo()
        owned_field_ids = package._owned_field_ids()
        out: list[InventoryModelJSON] = []
        rows = {
            cast("str", m.model): m
            for m in cast("StudioPackageModel", package.model_ids)
        }
        names = set(rows) | package._owned_model_names()
        for model_name in sorted(names):
            row = rows.get(model_name)
            ir_model = IrModelSudo.search([("model", "=", model_name)], limit=1)
            in_registry = model_name in self.env
            if row is not None:
                source = "extends" if row.extends else cast("str", row.source)
            else:
                source = "xml"
            fields_ = cast(
                "IrModelFields",
                ir_model.field_id if ir_model else IrModelSudo.browse().field_id,
            )
            owned = len([f for f in fields_ if f.id in owned_field_ids])
            view_types = [
                view_type
                for (view_type,) in cast(
                    "list[tuple[str]]",
                    view_model._read_group(
                        [("model", "=", model_name), ("mode", "=", "primary")], ["type"]
                    ),
                )
            ]
            counts = subject_counts.get(model_name, {})
            out.append(
                {
                    "model": model_name,
                    "display_name": cast("str", ir_model.name)
                    if ir_model
                    else model_name,
                    "id": cast("int", ir_model.id) if ir_model else False,
                    "source": source,
                    "parse_error": (row.parse_error or "") if row is not None else "",
                    "python_path": cast("str", row.python_path)
                    if row is not None
                    else "",
                    "in_registry": in_registry,
                    "field_count": len(self.env[model_name]._fields)
                    if in_registry
                    else len(fields_),
                    "owned_field_count": owned,
                    "views": sorted(view_types),
                    "counts": {
                        key: counts.get(key, 0)
                        for key in self.INVENTORY_GROUPS
                        if key != "models"
                    },
                }
            )
        return out

    @api.model
    def models_for_picker(self, package_id: int | None = None) -> ModelsForPickerJSON:
        """The models the crumb offers: the package's own, the ones it
        touches, and the ones this user opened last."""
        typed.security(self)._assert_studio_user()
        defined: list[DefinedModelJSON] = []
        extended: list[ExtendedModelJSON] = []
        if package_id:
            package = self._package(package_id)
            inventory = self.inventory(cast("int", package.id))
            defined = [
                {
                    "model": m["model"],
                    "display_name": m["display_name"],
                    "source": m["source"],
                }
                for m in inventory["models"]
            ]
            defined_names = {m["model"] for m in defined}
            touched: dict[str, int] = {}
            for key, entries in inventory.items():
                if key == "models":
                    continue
                for entry in cast("list[InventoryEntryJSON]", entries):
                    subject = entry["subject"]
                    if subject and subject not in defined_names:
                        touched[subject] = touched.get(subject, 0) + 1
            IrModelSudo = typed.model(self.env, IrModel).sudo()
            for model_name in sorted(touched):
                ir_model = IrModelSudo.search([("model", "=", model_name)], limit=1)
                extended.append(
                    {
                        "model": model_name,
                        "display_name": cast("str", ir_model.name)
                        if ir_model
                        else model_name,
                        "count": touched[model_name],
                    }
                )
        recent: list[RecentModelJSON] = []
        IrModelSudo = typed.model(self.env, IrModel).sudo()
        for model_name in self.user_prefs().get("recent_models") or []:
            if model_name in self.env:
                ir_model = IrModelSudo.search([("model", "=", model_name)], limit=1)
                recent.append(
                    {
                        "model": model_name,
                        "display_name": cast("str", ir_model.name)
                        if ir_model
                        else model_name,
                    }
                )
        return {"defined": defined, "extended": extended, "recent": recent}

    # -- changes -------------------------------------------------------------

    @api.model
    def changes(self, package_id: int) -> ChangesJSON:
        """The Changes pane: drift, git, applies and drafts, in one call."""
        typed.security(self)._assert_studio_user()
        package = self._package(package_id)
        typed.model(self.env, StudioPackageApply).sudo()._reap_abandoned(package)
        package.action_check_drift()
        drift: list[FileStatusEntryJSON] = []
        files: list[FileStatusEntryJSON] = []
        for entry in cast("StudioPackageFile", package.file_ids).sorted("path"):
            status = "in_sync"
            if entry.drifted:
                status = "missing" if not entry.disk_checksum else "edited"
                drift.append({"path": cast("str", entry.path), "status": status})
            files.append({"path": cast("str", entry.path), "status": status})
        git: ChangesGitInfoJSON = {
            "is_git": package.is_git,
            "branch": package.git_branch or "",
            "status": self._git_status(package) if package.is_git else [],
            "log": gitrepo.log(cast("str", package.root_path), LOG_LIMIT)
            if package.is_git
            else [],
            "auto_commit": cast("str", package.auto_commit),
        }
        applies = (
            typed.model(self.env, StudioPackageApply)
            .sudo()
            .search([("package_id", "=", package.id)], limit=APPLY_LIMIT)
        )
        return {
            "package": self._package_dict(
                package,
                suggested=typed.model(self.env, StudioPackage).sudo()._suggested(),
            ),
            "drift": drift,
            "files": files,
            "pending_write": package.state == "dirty",
            "git": git,
            "applies": [self._apply_dict(apply, package) for apply in applies],
            "drafts": self._drafts(package),
        }

    @api.model
    def _git_status(self, package: StudioPackage) -> list[GitStatusEntryJSON]:
        """Porcelain entries, package-relative, for the package's files only.

        ``git status`` speaks in repository-root paths; a package that is one
        directory of a larger repository has to strip its own prefix, and
        anything outside it is somebody else's change.
        """
        root = cast("str", package.root_path)
        top = gitrepo.toplevel(root)
        if not top:
            return []
        prefix = os.path.relpath(os.path.realpath(root), os.path.realpath(top))
        prefix = "" if prefix == "." else prefix.rstrip(os.sep) + os.sep
        out: list[GitStatusEntryJSON] = []
        for code, path in gitrepo.status(root):
            # A rename is "old -> new"; the new name is the one that exists.
            path = path.split(" -> ")[-1].strip('"')
            if prefix and not path.startswith(prefix):
                continue
            out.append({"path": path[len(prefix) :], "state": code or "M"})
        return out

    @api.model
    def _apply_dict(
        self, apply: StudioPackageApply, package: StudioPackage
    ) -> ApplyJSON:
        return {
            "id": cast("int", apply.id),
            "reason": apply.reason or "",
            "state": cast("str", apply.state),
            "error": apply.error or "",
            # `create_date`/`create_uid` are magic fields (`_add_magic_fields`,
            # `models.py`), added to every model at registry setup and never
            # declared as real class attributes -- invisible to pyright on
            # `apply.create_date`/`apply.create_uid` the same way
            # `studio_view_edit.py`'s own `_entry`/`studio_view_canvas.py`'s
            # own `_open_draft` document. Subscripted instead of dotted,
            # which sidesteps the missing-attribute error entirely rather
            # than casting a read that would not type-check in the first
            # place.
            "create_date": fields.Datetime.to_string(apply["create_date"]),
            "user": {
                "id": cast("int", apply["create_uid"].id),
                "name": cast("str", apply["create_uid"].name),
            },
            "backup_path": apply.backup_path or "",
            "has_backup": bool(apply.backup_path and os.path.isdir(apply.backup_path)),
            "files": [
                {"path": cast("str", f.path), "existed": f.existed}
                for f in cast("StudioPackageApplyFile", apply.file_ids)
            ],
            "can_rollback": apply.state in ("applied", "failed", "awaiting_restart")
            and package.writable
            and bool(apply.file_ids),
        }

    @api.model
    def _drafts(self, package: StudioPackage) -> list[DraftEntryJSON]:
        Draft = typed.model(self.env, StudioModelDraft).sudo()
        out: list[DraftEntryJSON] = []
        for draft in Draft.search([("package_id", "=", package.id)]):
            if not draft.dirty:
                continue
            out.append(
                {
                    "id": cast("int", draft.id),
                    "model": cast("str", draft.model),
                    "change_count": draft.change_count,
                    "user": {
                        "id": cast("int", draft["create_uid"].id),
                        "name": cast("str", draft["create_uid"].name),
                    },
                    "mine": draft["create_uid"] == self.env.user,
                    "write_date": fields.Datetime.to_string(draft["write_date"]),
                }
            )
        return out

    @api.model
    def git_diff(self, package_id: int, path: str | None = None) -> DiffResultJSON:
        typed.security(self)._assert_studio_user()
        package = self._package(package_id)
        if not package.is_git:
            return {"diff": "", "truncated": False}
        paths = [os.path.join(cast("str", package.root_path), path)] if path else None
        diff = gitrepo.diff(cast("str", package.root_path), paths)
        return {"diff": diff[:DIFF_LIMIT], "truncated": len(diff) > DIFF_LIMIT}

    @api.model
    def drift_diff(self, package_id: int, path: str) -> DriftDiffJSON:
        """What the database would write against what is on disk."""
        typed.security(self)._assert_studio_user()
        package = self._package(package_id)
        generated = package._render_files().get(path)
        on_disk = package._read_source(path)
        return {"diff": self._unified(generated, on_disk, path, "generated", "on disk")}

    @api.model
    def _unified(
        self,
        before: str | None,
        after: str | None,
        path: str,
        from_label: str,
        to_label: str,
    ) -> str:
        diff = difflib.unified_diff(
            (before or "").splitlines(keepends=True),
            (after or "").splitlines(keepends=True),
            fromfile="%s (%s)" % (path, from_label),
            tofile="%s (%s)" % (path, to_label),
        )
        return "".join(diff)[:DIFF_LIMIT]

    @api.model
    def commit(self, package_id: int, message: str) -> CommitResultJSON:
        """Commit everything under the package, and nothing beside it."""
        typed.security(self)._assert_studio_manager()
        package = self._package(package_id)
        if not package.is_git:
            return {"committed": False, "reason": _("Not a git repository.")}
        message = (message or "").strip()
        if not message:
            raise UserError(_("A commit needs a message."))
        sha = gitrepo.commit(cast("str", package.root_path), message)
        if not sha:
            return {"committed": False, "reason": _("Nothing to commit.")}
        return {"committed": True, "sha": sha}

    @api.model
    def git_init(self, package_id: int) -> GitInitResultJSON:
        typed.security(self)._assert_studio_manager()
        package = self._package(package_id)
        package._assert_writable()
        ok = gitrepo.init(cast("str", package.root_path))
        package.invalidate_recordset(["is_git", "git_branch"])
        return {"is_git": bool(ok and package.is_git)}

    @api.model
    def set_auto_commit(self, package_id: int, value: str) -> SetAutoCommitJSON:
        typed.security(self)._assert_studio_manager()
        package = self._package(package_id)
        package.write({"auto_commit": value})
        return {"auto_commit": cast("str", package.auto_commit)}

    # -- package actions, as dicts ---------------------------------------------

    @api.model
    def check_drift(self, package_id: int) -> CheckDriftJSON:
        typed.security(self)._assert_studio_user()
        package = self._package(package_id)
        package.action_check_drift()
        return {
            "state": cast("str", package.state),
            "drift_count": len(
                cast("StudioPackageFile", package.file_ids).filtered("drifted")
            ),
        }

    @api.model
    def write_files(self, package_id: int) -> PackageStateJSON:
        typed.security(self)._assert_studio_manager()
        package = self._package(package_id)
        package.action_write_files()
        return {"state": cast("str", package.state)}

    @api.model
    def reload(self, package_id: int) -> ReloadJSON:
        """Read the package from disk into the database, where that is possible."""
        typed.security(self)._assert_studio_manager()
        package = self._package(package_id)
        if package.reload_mode == "manual":
            return {"restart_required": True, "reloaded": False}
        package.action_reload()
        return {
            "restart_required": False,
            "reloaded": True,
            "state": cast("str", package.state),
        }

    @api.model
    def delete_records(self, package_id: int) -> PackageStateJSON:
        typed.security(self)._assert_studio_manager()
        package = self._package(package_id)
        package.action_delete_records()
        return {"state": cast("str", package.state)}

    @api.model
    def apply(
        self, package_id: int, reason: str = "", allow_destructive: bool = False
    ) -> ApplyJSON:
        typed.security(self)._assert_studio_manager()
        package = self._package(package_id)
        apply = package.action_apply(reason=reason, allow_destructive=allow_destructive)
        return self._apply_dict(apply, package)

    @api.model
    def rollback(self, apply_id: int) -> RollbackJSON:
        typed.security(self)._assert_studio_manager()
        apply = typed.model(self.env, StudioPackageApply).browse(apply_id).exists()
        if not apply:
            raise UserError(_("That apply no longer exists."))
        # `action_rollback()` is declared `-> dict[str, bool]`
        # (`studio_package_apply.py`, already converted); this file adds a
        # third, non-`bool` key (`"apply"`) right below, so the call's own
        # result is cast up front to the wider shape this method actually
        # returns rather than left at its callee's own narrower type.
        result = cast("RollbackJSON", apply.action_rollback())
        result["apply"] = self._apply_dict(
            apply, cast("StudioPackage", apply.package_id)
        )
        return result

    @api.model
    def discard_backup(self, apply_id: int) -> ApplyJSON:
        typed.security(self)._assert_studio_manager()
        apply = typed.model(self.env, StudioPackageApply).browse(apply_id).exists()
        if not apply:
            raise UserError(_("That apply no longer exists."))
        apply.action_discard_backup()
        return self._apply_dict(apply, cast("StudioPackage", apply.package_id))

    @api.model
    def apply_diff(self, apply_id: int, path: str) -> DriftDiffJSON:
        """What an apply changed in one file: its backup against the disk now."""
        typed.security(self)._assert_studio_user()
        apply = typed.model(self.env, StudioPackageApply).browse(apply_id).exists()
        if not apply:
            raise UserError(_("That apply no longer exists."))
        entry = cast("StudioPackageApplyFile", apply.file_ids).filtered(
            lambda f: f.path == path
        )[:1]
        if not entry:
            raise UserError(_("%s was not part of that apply.", path))
        before = cast("str", entry.content_before) if entry.existed else None
        after = cast("StudioPackage", apply.package_id)._read_source(path)
        return {"diff": self._unified(before, after, path, "before", "now")}

    # -- the user ------------------------------------------------------------

    @api.model
    def user_prefs(self) -> UserPrefsJSON:
        typed.security(self)._assert_studio_user()
        # `res_users.py` adds `studio_prefs` via `_inherit = "res.users"`
        # (its own class `ResUsers`), not on core `Users` -- the same
        # `_inherit`-invisible-to-pyright gap as any other cross-file
        # extension, cast to the class that actually declares the field.
        raw = cast("ResUsers", self.env.user).sudo().studio_prefs or "{}"
        try:
            prefs = json.loads(raw)
        except ValueError:
            prefs = {}
        return cast("UserPrefsJSON", {key: prefs.get(key) for key in PREF_KEYS})

    @api.model
    def set_user_pref(self, key: str, value: Any) -> UserPrefsJSON:
        typed.security(self)._assert_studio_user()
        if key not in PREF_KEYS:
            raise UserError(_("Not something the studio remembers: %s", key))
        # `user_prefs()` returns the closed `UserPrefsJSON` shape, but `key`
        # here is a runtime string, not one of its literal field names --
        # TypedDict subscript assignment needs a literal key, so the dict is
        # widened back to `dict[str, Any]` for this one dynamic-key write,
        # then narrowed back on return.
        prefs = cast("dict[str, Any]", self.user_prefs())
        if key == "recent_models":
            value = [v for v in (value or []) if isinstance(v, str)][:RECENT_MODELS]
        prefs[key] = value
        self.env.user.sudo().write({"studio_prefs": json.dumps(prefs)})
        return cast("UserPrefsJSON", prefs)

    @api.model
    def remember_model(self, model_name: str) -> UserPrefsJSON:
        """Move ``model_name`` to the front of the user's recent list."""
        typed.security(self)._assert_studio_user()
        recent = [
            m for m in (self.user_prefs().get("recent_models") or []) if m != model_name
        ]
        return self.set_user_pref("recent_models", [model_name] + recent)

    @api.model
    def checklist(self, package_id: int | None = None) -> ChecklistJSON:
        """Which of the getting-started steps have happened, from what exists."""
        typed.security(self)._assert_studio_user()
        package = self._package(package_id) if package_id else None
        if package is None:
            return {
                "package": False,
                "app": False,
                "field": False,
                "automation": False,
                "commit": False,
            }
        Data = typed.model(self.env, IrModelData).sudo()

        def owned(model: str) -> int:
            return Data.search_count(
                [("module", "=", package.name), ("model", "=", model)]
            )

        applied_edit = typed.model(self.env, StudioPackageApply).search_count(
            [
                ("package_id", "=", package.id),
                ("state", "in", ("applied", "awaiting_restart")),
                ("reason", "like", "edit %"),
            ]
        )
        return {
            "package": True,
            "app": bool(
                cast("StudioPackageModel", package.model_ids).filtered(
                    lambda m: not m.extends
                )
            ),
            "field": bool(applied_edit or owned("ir.model.fields")),
            "automation": bool(owned("base.automation")),
            "commit": package.is_git
            and bool(gitrepo.log(cast("str", package.root_path), 1)),
        }
