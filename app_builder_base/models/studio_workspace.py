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

import difflib
import json
import os

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..tools import gitrepo
from .studio_package import RESERVED_NAMES

# Keys a user may keep about their own use of the studio. Whitelisted so
# the preference blob stays a small, known shape rather than a scratchpad.
PREF_KEYS = ("last_package_id", "checklist_dismissed", "recent_models", "sidebar_width")
RECENT_MODELS = 8
DIFF_LIMIT = 200_000
APPLY_LIMIT = 50
LOG_LIMIT = 20


class StudioWorkspace(models.AbstractModel):
    _name = "studio.workspace"
    _inherit = ["studio.security.mixin"]
    _description = "Studio Workspace"

    # -- packages -----------------------------------------------------------

    @api.model
    def packages(self, include_git=True):
        """Every package, with what the home and the switcher need to say.

        Abandoned applies are reaped first, so a process that died mid-apply
        shows up here as a failed apply with a rollback on offer rather than
        as a row that stays pending for ever.
        """
        self._assert_studio_user()
        # Read as superuser once the guard has passed: the facts a builder
        # sees here (xmlids, module rows, applies) are ones the ACLs of
        # those models do not grant a plain user, and nothing is written.
        packages = self.env["studio.package"].sudo().search([])
        self.env["studio.package.apply"].sudo()._reap_abandoned(packages)
        suggested = self.env["studio.package"].sudo()._suggested()
        return [
            self._package_dict(package, include_git=include_git, suggested=suggested)
            for package in packages
        ]

    @api.model
    def package(self, package_id):
        """One package, with its manifest and files as well."""
        self._assert_studio_user()
        package = self._package(package_id)
        self.env["studio.package.apply"].sudo()._reap_abandoned(package)
        out = self._package_dict(
            package, suggested=self.env["studio.package"].sudo()._suggested()
        )
        out.update(
            {
                "depends": [d.strip() for d in (package.depends or "").split(",") if d],
                "category": package.category or "",
                "author": package.author or "",
                "license": package.license or "",
                "auto_commit": package.auto_commit,
                "files": [
                    {"path": f.path, "drifted": f.drifted}
                    for f in package.file_ids.sorted("path")
                ],
            }
        )
        return out

    @api.model
    def _package(self, package_id):
        """The package, as superuser: the guard is on the caller, and what
        is read about a package -- xmlids, module rows, applies -- is more
        than a Studio Builder's own ACLs grant."""
        package = self.env["studio.package"].sudo().browse(package_id).exists()
        if not package:
            raise UserError(_("That package no longer exists."))
        return package

    @api.model
    def _package_dict(self, package, include_git=True, suggested=None):
        Apply = self.env["studio.package.apply"].sudo()
        applies = Apply.search([("package_id", "=", package.id)])
        by_state = {}
        for apply in applies:
            by_state[apply.state] = by_state.get(apply.state, 0) + 1
        last = applies[:1]
        module = (
            self.env["ir.module.module"]
            .sudo()
            .search([("name", "=", package.name)], limit=1)
        )
        module_state = module.state if module else "unknown"
        python = package.model_ids.filtered(lambda m: not m.extends)
        models = {
            "python": len(python.filtered(lambda m: m.source == "python")),
            "frozen": len(python.filtered(lambda m: m.source == "frozen")),
            "extends": len(package.model_ids.filtered("extends")),
            "xml": len(package._owned_model_names() - package._python_model_set()),
        }
        git = {"is_git": package.is_git, "branch": package.git_branch or ""}
        if include_git and package.is_git:
            status = self._git_status(package)
            git["dirty"] = len([e for e in status if e["state"] != "??"])
            git["untracked"] = len([e for e in status if e["state"] == "??"])
        else:
            git["dirty"] = git["untracked"] = 0
        drafts = self._drafts(package)
        drift_count = len(package.file_ids.filtered("drifted"))

        health = []
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
            "id": package.id,
            "name": package.name,
            "title": package.display_name_ or package.name,
            "summary": package.summary or "",
            "version": package.version,
            "root_path": package.root_path or "",
            "writable": package.writable,
            "reload_mode": package.reload_mode,
            "state": package.state,
            "drift_count": drift_count,
            "file_count": len(package.file_ids),
            "record_count": package.record_count,
            "module_state": module_state,
            "git": git,
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
    def addons_dirs(self):
        """Where a package may be created: the addons path, as it is.

        Odoo builds ``odoo.addons.__path__`` once at start-up, so a package
        has to live directly under one of these to be found at all. Core's
        own directories are listed and never offered: a package written
        into ``odoo/addons`` would be a patch on the upstream checkout.
        """
        self._assert_studio_user()
        import odoo

        import odoo.addons

        core_root = os.path.dirname(os.path.dirname(os.path.abspath(odoo.__file__)))
        Package = self.env["studio.package"]
        out = []
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
    def create_package(self, values):
        """Make a package from the console, refusing what would not load.

        ``studio.package`` validates the name; everything else about where
        a package can live was found out later -- by ``_find_or_create_module``
        raising on the first install. Checked here instead, with a sentence
        each, so the first thing a user does in the studio cannot fail
        twenty minutes later.
        """
        self._assert_studio_manager()
        Package = self.env["studio.package"]
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
            self.env["ir.module.module"].sudo().search([("name", "=", name)], limit=1)
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
            {
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
            gitrepo.init(package.root_path)
            package.invalidate_recordset(["is_git", "git_branch"])
        return self.package(package.id)

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
    def _inventory_group(self, model_name, record):
        """Which list of the inventory a record belongs in.

        Overridden by the addons that know a model this one does not:
        ``base.automation`` lands in ``automations`` and ``tier.definition``
        in ``approvals`` only when those addons say so.
        """
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
    def inventory(self, package_id):
        """Everything the package owns, grouped by what it is, plus its models.

        Ownership is ``ir.model.data.module``, the same rule the serializer
        uses, so this lists exactly what the files declare. A model appears
        whether it is defined in Python, extended, frozen or still a set of
        data records the package owns but has not adopted.
        """
        self._assert_studio_user()
        package = self._package(package_id)
        serializers = package._serializer_env()
        groups = {key: [] for key in self.INVENTORY_GROUPS}
        subject_counts = {}
        for model_name, entries in package._owned_records().items():
            serializer = serializers._for_model(model_name)
            for xmlid, record in entries:
                group = self._inventory_group(model_name, record)
                # An AbstractModel recordset is empty and therefore falsy;
                # the question is whether a serializer exists at all.
                has_serializer = serializer is not None
                subject = serializer._group_model(record) if has_serializer else None
                target = serializer._target_file(record) if has_serializer else None
                entry = {
                    "id": record.id,
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
        groups["models"] = self._inventory_models(package, subject_counts)
        return groups

    @api.model
    def _inventory_models(self, package, subject_counts):
        IrModel = self.env["ir.model"].sudo()
        View = self.env["ir.ui.view"].sudo()
        owned_field_ids = package._owned_field_ids()
        out = []
        rows = {m.model: m for m in package.model_ids}
        names = set(rows) | package._owned_model_names()
        for model_name in sorted(names):
            row = rows.get(model_name)
            ir_model = IrModel.search([("model", "=", model_name)], limit=1)
            in_registry = model_name in self.env
            if row is not None:
                source = "extends" if row.extends else row.source
            else:
                source = "xml"
            fields_ = ir_model.field_id if ir_model else IrModel.browse().field_id
            owned = len([f for f in fields_ if f.id in owned_field_ids])
            view_types = [
                view_type
                for (view_type,) in View._read_group(
                    [("model", "=", model_name), ("mode", "=", "primary")], ["type"]
                )
            ]
            counts = subject_counts.get(model_name, {})
            out.append(
                {
                    "model": model_name,
                    "display_name": ir_model.name if ir_model else model_name,
                    "id": ir_model.id if ir_model else False,
                    "source": source,
                    "parse_error": (row.parse_error or "") if row is not None else "",
                    "python_path": row.python_path if row is not None else "",
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
    def models_for_picker(self, package_id=None):
        """The models the crumb offers: the package's own, the ones it
        touches, and the ones this user opened last."""
        self._assert_studio_user()
        defined, extended = [], []
        if package_id:
            package = self._package(package_id)
            inventory = self.inventory(package.id)
            defined = [
                {
                    "model": m["model"],
                    "display_name": m["display_name"],
                    "source": m["source"],
                }
                for m in inventory["models"]
            ]
            defined_names = {m["model"] for m in defined}
            touched = {}
            for key, entries in inventory.items():
                if key == "models":
                    continue
                for entry in entries:
                    subject = entry["subject"]
                    if subject and subject not in defined_names:
                        touched[subject] = touched.get(subject, 0) + 1
            IrModel = self.env["ir.model"].sudo()
            for model_name in sorted(touched):
                ir_model = IrModel.search([("model", "=", model_name)], limit=1)
                extended.append(
                    {
                        "model": model_name,
                        "display_name": ir_model.name if ir_model else model_name,
                        "count": touched[model_name],
                    }
                )
        recent = []
        IrModel = self.env["ir.model"].sudo()
        for model_name in self.user_prefs().get("recent_models") or []:
            if model_name in self.env:
                ir_model = IrModel.search([("model", "=", model_name)], limit=1)
                recent.append(
                    {
                        "model": model_name,
                        "display_name": ir_model.name if ir_model else model_name,
                    }
                )
        return {"defined": defined, "extended": extended, "recent": recent}

    # -- changes -------------------------------------------------------------

    @api.model
    def changes(self, package_id):
        """The Changes pane: drift, git, applies and drafts, in one call."""
        self._assert_studio_user()
        package = self._package(package_id)
        self.env["studio.package.apply"].sudo()._reap_abandoned(package)
        package.action_check_drift()
        drift, files = [], []
        for entry in package.file_ids.sorted("path"):
            status = "in_sync"
            if entry.drifted:
                status = "missing" if not entry.disk_checksum else "edited"
                drift.append({"path": entry.path, "status": status})
            files.append({"path": entry.path, "status": status})
        git = {
            "is_git": package.is_git,
            "branch": package.git_branch or "",
            "status": self._git_status(package) if package.is_git else [],
            "log": gitrepo.log(package.root_path, LOG_LIMIT) if package.is_git else [],
            "auto_commit": package.auto_commit,
        }
        applies = (
            self.env["studio.package.apply"]
            .sudo()
            .search([("package_id", "=", package.id)], limit=APPLY_LIMIT)
        )
        return {
            "package": self._package_dict(
                package, suggested=self.env["studio.package"].sudo()._suggested()
            ),
            "drift": drift,
            "files": files,
            "pending_write": package.state == "dirty",
            "git": git,
            "applies": [self._apply_dict(apply, package) for apply in applies],
            "drafts": self._drafts(package),
        }

    @api.model
    def _git_status(self, package):
        """Porcelain entries, package-relative, for the package's files only.

        ``git status`` speaks in repository-root paths; a package that is one
        directory of a larger repository has to strip its own prefix, and
        anything outside it is somebody else's change.
        """
        root = package.root_path
        top = gitrepo.toplevel(root)
        if not top:
            return []
        prefix = os.path.relpath(os.path.realpath(root), os.path.realpath(top))
        prefix = "" if prefix == "." else prefix.rstrip(os.sep) + os.sep
        out = []
        for code, path in gitrepo.status(root):
            # A rename is "old -> new"; the new name is the one that exists.
            path = path.split(" -> ")[-1].strip('"')
            if prefix and not path.startswith(prefix):
                continue
            out.append({"path": path[len(prefix) :], "state": code or "M"})
        return out

    @api.model
    def _apply_dict(self, apply, package):
        return {
            "id": apply.id,
            "reason": apply.reason or "",
            "state": apply.state,
            "error": apply.error or "",
            "create_date": fields.Datetime.to_string(apply.create_date),
            "user": {"id": apply.create_uid.id, "name": apply.create_uid.name},
            "backup_path": apply.backup_path or "",
            "has_backup": bool(apply.backup_path and os.path.isdir(apply.backup_path)),
            "files": [{"path": f.path, "existed": f.existed} for f in apply.file_ids],
            "can_rollback": apply.state in ("applied", "failed", "awaiting_restart")
            and package.writable
            and bool(apply.file_ids),
        }

    @api.model
    def _drafts(self, package):
        Draft = self.env["studio.model.draft"].sudo()
        out = []
        for draft in Draft.search([("package_id", "=", package.id)]):
            if not draft.dirty:
                continue
            out.append(
                {
                    "id": draft.id,
                    "model": draft.model,
                    "change_count": draft.change_count,
                    "user": {"id": draft.create_uid.id, "name": draft.create_uid.name},
                    "mine": draft.create_uid == self.env.user,
                    "write_date": fields.Datetime.to_string(draft.write_date),
                }
            )
        return out

    @api.model
    def git_diff(self, package_id, path=None):
        self._assert_studio_user()
        package = self._package(package_id)
        if not package.is_git:
            return {"diff": "", "truncated": False}
        paths = [os.path.join(package.root_path, path)] if path else None
        diff = gitrepo.diff(package.root_path, paths)
        return {"diff": diff[:DIFF_LIMIT], "truncated": len(diff) > DIFF_LIMIT}

    @api.model
    def drift_diff(self, package_id, path):
        """What the database would write against what is on disk."""
        self._assert_studio_user()
        package = self._package(package_id)
        generated = package._render_files().get(path)
        on_disk = package._read_source(path)
        return {"diff": self._unified(generated, on_disk, path, "generated", "on disk")}

    @api.model
    def _unified(self, before, after, path, from_label, to_label):
        diff = difflib.unified_diff(
            (before or "").splitlines(keepends=True),
            (after or "").splitlines(keepends=True),
            fromfile="%s (%s)" % (path, from_label),
            tofile="%s (%s)" % (path, to_label),
        )
        return "".join(diff)[:DIFF_LIMIT]

    @api.model
    def commit(self, package_id, message):
        """Commit everything under the package, and nothing beside it."""
        self._assert_studio_manager()
        package = self._package(package_id)
        if not package.is_git:
            return {"committed": False, "reason": _("Not a git repository.")}
        message = (message or "").strip()
        if not message:
            raise UserError(_("A commit needs a message."))
        sha = gitrepo.commit(package.root_path, message)
        if not sha:
            return {"committed": False, "reason": _("Nothing to commit.")}
        return {"committed": True, "sha": sha}

    @api.model
    def git_init(self, package_id):
        self._assert_studio_manager()
        package = self._package(package_id)
        package._assert_writable()
        ok = gitrepo.init(package.root_path)
        package.invalidate_recordset(["is_git", "git_branch"])
        return {"is_git": bool(ok and package.is_git)}

    @api.model
    def set_auto_commit(self, package_id, value):
        self._assert_studio_manager()
        package = self._package(package_id)
        package.write({"auto_commit": value})
        return {"auto_commit": package.auto_commit}

    # -- package actions, as dicts ---------------------------------------------

    @api.model
    def check_drift(self, package_id):
        self._assert_studio_user()
        package = self._package(package_id)
        package.action_check_drift()
        return {
            "state": package.state,
            "drift_count": len(package.file_ids.filtered("drifted")),
        }

    @api.model
    def write_files(self, package_id):
        self._assert_studio_manager()
        package = self._package(package_id)
        package.action_write_files()
        return {"state": package.state}

    @api.model
    def reload(self, package_id):
        """Read the package from disk into the database, where that is possible."""
        self._assert_studio_manager()
        package = self._package(package_id)
        if package.reload_mode == "manual":
            return {"restart_required": True, "reloaded": False}
        package.action_reload()
        return {"restart_required": False, "reloaded": True, "state": package.state}

    @api.model
    def delete_records(self, package_id):
        self._assert_studio_manager()
        package = self._package(package_id)
        package.action_delete_records()
        return {"state": package.state}

    @api.model
    def apply(self, package_id, reason="", allow_destructive=False):
        self._assert_studio_manager()
        package = self._package(package_id)
        apply = package.action_apply(reason=reason, allow_destructive=allow_destructive)
        return self._apply_dict(apply, package)

    @api.model
    def rollback(self, apply_id):
        self._assert_studio_manager()
        apply = self.env["studio.package.apply"].browse(apply_id).exists()
        if not apply:
            raise UserError(_("That apply no longer exists."))
        result = apply.action_rollback()
        result["apply"] = self._apply_dict(apply, apply.package_id)
        return result

    @api.model
    def discard_backup(self, apply_id):
        self._assert_studio_manager()
        apply = self.env["studio.package.apply"].browse(apply_id).exists()
        if not apply:
            raise UserError(_("That apply no longer exists."))
        apply.action_discard_backup()
        return self._apply_dict(apply, apply.package_id)

    @api.model
    def apply_diff(self, apply_id, path):
        """What an apply changed in one file: its backup against the disk now."""
        self._assert_studio_user()
        apply = self.env["studio.package.apply"].browse(apply_id).exists()
        if not apply:
            raise UserError(_("That apply no longer exists."))
        entry = apply.file_ids.filtered(lambda f: f.path == path)[:1]
        if not entry:
            raise UserError(_("%s was not part of that apply.", path))
        before = entry.content_before if entry.existed else None
        after = apply.package_id._read_source(path)
        return {"diff": self._unified(before, after, path, "before", "now")}

    # -- the user ------------------------------------------------------------

    @api.model
    def user_prefs(self):
        self._assert_studio_user()
        raw = self.env.user.sudo().studio_prefs or "{}"
        try:
            prefs = json.loads(raw)
        except ValueError:
            prefs = {}
        return {key: prefs.get(key) for key in PREF_KEYS}

    @api.model
    def set_user_pref(self, key, value):
        self._assert_studio_user()
        if key not in PREF_KEYS:
            raise UserError(_("Not something the studio remembers: %s", key))
        prefs = self.user_prefs()
        if key == "recent_models":
            value = [v for v in (value or []) if isinstance(v, str)][:RECENT_MODELS]
        prefs[key] = value
        self.env.user.sudo().write({"studio_prefs": json.dumps(prefs)})
        return prefs

    @api.model
    def remember_model(self, model_name):
        """Move ``model_name`` to the front of the user's recent list."""
        self._assert_studio_user()
        recent = [
            m for m in (self.user_prefs().get("recent_models") or []) if m != model_name
        ]
        return self.set_user_pref("recent_models", [model_name] + recent)

    @api.model
    def checklist(self, package_id=None):
        """Which of the getting-started steps have happened, from what exists."""
        self._assert_studio_user()
        package = self._package(package_id) if package_id else None
        if package is None:
            return {
                "package": False,
                "app": False,
                "field": False,
                "automation": False,
                "commit": False,
            }
        Data = self.env["ir.model.data"].sudo()

        def owned(model):
            return Data.search_count(
                [("module", "=", package.name), ("model", "=", model)]
            )

        applied_edit = self.env["studio.package.apply"].search_count(
            [
                ("package_id", "=", package.id),
                ("state", "in", ("applied", "awaiting_restart")),
                ("reason", "like", "edit %"),
            ]
        )
        return {
            "package": True,
            "app": bool(package.model_ids.filtered(lambda m: not m.extends)),
            "field": bool(applied_edit or owned("ir.model.fields")),
            "automation": bool(owned("base.automation")),
            "commit": package.is_git and bool(gitrepo.log(package.root_path, 1)),
        }
