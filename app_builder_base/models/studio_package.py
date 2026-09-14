# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""A studio package: one Odoo addon directory, managed as a record.

The package is the unit that ties the three halves together -- the records in
the database, the files on disk, and the git history. Its job is to keep them
in agreement and to be honest when they are not.
"""

import logging
import os
import shutil
import sys
import tempfile
import time

from odoo import _, api, fields, models
from odoo import models as models_module
from odoo.exceptions import UserError, ValidationError
from odoo.tools import config as tools_config
from odoo.tools import file_path

from odoo.addons.base.models.ir_model import (
    field_xmlid,
    model_xmlid,
    selection_xmlid,
)

from ..tools import (
    checksum,
    gitrepo,
    migrationgen,
    modelspec,
    pogen,
    pycodegen,
    pyparse,
    xml_writer,
)
from ..tools import manifest as manifest_tools

_logger = logging.getLogger(__name__)

# Module names Odoo core treats specially; graph.py hardcodes the first one out
# of the dependency graph entirely, so a package named that would silently
# never load.
RESERVED_NAMES = ("studio_customization",)

# Every menu lands here; see IrUiMenuSerializer._target_file.
MENUS_FILE = "views/menus.xml"

# Where every hand-written addon keeps its app icon, and the file Odoo copies
# it from: the tile the web client already shows for an app that has none.
APP_ICON_FILE = "static/description/icon.png"
DEFAULT_APP_ICON = "web/static/img/default_icon_app.png"

# Teardown order: dependants before their dependencies, so no unlink hits a
# restrict/cascade surprise.
UNLINK_ORDER = (
    "ir.ui.menu",
    "base.automation",
    # Before ir.actions.server: ir.cron delegates to it with ondelete='restrict'
    # (ir_cron.py:68), so dropping the action first fails on the foreign key.
    "ir.cron",
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


# -- the dev-mode file watcher --------------------------------------------
#
# `--dev=reload` restarts the server on any .py change under an addons path,
# and gives the requests in flight one second before it closes the database
# connections (`ThreadedServer.stop`). The studio writes .py files and then
# reloads them itself, in process, inside the same request -- so the restart
# the watcher would start is both needless and fatal: the upgrade dies half
# way with a closed cursor, and the rollback that follows dies the same way.
# So the watcher is told to look away from a package the studio is writing,
# for a few seconds around the write. A developer's own edit under the same
# directory, outside that window, restarts the server exactly as before.

_WATCHER_MUTED_UNTIL = {}  # realpath of a package root -> monotonic deadline
_WATCHER_MUTE_SECONDS = 5.0


def _mute_dev_watcher(root, seconds=_WATCHER_MUTE_SECONDS):
    """Keep the autoreload watcher from restarting on writes under ``root``.

    A no-op outside ``--dev=reload``: there is no watcher to mute. Called
    before a write and again after it, so a slow write cannot outrun its
    own window; the events the watcher delivers a moment after the last
    write still fall inside it.
    """
    if not root or "reload" not in (tools_config["dev_mode"] or []):
        return
    _install_watcher_mute()
    _WATCHER_MUTED_UNTIL[os.path.realpath(root)] = time.monotonic() + seconds


def _install_watcher_mute():
    """Wrap ``FSWatcherBase.handle_file`` once, for the life of the process.

    Both of core's watchers -- watchdog and inotify -- funnel every event
    through that one method, and it is the method that decides to restart.
    Wrapping it is the smallest intervention that covers both, and the
    wrapper only ever declines: a path nobody muted is handled by core.
    """
    from odoo.service import server as odoo_server

    base = getattr(odoo_server, "FSWatcherBase", None)
    if base is None or getattr(base, "_studio_muted", False):
        return
    original = base.handle_file

    def handle_file(self, path):
        real = os.path.realpath(path)
        now = time.monotonic()
        for muted_root, until in list(_WATCHER_MUTED_UNTIL.items()):
            if until < now:
                _WATCHER_MUTED_UNTIL.pop(muted_root, None)
            elif real == muted_root or real.startswith(muted_root + os.sep):
                _logger.debug(
                    "autoreload: %s was written by the studio and is reloaded in "
                    "process; not restarting",
                    path,
                )
                return None
        return original(self, path)

    base.handle_file = handle_file
    base._studio_muted = True


class StudioPackage(models.Model):
    _name = "studio.package"
    _inherit = ["studio.security.mixin"]
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

    model_ids = fields.One2many(
        "studio.package.model",
        "package_id",
        string="Models",
        help="Models this package defines, and where each definition lives.",
    )
    apply_ids = fields.One2many("studio.package.apply", "package_id", readonly=True)
    reload_mode = fields.Selection(
        [
            ("inproc", "In this process"),
            ("manual", "Manual restart required"),
        ],
        compute="_compute_reload_mode",
        help="How this deployment can pick up newly generated Python.",
    )
    python_models = fields.Char(
        compute="_compute_python_models",
        store=False,
        readonly=True,
        help="Models defined as Python classes. Kept as a plain string for "
        "readability; model_ids is the real registry.",
    )

    restart_required = fields.Boolean(
        compute="_compute_restart_required",
        help="Something was written to disk that only a server restart can load.",
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

    @api.depends("root_path")
    def _compute_writable(self):
        for package in self:
            path = package.root_path
            if not path:
                package.writable = False
                continue
            probe = path if os.path.isdir(path) else os.path.dirname(path)
            package.writable = bool(probe) and self._can_write_to(probe)

    @api.model
    def _can_write_to(self, directory):
        """Try it, rather than asking ``os.access``.

        This flag is the whole read-only-production guard, so it has to be
        right for the case it exists for -- and ``os.access`` is not. It
        answers for the *real* uid rather than the effective one, it cannot
        see an ACL or an immutable flag, and **when Odoo runs as root it
        answers True for a directory whose mode says 0500** -- which is how
        most containers run it, and how this project's own CI runs its tests.
        It also calls a regular file a writable directory, which is true only
        in the sense that nothing has tried yet.

        Creating a file and removing it is the only answer that is true by
        construction. It costs an inode briefly, on a model with single-digit
        row counts, read at builder speed rather than in a loop.
        """
        try:
            with tempfile.NamedTemporaryFile(dir=directory, prefix=".studio-probe-"):
                return True
        except OSError:
            # Permission, a read-only mount, a parent that is not a directory,
            # a full disk. Each of them means the same thing here.
            return False

    @api.model
    def _suggested(self):
        """Where something created from the studio should be written.

        The one writable package when there is exactly one, and nothing when
        the choice is real. Guessing between two would put somebody's work in
        the wrong addon, which is only discovered at review time.
        """
        writable = self.search([]).filtered("writable")
        return writable[:1] if len(writable) == 1 else self.browse()

    @api.model
    def _chosen(self, package_id=None):
        """The package a caller has already chosen, else the suggested one.

        The console shows one package in its top bar and records every
        drop into it; a list it opens beside the canvas -- automations,
        access rules -- has to record into the same one, or a rule made
        there lands in whichever package ``_suggested`` names, which with
        two writable packages is none. A choice that is not writable is
        no choice: the suggestion stands in for it, as for a caller that
        made none.
        """
        if package_id:
            package = self.browse(package_id).exists()
            if package and package.writable:
                return package
        return self._suggested()

    def _compute_record_count(self):
        for package in self:
            package.record_count = self.env["ir.model.data"].search_count(
                [("module", "=", package.name)]
            )

    def _compute_restart_required(self):
        Apply = self.env["studio.package.apply"]
        for package in self:
            package.restart_required = bool(
                Apply.search_count(
                    [
                        ("package_id", "=", package.id),
                        ("state", "=", "awaiting_restart"),
                    ]
                )
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

    @api.depends("model_ids.model", "model_ids.source")
    def _compute_python_models(self):
        for package in self:
            package.python_models = ", ".join(sorted(package._python_model_set()))

    def _python_model_set(self):
        """Models this package *declares* in Python, frozen ones included.

        A frozen model is still ours -- we simply must not rewrite its file --
        so it counts here, where the question is "does XML own this?".

        An extension does not, and that is the whole distinction: it adds to a
        model another module declares, so XML still owns that model's metadata
        and a manual field on it still belongs in a data file.
        """
        self.ensure_one()
        return {
            m.model
            for m in self.model_ids
            if m.source in ("python", "frozen") and m.model and not m.extends
        }

    def _python_module_set(self):
        """Models with a Python *file*, which is a different question.

        `models/__init__.py` has to import every file the package renders, and
        an extension renders one. Asking `_python_model_set` instead would leave
        the class unimported and the extension silently inert -- the worst
        failure mode available, because everything still loads.
        """
        self.ensure_one()
        return {
            m.model
            for m in self.model_ids
            if m.source in ("python", "frozen") and m.model
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

        # Python-defined models become source rather than XML metadata.
        python_files = self._render_python()
        self._assert_no_double_definition(files, python_files)
        files.update(python_files)

        # Everything above wrote the source term. This writes the rest.
        files.update(self._render_translations(serializers))

        files["__manifest__.py"] = self._render_manifest(sorted(files), dep_sink)
        files["__init__.py"] = pycodegen.render_package_init(bool(python_files))
        return files

    def _render_translations(self, serializers):
        """``{i18n/<lang>.po: text}`` for every language but the source one.

        Mirrors ``TranslationModuleReader`` (``translate.py:1200-1216``) rather
        than inventing an extraction: ``get_translation_dictionary`` handles the
        whole-value and term-based cases uniformly, because ``get_trans_terms``
        returns ``[value]`` for a plain char and the parsed terms for an html
        body or a view arch. Doing it any other way would produce a PO file
        Odoo's own importer disagrees with, which is the failure mode that is
        invisible until somebody switches language.
        """
        self.ensure_one()
        langs = [
            code
            for code, _name in self.env["res.lang"].get_installed()
            if code != "en_US"
        ]
        if not langs:
            return {}

        rows = {lang: [] for lang in langs}
        for model, entries in self._owned_records().items():
            serializer = serializers._for_model(model)
            if serializer is None:
                continue
            for xmlid, record in entries:
                # Already `module.name` -- _owned_records qualifies it.
                for fname in serializer._translatable_fields(record):
                    field = record._fields.get(fname)
                    if field is None:
                        continue
                    kind = "model_terms" if callable(field.translate) else "model"
                    source = record.with_context(lang="en_US")[fname] or ""
                    if not source:
                        continue
                    translated = {
                        lang: record.with_context(lang=lang)[fname] or ""
                        for lang in langs
                    }
                    try:
                        dictionary = field.get_translation_dictionary(
                            source, translated
                        )
                    except Exception:  # noqa: BLE001 - see below
                        # Term extraction parses html, and a body a user
                        # pasted in can be malformed in ways lxml objects to.
                        # Losing one field's translations is bad; failing the
                        # whole save is worse.
                        _logger.warning(
                            "Could not extract translatable terms from %s.%s of %s",
                            model,
                            fname,
                            xmlid,
                        )
                        continue
                    occurrence = pogen.Occurrence(kind, model, fname, xmlid)
                    for term, per_lang in dictionary.items():
                        for lang in langs:
                            rows[lang].append(
                                (term, per_lang.get(lang) or "", occurrence)
                            )

        files = {}
        for lang in langs:
            relative = "i18n/%s.po" % lang
            content = pogen.merge_po(
                self._read_source(relative),
                self.name,
                lang,
                pogen.merge_terms(rows[lang]),
            )
            if content:
                files[relative] = content
        return files

    def _render_python(self):
        """Render ``models/*.py`` for every model this package defines in Python.

        Regenerated on every write, not written once. That inverts the old
        one-way handoff, and it is only safe because the file is the *input*:
        ``_current_spec`` parses it back, so rendering reproduces whatever is
        there, including anything a developer added by hand. What the parser
        cannot read at all freezes the model instead of being overwritten.

        Returns an empty dict when the package has no Python models, which
        keeps a purely data-driven addon exactly as it was.
        """
        self.ensure_one()
        owned = self.model_ids.filtered(lambda m: m.source in ("python", "frozen"))
        if not owned:
            return {}

        files = {}
        emitted = []
        for entry in owned.sorted(lambda m: m.model):
            relative = entry.python_path
            existing = self._read_source(relative)
            spec = entry._current_spec()  # may freeze the row as a side effect

            if spec is not None and existing is not None:
                # Splice the block back in and leave every other byte alone.
                rewritten = pycodegen.splice_block(
                    existing, pycodegen.render_block(spec), spec
                )
                files[relative] = pycodegen.ensure_imports(rewritten, spec)
                emitted.append(entry.model)
                continue

            if existing is not None:
                # Frozen, or a file whose block we could not read: keep it
                # exactly as it is rather than guessing.
                files[relative] = existing
                emitted.append(entry.model)
                continue

            seeded = self._seed_python_from_metadata(entry)
            if seeded is None:
                continue
            files[relative] = seeded
            emitted.append(entry.model)

        if emitted:
            files["models/__init__.py"] = self._render_models_init(emitted)
        return files

    def _assert_no_double_definition(self, data_files, python_files):
        """Refuse to emit a model as both a class and a set of data records.

        ``_ownable`` should already prevent this, but the window where a row is
        still ``state='manual'`` for a Python-backed model -- mid-adoption, or
        after a half-failed apply -- is exactly where it would bite. A silent
        double definition is unrecoverable: ``_add_manual_models`` builds a
        second class competing for the same ``_name``, and ``_process_end``
        then reaps the package's own xmlids. A raised error costs a retry.

        An *extension* is not a double definition and must not be caught here.
        Its class has no ``_name``, so there is nothing for a second class to
        compete with -- and a manual ``x_`` field on the model it extends is
        ordinary metadata that belongs in XML. Adding a method to
        ``res.partner`` and adding a field to it is exactly the combination this
        would otherwise make impossible.
        """
        self.ensure_one()
        for entry in self.model_ids:
            if entry.extends or entry.python_path not in python_files:
                continue
            clash = "models/%s.xml" % entry.model.replace(".", "_")
            if clash in data_files:
                raise UserError(
                    _(
                        "%(model)s would be written both as a Python class and "
                        "as data records (%(path)s). Its metadata rows are "
                        "still marked manual; reload the package to let "
                        "reflection settle them.",
                        model=entry.model,
                        path=clash,
                    )
                )

    def _seed_python_from_metadata(self, entry):
        """First render for a model that has no file yet -- i.e. adoption.

        The only direction in which ``ir.model`` is an input rather than a
        reflection artefact, and it happens exactly once per model.
        """
        self.ensure_one()
        model = self.env["ir.model"].search([("model", "=", entry.model)], limit=1)
        if not model:
            _logger.warning(
                "Package %s claims %s but no such model exists",
                self.name,
                entry.model,
            )
            return None
        # Only fields this package owns: Odoo declares the magic columns
        # itself, and a field from another module is not ours to redeclare.
        owned_fields = model.field_id.filtered(lambda f: f.state == "manual")
        return pycodegen.render_model(pycodegen.spec_from_ir_model(model, owned_fields))

    def _render_bootstrap_files(self):
        """Write the least a directory needs to be an installable module.

        Deliberately empty of content: this is installed before any model
        exists, so that the one slow step -- ``button_immediate_install`` --
        happens on a module with nothing in it that can fail.
        """
        self.ensure_one()
        self._assert_writable()
        files = {
            "__init__.py": pycodegen.render_package_init(False),
            "__manifest__.py": self._render_manifest([]),
        }
        self._write_files(files)
        return files

    def _seed_source_for(self, model_name, spec):
        """Put a model's first Python on disk, before it has ever been loaded.

        The only moment a spec flows *to* the file without having been parsed
        from it. Everything after this is a regeneration of what is there.
        """
        self.ensure_one()
        self._assert_writable()
        relative = "models/%s" % pycodegen.module_file_for(model_name)
        emitted = sorted(self._python_module_set() | {model_name})
        self._write_files(
            {
                relative: pycodegen.render_model(spec),
                "models/__init__.py": self._render_models_init(emitted),
                "__init__.py": pycodegen.render_package_init(True),
            }
        )
        return relative

    def _seed_app_icon(self):
        """Put a real icon file in the package and return its ``web_icon``.

        A seed in the same sense as ``_seed_source_for``: written only when
        absent, never regenerated and never tracked, so a designer's
        replacement survives every later write and prune. What gets copied is
        Odoo's own placeholder tile, so the app looks exactly as it would with
        no icon at all -- until somebody drops a better PNG on the same path.

        The value returned is the two-part ``module,path`` form, the one every
        hand-written app uses. Core also accepts a *built* icon
        (``fa-class,color,background``) and renders it itself, but that form
        carries no image data, and the apps menu OCA's ``web_responsive``
        installs assumes there always is some -- it crashes the whole client
        on the first built-icon app. A file is understood by both.
        """
        self.ensure_one()
        self._assert_writable()
        full = os.path.join(self.root_path, APP_ICON_FILE)
        if not os.path.isfile(full):
            os.makedirs(os.path.dirname(full), exist_ok=True)
            shutil.copyfile(file_path(DEFAULT_APP_ICON), full)
        return "%s,%s" % (self.name, APP_ICON_FILE)

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
        """Union of declared depends and every module we actually need."""
        self.ensure_one()
        declared = {d.strip() for d in (self.depends or "").split(",") if d.strip()}
        referenced = set(dep_sink or ())
        # 'base' is implicit but harmless (and conventional) to state.
        depends = (declared | referenced | self._python_depends() | {"base"}) - {
            self.name
        }
        return sorted(depends)

    def _python_depends(self):
        """Modules our generated *classes* need, which no xmlid ref reveals.

        ``dep_sink`` is filled while serializing records, so it only ever sees
        what XML points at. A class doing ``_inherit = ["mail.thread"]`` needs
        ``mail`` just as much, and nothing in the data files says so -- the
        package installs fine here and fails on a database without mail, which
        is the same class of bug as the one recorded as design finding 4.
        """
        self.ensure_one()
        needed = set()
        IrModel = self.env["ir.model"].sudo()
        for entry in self.model_ids.filtered(lambda m: m.source == "python"):
            spec = entry._current_spec()
            if spec is None:
                continue
            # An extension's own `name` is a model somebody else declares, so
            # it is a dependency exactly as its mixins are -- and missing it
            # means the package installs here and fails on a database without
            # that module, which is design finding 4 all over again.
            inherited_models = spec.inherit + ((spec.name,) if spec.extends else ())
            for inherited in inherited_models:
                record = IrModel.search([("model", "=", inherited)], limit=1)
                if not record:
                    continue
                needed.update(
                    part.strip() for part in (record.modules or "").split(",")
                )
        return {name for name in needed if name and name != self.name}

    @api.model
    def _order_data_files(self, paths):
        """Order manifest 'data' so every ref resolves when the file loads.

        A hand-written addon puts ``security/`` first because its groups are
        needed by everything else. A package with **XML-defined** models cannot:
        everything we emit under ``security/`` -- both the ACL csv and ir.rule --
        carries a ``model_id`` ref to an ``ir.model`` record that ``models/``
        has not defined yet, so loading a rule first fails the install with an
        unresolvable external id.

        A package whose models are all Python does not have that problem, and
        gets the conventional order back. Reflection creates the ``ir.model``
        row and its xmlid during ``init_models``, which runs before ``load_data``
        -- so ``pkg.model_workshop_project`` already resolves by the time the
        csv is read, on the very first install.
        """
        if self._has_xml_models():
            rank = {"models": 0, "data": 1, "security": 2, "views": 3, "report": 4}
        else:
            rank = {"security": 0, "models": 1, "data": 2, "views": 3, "report": 4}

        def key(path):
            head = rank.get(path.split("/")[0], 9)
            if path == MENUS_FILE:
                # Menus ref their action, so they must follow every view file
                # that defines one. Alphabetically "menus.xml" would sort first.
                return (head + 0.5, path)
            return (head, path)

        return sorted((p for p in paths if p.endswith((".xml", ".csv"))), key=key)

    def _has_xml_models(self):
        """Whether any model this package owns is still defined as data.

        A mixed package -- some Python models, some manual ones, or a manual
        field on a core model -- still needs models before security.
        """
        self.ensure_one()
        python_owned = self._python_model_set()
        for _xmlid, record in self._owned_records().get("ir.model", []):
            if record.model not in python_owned:
                return True
        return False

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
        self._assert_studio_manager()
        for package in self:
            package._assert_writable()
            files = package._render_files()
            written = package._write_files(files, prune=True)
            package._sync_file_records(files)
            package._run_auto_commit(written)
            package.state = "synced"
        return True

    def _write_files(self, files, prune=False):
        """Write rendered content; optionally remove generated files that went.

        ``prune`` is off by default and that default is load-bearing. Pruning
        reads *absent from ``files``* as *deleted*, which is only true when
        ``files`` is the whole rendered package. Hand a partial set to a
        pruning write -- one model's ``.py``, say -- and it deletes every other
        file the package generated: the other models, the views, the menus, the
        ACLs. Callers that render everything opt in; callers that render one
        thing cannot make that mistake by forgetting a flag.
        """
        self.ensure_one()
        root = self.root_path
        os.makedirs(root, exist_ok=True)
        _mute_dev_watcher(root)
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
        # Again, after: the window is measured from the last write, not the
        # first, and the watcher hears about a file a moment after it lands.
        _mute_dev_watcher(root)

        if not prune:
            return written

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

    def studio_capture(self, records, write_files=True):
        """Take ownership of ``records`` and flush the package to disk.

        This is the single entry point every builder module calls after it
        changes something. Assigning the xmlid and writing the file happen in
        the caller's transaction, so the database and the source tree either
        both advance or both roll back -- which is what lets us treat the DB
        write as an optimisation rather than a second source of truth.

        ``write_files=False`` takes ownership without touching the disk, and
        leaves the package marked as having a write pending. It is for a
        caller that captures several things in one gesture -- a field, then
        the view it lands in -- and wants the directory written once, last:
        a file written for the first step and then a failure in the second
        would leave source on disk for a change the transaction rolled back.
        The caller owes the package an ``action_write_files()``.
        """
        self._assert_studio_manager()
        self.ensure_one()
        if not any(True for _rec in self._flatten(records)):
            return False
        self._assign(records)
        if write_files and self.writable:
            self.action_write_files()
        else:
            self.state = "dirty"
        return True

    # -- graduate to code -------------------------------------------------

    def action_adopt(self, model_names):
        """Bring an existing ``x_`` manual model under Python management.

        Not a milestone, and not a handoff. New models are Python from the
        first save; this is the migration path for what came before -- a
        package built by an older version of the studio, or a model somebody
        made by hand in Settings -> Technical.

        Afterwards the model is exactly like any other the builder owns: the
        marked block inside its class stays in sync, and everything outside it
        is the developer's. Adopting does not close any door.

        The new class takes effect once the package reloads, which
        ``--dev=reload`` does for you.
        """
        self._assert_studio_manager()
        self.ensure_one()
        self._assert_writable()
        requested = {m.strip() for m in model_names if m and m.strip()}
        if not requested:
            raise UserError(_("Choose at least one model to adopt."))

        unknown = requested - self._owned_model_names()
        if unknown:
            raise UserError(
                _(
                    "This package does not own %(models)s, so it cannot adopt them.",
                    models=", ".join(sorted(unknown)),
                )
            )
        self._assert_module_installed()

        # Strict order. The metadata is the *input* to code generation and is
        # retired by it, so the Python must be on disk before the demotion; and
        # the XML must be rendered after it, so that _ownable (which excludes
        # state='base') naturally stops emitting what the class now defines.
        self._write_adopted_source(requested)
        for model_name in sorted(requested):
            self.env["studio.package.model"]._adopt(self, model_name, source="python")
        self._demote_manual_metadata(requested)
        self.action_write_files()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Adopted"),
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
        """Refuse to adopt into a package Odoo has not installed as a module.

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
                    "Odoo only loads Python for installed modules, so adopting "
                    "now would leave %(name)s with no definition at all after a "
                    "restart.",
                    name=self.name,
                )
            )

    def _write_adopted_source(self, model_names):
        """Emit the Python for ``model_names`` from their live metadata.

        Written directly rather than through ``action_write_files`` because
        this has to happen while the metadata still exists, and before the
        pruning pass that removes the XML it replaces.
        """
        self.ensure_one()
        env = self._source_env()
        root = self.root_path
        os.makedirs(os.path.join(root, "models"), exist_ok=True)
        emitted = sorted(self._python_module_set() | set(model_names))

        for model_name in sorted(model_names):
            relative = "models/%s" % pycodegen.module_file_for(model_name)
            if self._read_source(relative) is not None:
                # Adoption seeds a file that does not exist yet. If one is
                # already there the model is adopted, and from then on that
                # file is the definition -- _render_python regenerates it from
                # its own parsed contents rather than from this metadata, which
                # by now has been demoted to state='base' anyway.
                continue
            model = env["ir.model"].search([("model", "=", model_name)], limit=1)
            if not model:
                continue
            owned = model.field_id.filtered(lambda f: f.state == "manual")
            with open(os.path.join(root, relative), "w", encoding="utf-8") as handle:
                handle.write(
                    pycodegen.render_model(pycodegen.spec_from_ir_model(model, owned))
                )

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
            "Adopted %s in package %s: metadata reclassified as base; "
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

        That flag is also why the reflection guard below is not optional. Once
        a package defines models in Python, reflection writes an
        ``ir.model.data`` row for *every* field it declares -- the magic
        columns, and everything ``mail.thread`` brings with it. Feeding those to
        ``unlink`` with ``_force_unlink`` set would run ``_drop_column`` over
        columns this package never created and take their data with it.
        """
        self._assert_studio_manager()
        self.ensure_one()
        data = self._deletable_data()
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

    def _deletable_data(self):
        """The package's ``ir.model.data`` rows minus reflection artefacts.

        A row is ours to delete only if the record behind it is one the
        serializers would have emitted. Anything reflected from a Python class
        -- ``state='base'`` metadata, mixin fields, magic columns -- carries our
        module name purely because our class declared it, and deleting it is
        Odoo's job during uninstall, not ours.
        """
        self.ensure_one()
        data = self.env["ir.model.data"].search([("module", "=", self.name)])
        serializers = self._serializer_env()
        keep = []
        for entry in data:
            if entry.model not in self.env:
                continue
            record = self.env[entry.model].browse(entry.res_id)
            if not record.exists():
                keep.append(entry)  # a dangling row: dropping it is harmless
                continue
            serializer = serializers._for_model(entry.model)
            if serializer is not None and not serializer._ownable(record):
                continue
            keep.append(entry)
        return self.env["ir.model.data"].browse([e.id for e in keep])

    # -- apply -------------------------------------------------------------

    def _compute_reload_mode(self):
        """How this deployment can pick up new Python.

        ``manual`` is the correct answer under multiple workers, not a cop-out.
        ``setup_models`` sets ``registry_invalidated``, so every other worker
        rebuilds its registry -- but their ``sys.modules`` still holds the old
        Python, so they would rebuild against a stale class. An in-process
        re-import across workers is not slow, it is wrong.

        ``--dev=reload`` does not change the answer. It used to select a
        third mode that let the dev server's own restart do the reload, and
        that never worked: the restart the watcher starts on the first .py
        written kills the request that is still writing, and a plain boot
        does not install a module that is only marked for it. The studio
        reloads its own packages in process instead, and mutes the watcher
        for its own writes (``_mute_dev_watcher``).
        """
        workers = tools_config["workers"]
        for package in self:
            package.reload_mode = "inproc" if not workers else "manual"

    def _reimport_module(self):
        """Purge this package's Python so it is imported again.

        Proven necessary in ``tests/e2e/probe_reimport.py``:
        ``load_openerp_module`` early-returns when ``odoo.addons.<name>`` is
        already in ``sys.modules``, so an upgrade without this reports success
        and silently re-runs the data files against the *old* classes.

        ``MetaModel.module_to_models`` is append-only, so skipping it registers
        every class a second time.
        """
        self.ensure_one()
        prefix = "odoo.addons.%s" % self.name
        for name in [
            m for m in sys.modules if m == prefix or m.startswith(prefix + ".")
        ]:
            del sys.modules[name]
        models_module.MetaModel.module_to_models.pop(self.name, None)
        self._invalidate_module_caches()

    def _reload_now(self):
        """Make the running process see the source that is on disk.

        Order is load-bearing and was measured, not reasoned about: purge
        first, so the import happens at all; *then* upgrade, so ``init_models``
        runs and the schema follows. Purging alone leaves the new field in the
        ORM and absent from Postgres, because ``Registry.new`` only runs
        ``init_models`` for modules marked ``to upgrade``.
        """
        self.ensure_one()
        if self.reload_mode == "manual":
            raise UserError(
                _(
                    "This server runs %(workers)s worker processes, so a "
                    "package cannot be reloaded in place: the other workers "
                    "would rebuild their registry against the Python they "
                    "already have in memory. Restart the server to pick this "
                    "change up.",
                    workers=tools_config["workers"],
                )
            )
        self._reimport_module()
        module = self._find_or_create_module()
        if module.state == "installed":
            return module.button_immediate_upgrade()
        return module.button_immediate_install()

    def _assert_sources_compile(self, files):
        """Refuse to write Python that will not import.

        This is the step that keeps a bad apply recoverable. Once a broken
        module file is on disk, the next request re-imports it during
        ``load_modules`` and the database will not boot -- for everybody, not
        just whoever pressed the button.
        """
        for path, content in sorted(files.items()):
            if not path.endswith(".py"):
                continue
            try:
                compile(content, path, "exec")
            except SyntaxError as err:
                raise UserError(
                    _(
                        "Generated %(path)s is not valid Python (%(err)s). "
                        "Nothing was written.",
                        path=path,
                        err=err,
                    )
                ) from err

    def _assert_specs_reparse(self, files):
        """Everything we are about to write must read back as what it says.

        Cheap here, and the alternative is discovering on the next save that a
        file we generated is one the parser refuses -- at which point the model
        freezes and the builder appears to have broken itself.
        """
        self.ensure_one()
        for entry in self.model_ids.filtered(lambda m: m.source == "python"):
            content = files.get(entry.python_path)
            if content is None:
                continue
            try:
                spec = pyparse.parse_model(content)
            except pyparse.UnsupportedConstruct as err:
                raise UserError(
                    _(
                        "Generated %(path)s is not something the builder can "
                        "read back (%(err)s). Nothing was written.",
                        path=entry.python_path,
                        err=err,
                    )
                ) from err
            if pycodegen.render_model(spec) != content:
                raise UserError(
                    _(
                        "Generated %(path)s does not round-trip. Nothing was "
                        "written; please report this.",
                        path=entry.python_path,
                    )
                )

    def _destructive_changes(self, files):
        """Columns this apply would drop, per model.

        The baseline has to be the *database*, not the file. Since the emitter
        now regenerates from disk, comparing the two would find nothing the
        moment a developer edits the file directly -- which is exactly the case
        where a column is about to disappear. What matters is which fields
        currently have a column and are not in the source we are about to
        write, however they came to be missing.

        Only fields this package introduced count. A field another module put
        on the same model is not ours to drop and Odoo will not drop it.
        """
        self.ensure_one()
        dropped = {}
        owned_field_ids = self._owned_field_ids()
        # Extensions excluded: one declares no fields of its own, so its empty
        # field list is not "every column removed" -- it is "this class is not
        # where the columns are declared".
        for entry in self.model_ids.filtered(
            lambda m: m.source == "python" and not m.extends
        ):
            source = files.get(entry.python_path)
            if source is None:
                continue
            try:
                after = pyparse.parse_model(source)
            except pyparse.UnsupportedConstruct:
                continue  # frozen; we are not rewriting it anyway
            model = self.env["ir.model"].search([("model", "=", entry.model)], limit=1)
            if not model:
                continue
            # Everything the class itself did not declare. Reflection attributes
            # a mixin's fields to whichever module introduced the *model*, so
            # message_ids and friends carry our xmlid too -- and reading them as
            # columns we are about to drop would block every ordinary save.
            # Asking the live mixin is exact; a hardcoded list would not be.
            keeping = set(after.field_names) | set(modelspec.MAGIC_COLUMNS)
            for mixin in after.inherit:
                if mixin in self.env:
                    keeping |= set(self.env[mixin]._fields)
            gone = sorted(
                record.name
                for record in model.field_id
                if record.id in owned_field_ids
                and record.store
                and record.name not in keeping
            )
            if gone:
                dropped[entry.model] = tuple(gone)
        return dropped

    def _owned_field_ids(self):
        """ids of ``ir.model.fields`` records carrying this package's xmlid."""
        self.ensure_one()
        entries = self.env["ir.model.data"].search(
            [("module", "=", self.name), ("model", "=", "ir.model.fields")]
        )
        return set(entries.mapped("res_id"))

    def _write_pre_migrations(self, dropped, stamp):
        """Rename each doomed column aside before Odoo can drop it."""
        self.ensure_one()
        files = {}
        for model_name, columns in sorted(dropped.items()):
            table = model_name.replace(".", "_")
            content = migrationgen.render_pre_migration(table, columns, stamp)
            if content:
                files[migrationgen.migration_path(self.version, stamp)] = content
        return files

    def action_apply(
        self, reason="", allow_destructive=False, overlay=None, reload=None
    ):
        """Write the package and make the running process see it.

        The sequence is fixed and none of it is optional -- see the class
        docstring on ``studio.package.apply`` for why a half-finished apply is
        not something the ORM can roll back for us.

        ``overlay`` is content a caller has for files the render would
        otherwise produce from disk -- a draft's rewritten ``.py`` -- and
        it goes through this sequence *instead of* being written first:
        the snapshot at step 3 has to record the bytes the file had before
        the change, or a rollback puts the change back.

        ``reload=False`` -- and any apply on a server that cannot reload
        in place -- stops after step 5. The files are on disk and
        committed, the apply is ``awaiting_restart``, and the restart the
        user is told about is what makes the change live. Nothing is
        restored, because nothing was loaded and nothing could have gone
        wrong yet.
        """
        self._assert_studio_manager()
        self.ensure_one()
        self._assert_writable()

        files = self._render_files()  # 1. render to memory
        files.update(overlay or {})
        self._assert_sources_compile(files)  # 2. validate before touching disk
        self._assert_specs_reparse(files)

        stamp = fields.Datetime.now().strftime("%Y%m%d%H%M%S")

        dropped = self._destructive_changes(files)
        if dropped and not allow_destructive:
            raise UserError(
                _(
                    "This change removes stored field(s) and would drop their "
                    "data:\n\n%(detail)s\n\nApply it again with the "
                    "destructive option to keep the data under a renamed "
                    "column instead.",
                    detail="\n".join(
                        "  %s: %s" % (model, ", ".join(cols))
                        for model, cols in sorted(dropped.items())
                    ),
                )
            )
        if dropped:
            # Ordering is what makes this work: migrate_module(pkg, 'pre') runs
            # long before _process_end, so by the time _drop_column looks the
            # column is already gone under its old name and it drops nothing.
            files.update(self._write_pre_migrations(dropped, stamp))
        apply = self.env["studio.package.apply"]._snapshot(  # 3. keep the old bytes
            self, files, reason=reason, stamp=stamp
        )
        if self.is_git:
            gitrepo.commit(self.root_path, "studio: before %s" % (reason or "apply"))

        written = self._write_files(files, prune=True)  # 4. write
        self._sync_file_records(files)
        self._run_auto_commit(written)
        self.env.cr.commit()  # 5. commit BEFORE the reload

        if reload is False or self.reload_mode == "manual":
            apply.state = "awaiting_restart"
            self.state = "synced"
            return apply

        try:
            self._reload_now()  # 6. reimport, then upgrade
        except Exception as err:  # 7. restore and go back to a good registry
            _logger.exception("Apply failed for package %s", self.name)
            apply._restore()
            self.env.cr.commit()
            try:
                self._reload_now()
            except Exception:  # pragma: no cover - already in trouble
                _logger.exception(
                    "Could not reload %s after a failed apply; the package on "
                    "disk has been restored but this process may be stale",
                    self.name,
                )
            apply.write({"state": "failed", "error": str(err)})
            raise UserError(
                _(
                    "This change could not be applied and has been rolled "
                    "back:\n\n%(err)s",
                    err=err,
                )
            ) from err

        apply.state = "applied"
        self.state = "synced"
        return apply

    # -- drift ------------------------------------------------------------

    def action_check_drift(self):
        """Compare disk against what we last generated."""
        self._assert_studio_user()
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
        self._assert_studio_user()
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
        self._assert_studio_manager()
        self.ensure_one()
        if self.reload_mode == "manual":
            # The same reason `_reload_now` refuses: the other workers would
            # rebuild their registry against the Python already in memory.
            raise UserError(
                _(
                    "This server runs %(workers)s worker processes, so a "
                    "package cannot be reloaded in place. Restart the server "
                    "to read the package from disk.",
                    workers=tools_config["workers"],
                )
            )
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
        # A serializer may name its own records. Consulted first so per-model
        # knowledge lives with the serializer rather than accumulating here;
        # the branches below stay because they reuse Odoo's *own* reflection
        # helpers, which is what makes graduation safe.
        serializer = self._serializer_env()._for_model(record._name)
        if serializer is not None:
            suggested = serializer._suggest_xmlid(record)
            if suggested:
                return suggested
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
