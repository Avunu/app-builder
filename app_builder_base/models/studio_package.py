# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""A studio package: one Odoo addon directory, managed as a record.

The package is the unit that ties the three halves together -- the records in
the database, the files on disk, and the git history. Its job is to keep them
in agreement and to be honest when they are not.
"""

import logging
import os

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.base.models.ir_model import (
    field_xmlid,
    model_xmlid,
    selection_xmlid,
)

from ..tools import checksum, gitrepo, pycodegen, xml_writer
from ..tools import manifest as manifest_tools

_logger = logging.getLogger(__name__)

# Module names Odoo core treats specially; graph.py hardcodes the first one out
# of the dependency graph entirely, so a package named that would silently
# never load.
RESERVED_NAMES = ("studio_customization",)

# Every menu lands here; see IrUiMenuSerializer._target_file.
MENUS_FILE = "views/menus.xml"

# Teardown order: dependants before their dependencies, so no unlink hits a
# restrict/cascade surprise.
UNLINK_ORDER = (
    "ir.ui.menu",
    "base.automation",
    "ir.actions.act_window.view",
    "ir.actions.act_window",
    "ir.actions.server",
    "ir.actions.report",
    "ir.ui.view",
    "ir.model.access",
    "ir.rule",
    "ir.model.fields.selection",
    "ir.model.fields",
    "ir.model",
)

STATES = [
    ("draft", "Draft"),
    ("synced", "In sync"),
    ("dirty", "Pending write"),
    ("drifted", "Edited on disk"),
    ("missing", "Files missing"),
]


class StudioPackage(models.Model):
    _name = "studio.package"
    _description = "Studio Package"
    _order = "name"

    name = fields.Char(
        required=True,
        help="Technical module name. Becomes the directory name and the "
        "xmlid prefix for everything the package owns.",
    )
    display_name_ = fields.Char(string="Title", required=True, default="Studio Package")
    summary = fields.Char()
    version = fields.Char(default="18.0.1.0.0", required=True)
    category = fields.Char(default="Customization")
    author = fields.Char(default="App Builder")
    license = fields.Char(default="AGPL-3")
    depends = fields.Char(
        default="base",
        required=True,
        help="Comma-separated module names for the manifest 'depends' key.",
    )

    root_path = fields.Char(
        compute="_compute_root_path",
        store=True,
        readonly=False,
        help="Absolute path of the addon directory.",
    )
    writable = fields.Boolean(compute="_compute_writable")
    state = fields.Selection(STATES, default="draft", readonly=True)

    file_ids = fields.One2many("studio.package.file", "package_id", readonly=True)
    record_count = fields.Integer(compute="_compute_record_count")

    graduated_models = fields.Char(
        readonly=True,
        help="Comma-separated models that have been converted to Python classes. "
        "The builder stops emitting XML metadata for these and will not "
        "overwrite their source files.",
    )

    is_git = fields.Boolean(compute="_compute_git_info")
    git_branch = fields.Char(compute="_compute_git_info")
    auto_commit = fields.Selection(
        [("off", "Off"), ("stage", "Stage only"), ("commit", "Commit each change")],
        default="stage",
        required=True,
        help="What to do with git after each write.",
    )

    _sql_constraints = [
        (
            "name_uniq",
            "unique(name)",
            "A studio package with this name already exists.",
        ),
    ]

    # -- constraints ------------------------------------------------------

    @api.constrains("name")
    def _check_name(self):
        for package in self:
            if package.name in RESERVED_NAMES:
                raise ValidationError(
                    _(
                        "'%s' is reserved by Odoo core (it is excluded from the "
                        "module dependency graph) and cannot be used.",
                        package.name,
                    )
                )
            if not package.name or not package.name.isidentifier():
                raise ValidationError(
                    _("'%s' is not a valid Python module name.", package.name)
                )

    # -- computes ---------------------------------------------------------

    @api.depends("name")
    def _compute_root_path(self):
        base = self.env["studio.package"]._default_addons_dir()
        for package in self:
            if not package.root_path and package.name:
                package.root_path = os.path.join(base, package.name)
            elif not package.root_path:
                package.root_path = False

    def _compute_writable(self):
        for package in self:
            path = package.root_path
            if not path:
                package.writable = False
                continue
            probe = path if os.path.isdir(path) else os.path.dirname(path)
            package.writable = bool(probe) and os.access(probe, os.W_OK)

    def _compute_record_count(self):
        for package in self:
            package.record_count = self.env["ir.model.data"].search_count(
                [("module", "=", package.name)]
            )

    def _compute_git_info(self):
        for package in self:
            path = package.root_path
            package.is_git = bool(path) and gitrepo.is_repo(path)
            package.git_branch = (
                gitrepo.current_branch(path) if package.is_git else False
            )

    # -- addons path ------------------------------------------------------

    @api.model
    def _default_addons_dir(self):
        """Pick a writable addons_path entry to create packages in.

        A brand-new addons *directory* cannot be registered at runtime -- Odoo
        builds ``odoo.addons.__path__`` once at startup from the config -- so a
        package must be created inside a path the server already knows about.
        Preferring a directory literally named 'custom' matches the odoo-nix
        layout, where that is the project's own writable addon root.
        """
        import odoo.addons

        candidates = [p for p in odoo.addons.__path__ if os.access(p, os.W_OK)]
        if not candidates:
            return ""
        for path in candidates:
            if os.path.basename(path.rstrip(os.sep)) == "custom":
                return path
        return candidates[0]

    # -- serialization ----------------------------------------------------

    def _serializer_env(self, dep_sink=None):
        """Serializers need the package name to shorten same-module refs.

        ``dep_sink`` is a set the serializers add foreign module names to as
        they emit refs, which is how the manifest learns what it depends on.

        ``lang=None`` is load-bearing, not tidiness. Many of the fields we emit
        are ``translate=True`` (ir.model.name, field_description, help, menu and
        action names) and ``ir.ui.view.arch_db`` uses ``xml_translate``, so
        reading them in the acting user's language would emit the *translation*.
        Odoo's importer pins ``lang=None`` (convert.py:630), so that translation
        would then be written back as the en_US source term -- destroying the
        original string and losing the translation. It would also make the bytes
        depend on who happened to click save.
        """
        self.ensure_one()
        return self.env["studio.serializer"].with_context(
            studio_package=self.name,
            studio_dep_sink=dep_sink,
            lang=None,
        )

    def _source_env(self):
        """Env for reading records during serialization: source language only."""
        self.ensure_one()
        return self.env(context=dict(self.env.context, lang=None))

    def _owned_records(self):
        """Group the package's records by model, keyed by xmlid.

        Ownership is defined by ``ir.model.data.module``, which is exactly what
        loading the generated files would produce -- so the DB->file and
        file->DB directions agree on the record set by construction.
        """
        self.ensure_one()
        # Browse in the source language: the records themselves are read here,
        # and a translated value read in the user's lang would be emitted as if
        # it were the source term. See _serializer_env.
        env = self._source_env()
        data = env["ir.model.data"].search([("module", "=", self.name)])
        serializers = self._serializer_env()
        grouped = {}
        for entry in data:
            if entry.model not in env:
                continue
            record = env[entry.model].browse(entry.res_id)
            if not record.exists():
                continue
            serializer = serializers._for_model(entry.model)
            if serializer is not None and not serializer._ownable(record):
                continue
            grouped.setdefault(entry.model, []).append(
                ("%s.%s" % (entry.module, entry.name), record)
            )
        return grouped

    def _graduated_set(self):
        self.ensure_one()
        return {
            m.strip() for m in (self.graduated_models or "").split(",") if m.strip()
        }

    def _owned_model_names(self):
        """Custom models this package owns, graduated or not.

        Read straight from ir.model.data rather than from ``_owned_records``,
        because the latter deliberately hides already-graduated metadata.
        """
        self.ensure_one()
        entries = self.env["ir.model.data"].search(
            [("module", "=", self.name), ("model", "=", "ir.model")]
        )
        records = self.env["ir.model"].browse(entries.mapped("res_id")).exists()
        return set(records.mapped("model"))

    # NB: there is deliberately no "is this model graduated?" filter here.
    # Graduation demotes the metadata to state='base', and `_ownable` already
    # excludes that -- so the XML stops being emitted as a consequence of the
    # data, not of a flag. Filtering on the flag instead was an active bug: a
    # field added to an already-graduated model is manual, belongs in XML
    # (exactly as Studio adds fields to core models), and was being written to
    # no file at all.

    def _render_files(self):
        """Render every generated file. Returns ``{relative_path: content}``."""
        self.ensure_one()
        # Modules our refs point at; becomes the manifest 'depends'.
        dep_sink = set()
        serializers = self._serializer_env(dep_sink)
        # (file, sort_key) -> node, accumulated then ordered in one pass so the
        # result never depends on database iteration order.
        buckets = {}
        csv_rows = {}

        for model, entries in self._owned_records().items():
            serializer = serializers._for_model(model)
            if serializer is None:
                continue
            serializer = serializer.with_context(
                studio_package=self.name, studio_dep_sink=dep_sink
            )
            for xmlid, record in entries:
                target = serializer._target_file(record)
                key = serializer._sort_key(record, xmlid)
                if serializer._studio_format == "csv":
                    csv_rows.setdefault(target, []).append(
                        (key, serializer._csv_row(record, xmlid))
                    )
                else:
                    node = serializer._serialize(record, xmlid)
                    buckets.setdefault(target, []).append(
                        (key, node, serializer._studio_noupdate)
                    )

        files = {}
        for target, items in buckets.items():
            items.sort(key=lambda item: item[0])
            plain = [node for _key, node, nou in items if not nou]
            noupdate = [node for _key, node, nou in items if nou]
            root = xml_writer.build_document(plain, noupdate)
            files[target] = xml_writer.serialize_document(root)

        for target, rows in csv_rows.items():
            rows.sort(key=lambda item: item[0])
            access = serializers._for_model("ir.model.access")
            files[target] = access._render_csv([row for _key, row in rows])

        # Graduated models become Python source rather than XML metadata.
        python_files = self._render_python()
        files.update(python_files)

        files["__manifest__.py"] = self._render_manifest(sorted(files), dep_sink)
        files["__init__.py"] = pycodegen.render_package_init(bool(python_files))
        return files

    def _render_python(self):
        """Render ``models/*.py`` for every graduated model.

        Returns an empty dict when nothing has graduated, which keeps the
        generated addon data-only -- and therefore reloadable without a server
        restart -- for as long as the user wants it that way.

        Graduation is a **one-way handoff**: a model file is generated once and
        then belongs to the developer. Regenerating would be actively wrong,
        because once the Python class loads, reflection flips its fields to
        ``state='base'`` and there is no longer any manual metadata to render --
        we would overwrite a working class with an empty one.
        """
        self.ensure_one()
        graduated = sorted(self._graduated_set())
        if not graduated:
            return {}

        files = {}
        emitted = []
        for model_name in graduated:
            relative = "models/%s" % pycodegen.module_file_for(model_name)
            existing = self._read_source(relative)
            if existing is not None:
                files[relative] = existing
                emitted.append(model_name)
                continue

            model = self.env["ir.model"].search([("model", "=", model_name)], limit=1)
            if not model:
                _logger.warning(
                    "Package %s lists %s as graduated but no such model exists",
                    self.name,
                    model_name,
                )
                continue
            # Only fields this package owns: Odoo declares the magic columns
            # itself, and a field from another module is not ours to redeclare.
            owned = model.field_id.filtered(lambda f: f.state == "manual")
            files[relative] = pycodegen.render_model(model, owned)
            emitted.append(model_name)

        if emitted:
            files["models/__init__.py"] = self._render_models_init(emitted)
        return files

    def _read_source(self, relative):
        """Return the on-disk content of a package file, or ``None``."""
        self.ensure_one()
        full = os.path.join(self.root_path or "", relative)
        if not os.path.isfile(full):
            return None
        with open(full, encoding="utf-8") as handle:
            return handle.read()

    def _render_models_init(self, model_names):
        """Regenerate ``models/__init__.py``, keeping hand-added imports.

        Same tolerance as the manifest merge: a developer may add their own
        module next to the graduated ones and must not lose it on the next
        write.
        """
        self.ensure_one()
        generated = pycodegen.render_models_init(model_names)
        existing = self._read_source("models/__init__.py")
        if not existing:
            return generated
        wanted = set(generated.splitlines())
        extra = [
            line
            for line in existing.splitlines()
            if line.strip().startswith("from . import") and line not in wanted
        ]
        if not extra:
            return generated
        return "%s%s\n" % (generated, "\n".join(sorted(extra)))

    def _render_manifest(self, data_files, dep_sink=None):
        """Build the manifest, preserving hand-edited keys."""
        self.ensure_one()
        existing = {}
        path = os.path.join(self.root_path or "", "__manifest__.py")
        if os.path.isfile(path):
            try:
                existing = manifest_tools.read_manifest(path)
            except (SyntaxError, ValueError) as err:
                _logger.warning("Unparseable manifest at %s: %s", path, err)
        generated = {
            "name": self.display_name_ or self.name,
            "version": self.version,
            "category": self.category or "Customization",
            "author": self.author or "App Builder",
            "license": self.license or "AGPL-3",
            "installable": True,
            # Declared dependencies, plus every module we actually reference.
            # Deriving this rather than trusting the user is what makes a
            # generated package installable into a database that does not
            # already happen to contain what it points at.
            "depends": self._effective_depends(dep_sink),
            # Load order matters: models before views before security.
            "data": self._order_data_files(data_files),
        }
        if self.summary:
            generated["summary"] = self.summary
        return manifest_tools.render_manifest(
            manifest_tools.merge_manifest(existing, generated)
        )

    def _effective_depends(self, dep_sink=None):
        """Union of declared depends and modules referenced by our records."""
        self.ensure_one()
        declared = {d.strip() for d in (self.depends or "").split(",") if d.strip()}
        referenced = set(dep_sink or ())
        # 'base' is implicit but harmless (and conventional) to state.
        depends = (declared | referenced | {"base"}) - {self.name}
        return sorted(depends)

    @api.model
    def _order_data_files(self, paths):
        """Order manifest 'data' so every ref resolves when the file loads.

        A hand-written addon puts ``security/`` first because its groups are
        needed by everything else. We cannot: everything we emit under
        ``security/`` -- both the ACL csv and ir.rule -- carries a ``model_id``
        ref to an ``ir.model`` record that ``models/`` has not defined yet.
        Loading a rule first makes the generated package fail to install with an
        unresolvable external id, so security has to follow models here.
        """
        rank = {"models": 0, "data": 1, "security": 2, "views": 3, "report": 4}

        def key(path):
            head = rank.get(path.split("/")[0], 9)
            if path == MENUS_FILE:
                # Menus ref their action, so they must follow every view file
                # that defines one. Alphabetically "menus.xml" would sort first.
                return (head + 0.5, path)
            return (head, path)

        return sorted((p for p in paths if p.endswith((".xml", ".csv"))), key=key)

    # -- disk I/O ---------------------------------------------------------

    def _assert_writable(self):
        self.ensure_one()
        if not self.writable:
            raise UserError(
                _(
                    "The package directory '%s' is not writable. This is normal "
                    "on a production deployment: build packages in a development "
                    "environment and ship them through git.",
                    self.root_path or "",
                )
            )

    def action_write_files(self):
        """Serialize the package to disk and record checksums."""
        for package in self:
            package._assert_writable()
            files = package._render_files()
            written = package._write_files(files)
            package._sync_file_records(files)
            package._run_auto_commit(written)
            package.state = "synced"
        return True

    def _write_files(self, files):
        """Write rendered content, pruning generated files that vanished."""
        self.ensure_one()
        root = self.root_path
        os.makedirs(root, exist_ok=True)
        written = []
        for relative, content in files.items():
            full = os.path.join(root, relative)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            # Skip untouched files so mtimes stay stable and the FS watcher
            # does not fire a pointless reload.
            if checksum.hash_file(full) == checksum.hash_text(content):
                continue
            with open(full, "w", encoding="utf-8") as handle:
                handle.write(content)
            written.append(relative)

        for stale in self.file_ids.filtered(lambda f: f.path not in files):
            full = os.path.join(root, stale.path)
            # Only remove files we generated and that nobody has since edited.
            if os.path.isfile(full) and (
                checksum.hash_file(full) == stale.generated_checksum
            ):
                os.remove(full)
                written.append(stale.path)
        return written

    def _sync_file_records(self, files):
        self.ensure_one()
        existing = {f.path: f for f in self.file_ids}
        for relative, content in files.items():
            digest = checksum.hash_text(content)
            record = existing.pop(relative, None)
            if record:
                # Both checksums: disk_checksum drives `drifted`, so leaving it
                # at its previous value marks every file we just wrote as
                # drifted until someone runs a drift check.
                record.write({"generated_checksum": digest, "disk_checksum": digest})
            else:
                self.env["studio.package.file"].create(
                    {
                        "package_id": self.id,
                        "path": relative,
                        "generated_checksum": digest,
                        "disk_checksum": digest,
                    }
                )
        if existing:
            self.env["studio.package.file"].browse(
                [r.id for r in existing.values()]
            ).unlink()

    def _run_auto_commit(self, written):
        self.ensure_one()
        if not written or self.auto_commit == "off" or not self.is_git:
            return
        paths = [os.path.join(self.root_path, p) for p in written]
        if self.auto_commit == "stage":
            gitrepo.add(self.root_path, paths)
        else:
            gitrepo.commit(
                self.root_path,
                "studio(%s): update %s" % (self.name, ", ".join(sorted(written)[:5])),
                paths,
            )

    def studio_capture(self, records):
        """Take ownership of ``records`` and flush the package to disk.

        This is the single entry point every builder module calls after it
        changes something. Assigning the xmlid and writing the file happen in
        the caller's transaction, so the database and the source tree either
        both advance or both roll back -- which is what lets us treat the DB
        write as an optimisation rather than a second source of truth.
        """
        self.ensure_one()
        if not any(True for _rec in self._flatten(records)):
            return False
        self._assign(records)
        if self.writable:
            self.action_write_files()
        else:
            self.state = "dirty"
        return True

    # -- graduate to code -------------------------------------------------

    def action_graduate(self, model_names):
        """Convert manual models into real Python classes in this package.

        This is the capability Odoo Studio does not have: the customization
        stops being metadata and becomes source a developer owns. It is safe
        because the xmlids Odoo's reflection assigns to a code-defined model are
        the same ones we emitted in XML, so the records, the table and its data
        all survive; only where the definition *lives* changes.

        The new class only takes effect once the Python process reloads, which
        ``--dev=reload`` does automatically in development.
        """
        self.ensure_one()
        self._assert_writable()
        requested = {m.strip() for m in model_names if m and m.strip()}
        if not requested:
            raise UserError(_("Choose at least one model to graduate."))

        unknown = requested - self._owned_model_names()
        if unknown:
            raise UserError(
                _(
                    "This package does not own %(models)s, so it cannot graduate them.",
                    models=", ".join(sorted(unknown)),
                )
            )
        self._assert_module_installed()

        # Strict order. The metadata is the *input* to code generation and is
        # retired by it, so the Python must be on disk before the demotion; and
        # the XML must be rendered after it, so that _ownable (which excludes
        # state='base') naturally stops emitting what the class now defines.
        self._write_graduated_source(requested)
        self.graduated_models = ",".join(sorted(self._graduated_set() | requested))
        self._demote_manual_metadata(requested)
        self.action_write_files()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Graduated to code"),
                "message": _(
                    "%(models)s now live in models/ as Python. Restart the server "
                    "(or rely on --dev=reload) for the classes to take effect.",
                    models=", ".join(sorted(requested)),
                ),
                "type": "success",
                "sticky": True,
            },
        }

    def _assert_module_installed(self):
        """Refuse to graduate a package Odoo has not installed as a module.

        Odoo only imports Python for modules in the dependency graph. If the
        package is merely a directory of files that nobody installed, demoting
        the metadata removes the manual definition while nothing replaces it,
        and the model disappears from the registry at the next restart.
        """
        self.ensure_one()
        module = (
            self.env["ir.module.module"]
            .sudo()
            .search([("name", "=", self.name)], limit=1)
        )
        if module.state != "installed":
            raise UserError(
                _(
                    "Install the '%(name)s' module first (Reload from disk). "
                    "Odoo only loads Python for installed modules, so graduating "
                    "now would leave %(name)s with no definition at all after a "
                    "restart.",
                    name=self.name,
                )
            )

    def _write_graduated_source(self, model_names):
        """Emit the Python for ``model_names`` from their live metadata.

        Written directly rather than through ``action_write_files`` because
        this has to happen while the metadata still exists, and before the
        pruning pass that removes the XML it replaces.
        """
        self.ensure_one()
        env = self._source_env()
        root = self.root_path
        os.makedirs(os.path.join(root, "models"), exist_ok=True)
        emitted = sorted(self._graduated_set() | set(model_names))

        for model_name in sorted(model_names):
            relative = "models/%s" % pycodegen.module_file_for(model_name)
            if self._read_source(relative) is not None:
                continue  # one-way handoff: never overwrite
            model = env["ir.model"].search([("model", "=", model_name)], limit=1)
            if not model:
                continue
            owned = model.field_id.filtered(lambda f: f.state == "manual")
            with open(os.path.join(root, relative), "w", encoding="utf-8") as handle:
                handle.write(pycodegen.render_model(model, owned))

        with open(
            os.path.join(root, "models/__init__.py"), "w", encoding="utf-8"
        ) as handle:
            handle.write(self._render_models_init(emitted))
        with open(os.path.join(root, "__init__.py"), "w", encoding="utf-8") as handle:
            handle.write(pycodegen.render_package_init(True))

    def _demote_manual_metadata(self, model_names):
        """Retire the manual metadata rows, keeping the table and its data.

        Without this the graduation does not survive a restart. Two things go
        wrong if the ``state='manual'`` rows are left behind:

        * ``_add_manual_models`` rebuilds a custom class for the model from
          those rows on every ``setup_models``, competing with the Python class
          for the same ``_name``;
        * ``_process_end`` then finds the studio's ``ir.model.data`` rows absent
          from the freshly loaded data files and deletes the records outright --
          observed as "Deleting ...@ir.model (pkg.model_x_foo)".

        The rows are *reclassified*, not deleted. Deleting them would be
        catastrophic in two different ways: ``ir.model.fields.unlink`` calls
        ``_drop_column`` and would destroy the user's data, and every
        ``model_id`` in Odoo (``ir.model.access``, ``ir.rule``,
        ``ir.actions.server``, ``base.automation``) is ``ondelete='cascade'``,
        so removing the ``ir.model`` row silently takes the access rules and
        automations with it.

        Flipping ``state`` to 'base' achieves the same end with none of that:
        ``_add_manual_models`` and ``_add_manual_fields`` both select on
        ``state='manual'`` and therefore ignore these rows, leaving the Python
        class as the sole definition, while reflection updates the very same
        rows in place and re-registers their existing xmlids.

        Raw SQL because ``ir.model.write`` explicitly forbids changing ``state``
        (ir_model.py:386) -- which is right for ordinary use, and exactly what a
        controlled migration like this one needs to bypass.
        """
        self.ensure_one()
        names = sorted(model_names)
        if not names:
            return

        self.env.flush_all()
        self.env.cr.execute(
            """
            UPDATE ir_model_fields SET state = 'base'
             WHERE model IN %s AND state = 'manual'
            """,
            (tuple(names),),
        )
        self.env.cr.execute(
            "UPDATE ir_model SET state = 'base' WHERE model IN %s AND state = 'manual'",
            (tuple(names),),
        )
        self.env.invalidate_all()
        self.env.registry.clear_cache()
        _logger.info(
            "Graduated %s in package %s: metadata reclassified as base; "
            "tables, data, access rules and automations untouched",
            ", ".join(names),
            self.name,
        )

    # -- teardown ---------------------------------------------------------

    def action_delete_records(self):
        """Remove every record this package owns, leaving the files alone.

        Uses the same ``_force_unlink`` flag as Odoo's own
        ``_module_data_uninstall``: without it ``_prepare_update`` refuses to
        drop any column that carries module data.
        """
        self.ensure_one()
        data = self.env["ir.model.data"].search([("module", "=", self.name)])
        by_model = {}
        for entry in data:
            by_model.setdefault(entry.model, []).append(entry.res_id)

        env = self.env(context=dict(self.env.context, _force_unlink=True))
        for model in UNLINK_ORDER:
            res_ids = by_model.pop(model, [])
            if res_ids and model in env:
                env[model].browse(res_ids).exists().unlink()
        for model, res_ids in by_model.items():
            if model in env:
                env[model].browse(res_ids).exists().unlink()
        data.exists().unlink()
        # Forget which files we generated. The confirm dialog promises the
        # source is kept so the module can be reinstalled -- but the prune pass
        # in _write_files deletes any tracked file that no longer has records
        # behind it, so keeping these rows would let the next "Write to disk"
        # silently erase the very files we just promised to preserve.
        self.file_ids.unlink()
        self.state = "draft"
        return True

    # -- drift ------------------------------------------------------------

    def action_check_drift(self):
        """Compare disk against what we last generated."""
        for package in self:
            package.file_ids._refresh_disk_checksum()
            if not os.path.isdir(package.root_path or ""):
                package.state = "missing"
            elif any(f.drifted for f in package.file_ids):
                package.state = "drifted"
            elif package.state != "draft":
                package.state = "synced"
        return True

    def action_view_diff(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "studio.package",
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
            "context": dict(self.env.context, studio_diff=gitrepo.diff(self.root_path)),
        }

    # -- module lifecycle -------------------------------------------------

    def action_reload(self):
        """Re-read the package from disk into the database.

        This is the file->DB direction, and the repair path for drift. The two
        cache_clear calls are not optional: Odoo caches manifests in an
        lru_cache that nothing ever invalidates, and never calls
        importlib.invalidate_caches(), so without them a package edited on disk
        stays invisible for the lifetime of the process.
        """
        self.ensure_one()
        self._invalidate_module_caches()
        module = self._find_or_create_module()
        if module.state == "installed":
            action = module.button_immediate_upgrade()
        else:
            action = module.button_immediate_install()
        self.action_check_drift()
        # Returning Odoo's own {'tag': 'reload'} action matters: the registry
        # has just been rebuilt, so the browser is holding stale views and
        # menus until it reloads.
        return action

    @api.model
    def _invalidate_module_caches(self):
        import importlib

        from odoo.modules import module as module_tools

        cached = getattr(module_tools, "_get_manifest_cached", None)
        if cached is not None and hasattr(cached, "cache_clear"):
            cached.cache_clear()
        # get_manifest deep-copies from the cache above; clear it too if it is
        # independently memoised in this Odoo version.
        outer = getattr(module_tools, "get_manifest", None)
        if outer is not None and hasattr(outer, "cache_clear"):
            outer.cache_clear()
        importlib.invalidate_caches()

    def _find_or_create_module(self):
        self.ensure_one()
        Module = self.env["ir.module.module"]
        Module.update_list()
        module = Module.search([("name", "=", self.name)], limit=1)
        if not module:
            raise UserError(
                _(
                    "Odoo does not see a module named '%(name)s' at %(path)s. "
                    "The package must live inside a directory that was already "
                    "on addons_path when the server started.",
                    name=self.name,
                    path=self.root_path,
                )
            )
        return module

    def action_open_form(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "studio.package",
            "res_id": self.id,
            "view_mode": "form",
        }

    # -- xmlid allocation -------------------------------------------------

    @api.model
    def _flatten(self, records):
        """Yield individual records from a recordset or a list of them.

        A single studio operation typically touches several models at once (a
        model, its fields, a view, an action, a menu), and recordsets of
        different models cannot be concatenated -- so callers pass a list.
        """
        if isinstance(records, models.BaseModel):
            yield from records
            return
        for item in records or ():
            if isinstance(item, models.BaseModel):
                yield from item
            elif item:
                yield item

    def _assign(self, records, suggested_name=None):
        """Give ``records`` an xmlid in this package, creating it if needed.

        Everything the builder creates must be reachable by xmlid, otherwise it
        cannot be referenced from generated XML and cannot survive a reload.
        """
        self.ensure_one()
        Data = self.env["ir.model.data"]
        serializers = self._serializer_env()
        result = []
        for record in self._flatten(records):
            serializer = serializers._for_model(record._name)
            if serializer is not None and not serializer._ownable(record):
                # e.g. a model's magic columns, which arrive as part of
                # field_id but belong to Odoo, not to this package.
                continue
            existing = record.get_external_id().get(record.id)
            if existing:
                module = existing.partition(".")[0]
                if module != self.name:
                    # Silently returning here made "assign to my package" a
                    # no-op for anything another module already owns, and the
                    # record then never appeared in our source.
                    raise UserError(
                        _(
                            "%(record)s already belongs to module '%(owner)s'. A "
                            "record can only be written into one addon.",
                            record=record.display_name,
                            owner=module,
                        )
                    )
                result.append(existing)
                continue
            name = suggested_name or self._suggest_xmlid(record)
            name = self._unique_xmlid(name)
            Data.create(
                {
                    "module": self.name,
                    "name": name,
                    "model": record._name,
                    "res_id": record.id,
                    "noupdate": False,
                }
            )
            result.append("%s.%s" % (self.name, name))
        return result

    @api.model
    def _suggest_xmlid(self, record):
        """Derive a readable xmlid stem from the record itself.

        Model, field and selection xmlids deliberately reuse Odoo's *own*
        reflection helpers rather than a convention of our own. That is what
        makes "graduate to code" safe: when a manual model becomes a Python
        class, `_reflect_models` / `_reflect_fields` / `_reflect_selections`
        re-register the very same xmlids, so they appear in
        ``pool.loaded_xmlids`` and `_process_end` does not treat the records as
        stale and delete them.
        """
        prefix = record._name.replace(".", "_")
        if record._name == "ir.model":
            return model_xmlid("", record.model).lstrip(".")
        if record._name == "ir.model.fields":
            return field_xmlid("", record.model_id.model, record.name).lstrip(".")
        if record._name == "ir.model.fields.selection":
            return selection_xmlid(
                "",
                record.field_id.model_id.model,
                record.field_id.name,
                record.value,
            ).lstrip(".")
        if record._name == "ir.ui.view":
            return "view_%s" % (record.name or "").lower().replace(" ", "_").replace(
                ".", "_"
            )
        if record._name == "ir.model.access":
            return "access_%s" % (record.name or "").lower().replace(".", "_").replace(
                " ", "_"
            )
        label = getattr(record, "name", False) or record.display_name or str(record.id)
        slug = str(label).lower().replace(" ", "_").replace(".", "_")
        return "%s_%s" % (prefix, slug)

    def _unique_xmlid(self, name):
        self.ensure_one()
        Data = self.env["ir.model.data"]
        candidate = name
        suffix = 1
        while Data.search_count([("module", "=", self.name), ("name", "=", candidate)]):
            suffix += 1
            candidate = "%s_%d" % (name, suffix)
        return candidate


class StudioPackageFile(models.Model):
    _name = "studio.package.file"
    _description = "Studio Package File"
    _order = "path"

    package_id = fields.Many2one("studio.package", required=True, ondelete="cascade")
    path = fields.Char(required=True, help="Path relative to the package root.")
    generated_checksum = fields.Char(
        readonly=True, help="Hash of the content the builder last wrote."
    )
    disk_checksum = fields.Char(readonly=True, help="Hash of the file on disk.")
    drifted = fields.Boolean(
        compute="_compute_drifted",
        store=True,
        help="Set when the file on disk no longer matches what we generated, "
        "i.e. somebody edited it by hand.",
    )

    @api.depends("generated_checksum", "disk_checksum")
    def _compute_drifted(self):
        for record in self:
            record.drifted = record.disk_checksum != record.generated_checksum

    def _refresh_disk_checksum(self):
        for record in self:
            full = os.path.join(record.package_id.root_path or "", record.path)
            record.disk_checksum = checksum.hash_file(full) or False
