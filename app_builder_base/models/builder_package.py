# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""A builder package: one Odoo addon directory, managed as a record.

The package is the unit that ties the three halves together -- the records in
the database, the files on disk, and the git history. Its job is to keep them
in agreement and to be honest when they are not.
"""

from __future__ import annotations

import contextlib
import functools
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
from typing import TYPE_CHECKING, Any, cast

import psycopg2

from odoo import api, fields, models
from odoo import models as models_module  # pylint: disable=reimported
from odoo.exceptions import UserError, ValidationError
from odoo.modules.registry import Registry
from odoo.tools import config as tools_config
from odoo.tools import file_path, mute_logger, sql
from odoo.tools.parse_version import parse_version

from odoo.addons.base.models import ir_model as ir_model_module
from odoo.addons.base.models.ir_model import IrModel, IrModelData
from odoo.addons.base.models.ir_module import Module as IrModuleModule
from odoo.addons.base.models.res_lang import Lang

from ..tools import (
    atomicfile,
    checksum,
    gitrepo,
    migrationgen,
    modelspec,
    pogen,
    pycodegen,
    pyparse,
    typed,
    xml_writer,
)
from ..tools import manifest as manifest_tools
from ..tools.i18n import _
from .builder_serializer import BuilderSerializer

if TYPE_CHECKING:
    # Only for annotations/casts below; with `from __future__ import
    # annotations` nothing here needs these at runtime, the same bargain
    # every other Phase 1c file's `TYPE_CHECKING` block makes.
    from collections.abc import Generator, Iterable, Iterator

    from odoo.fields import _String
    from odoo.models import BaseModel
    from odoo.sql_db import Cursor

    from odoo.addons.base.models.ir_model import (
        IrModelAccess,
        IrModelFields,
        IrModelSelection,
    )
    from odoo.addons.base.models.ir_ui_view import View

    from ..tools.lxml_types import LxmlElement
    from ..tools.manifest import Manifest, ManifestValue
    from ..tools.modelspec import ModelSpec

    # `builder_package.py` <-> `builder_package_apply.py`/`builder_package_model
    # .py`: two real circular references (TYPING.md's own dependency map),
    # aggregate-root/child FK pairs, this file converted first. Both imports
    # stay `TYPE_CHECKING`-only -- never a real, top-level import -- so that
    # when those two files are converted next and need `BuilderPackage` back
    # (for their own `package_id` typed-relation field), the cycle does not
    # become a real one. That also means neither class can be passed as
    # `typed.model()`'s own `cls` argument here (that helper reads `cls
    # ._name` at *runtime*, which needs a real binding): every
    # `self.env["builder.package.apply"]`/`self.env["builder.package.model"]`
    # below stays exactly as it was, and is `cast()` to the class instead --
    # a deliberate, reasoned departure from typed.model() for these two
    # names only, not an oversight (see this file's own PR notes).
    #
    # Relative, not the fully-qualified `odoo.addons.app_builder_base....`
    # form: this repo is reachable under *two* different pyright module
    # identities at once (`app_builder_base.*`, via pyrightconfig.json's own
    # `include`; and `odoo.addons.app_builder_base.*`, via `extraPaths`' merged
    # tree, which mirrors this same repo) -- confirmed the hard way, this
    # file's own first draft imported these two absolutely and every call
    # into a `tools/` function taking a `ModelSpec` (`pycodegen.render_block`
    # et al., all reached from *this* file via a relative `..tools` import)
    # then failed with two `ModelSpec`s that print identically but come from
    # different resolved module paths. Relative imports keep this file and
    # everything it reaches within the same `app_builder_base.*` identity as
    # the `tools/` modules it calls into.
    from .builder_package_apply import BuilderPackageApply
    from .builder_package_model import BuilderPackageModel
    from .builder_security import BuilderSecurityMixin
    from .serializers.ir_security import IrModelAccessSerializer

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

# What a generated manifest may declare: exactly the values core's own
# `ir.module.module.license` accepts, so a typo cannot reach a manifest and
# come back as a warning on every boot.
LICENSES = [
    ("LGPL-3", "LGPL Version 3"),
    ("OPL-1", "Odoo Proprietary License v1.0"),
    ("OEEL-1", "Odoo Enterprise Edition License v1.0"),
    ("AGPL-3", "Affero GPL-3"),
    ("GPL-3", "GPL Version 3"),
    ("GPL-3 or any later version", "GPL-3 or later version"),
    ("GPL-2", "GPL Version 2"),
    ("GPL-2 or any later version", "GPL-2 or later version"),
    ("Other OSI approved licence", "Other OSI Approved License"),
    ("Other proprietary", "Other Proprietary"),
]
# The default for a package nobody chose a licence for. A generated package
# is its author's own work, not a derivative of the (AGPL) builder that
# typed it out, and LGPL-3 is what Odoo's own scaffold and community addons
# default to -- it does not put a network-copyleft label on somebody's
# private customisation without their asking.
DEFAULT_LICENSE = "LGPL-3"

# Everything the builder keeps for itself inside a package directory.
BUILDER_DIR = ".builder"
# Which database last wrote this directory. See `_claim_directory`.
OWNER_FILE = ".builder/owner"

# First key of the two-key advisory lock taken around a package write; the
# second is the package id. Arbitrary, fixed, and ours ("buil").
ADVISORY_LOCK_NAMESPACE = 0x6275696C

# How long an apply waits for a running scheduled action before giving up.
# Core's module operations take `ir_cron ... FOR UPDATE NOWAIT` and fail
# outright while a cron runs; most crons finish within seconds.
CRON_LOCK_ATTEMPTS = 10
CRON_LOCK_DELAY = 1.0

# (database, package id) -> ident of the thread applying it. An apply
# commits half way and then reloads, so no database lock can span it; within
# one process this does. Across processes the advisory lock covers the part
# before the commit, which under workers is the whole apply.
_APPLYING: dict[tuple[str, int], int] = {}
_APPLYING_GUARD = threading.Lock()


def _registries() -> Any:
    """``Registry.registries``: the process's database-name -> registry LRU.

    Read through ``vars`` because the class attribute carries no annotation
    of its own -- untyped vendor plumbing, the same boundary
    ``_install_watcher_mute`` meets with ``FSWatcherBase``.
    """
    return vars(Registry)["registries"]


def _adapt_version(version: str) -> str:
    """Core's own ``adapt_version`` (``18.0.`` prefixed, validated)."""
    from odoo.modules import module as module_tools

    adapt: Any = vars(module_tools)["adapt_version"]
    return cast("str", adapt(version))


def _strict_root_path() -> bool:
    """Whether a package must sit directly under an ``addons_path`` entry.

    Always, except while a test runs: the suite builds its packages in
    throwaway temporary directories, which is the one honest reason for a
    package to live somewhere Odoo could never load it from. The checks that
    keep a package out of core's own directories apply either way.
    """
    return not getattr(threading.current_thread(), "testing", False)


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
# connections (`ThreadedServer.stop`). The builder writes .py files and then
# reloads them itself, in process, inside the same request -- so the restart
# the watcher would start is both needless and fatal: the upgrade dies half
# way with a closed cursor, and the rollback that follows dies the same way.
# So the watcher is told to look away from a package the builder is writing,
# for a few seconds around the write. A developer's own edit under the same
# directory, outside that window, restarts the server exactly as before.

# realpath of a package root -> monotonic deadline
_WATCHER_MUTED_UNTIL: dict[str, float] = {}
_WATCHER_MUTE_SECONDS = 5.0


def _mute_dev_watcher(root: str, seconds: float = _WATCHER_MUTE_SECONDS) -> None:
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


def _install_watcher_mute() -> None:
    """Wrap ``FSWatcherBase.handle_file`` once, for the life of the process.

    Both of core's watchers -- watchdog and inotify -- funnel every event
    through that one method, and it is the method that decides to restart.
    Wrapping it is the smallest intervention that covers both, and the
    wrapper only ever declines: a path nobody muted is handled by core.
    """
    from odoo.service import server as odoo_server

    # `FSWatcherBase` is only ever present when a dev-mode watcher is
    # actually running (`getattr` with a default rather than a plain
    # attribute access), and what it and its own `handle_file` really are is
    # vendor, dev-only plumbing this module patches rather than depends on
    # the shape of -- `Any` is the honest type at this boundary, the same
    # spirit as the codebase's other traced-vendor-gap `Any` uses.
    base: Any = getattr(odoo_server, "FSWatcherBase", None)
    if base is None or getattr(base, "_builder_muted", False):
        return
    original = base.handle_file

    def handle_file(self: Any, path: str) -> None:
        real = os.path.realpath(path)
        now = time.monotonic()
        for muted_root, until in list(_WATCHER_MUTED_UNTIL.items()):
            if until < now:
                _WATCHER_MUTED_UNTIL.pop(muted_root, None)
            elif real == muted_root or real.startswith(muted_root + os.sep):
                _logger.debug(
                    "autoreload: %s was written by the builder and is reloaded in "
                    "process; not restarting",
                    path,
                )
                return None
        return original(self, path)

    base.handle_file = handle_file
    base._builder_muted = True


class BuilderPackage(models.Model):
    _name = "builder.package"
    _inherit = ["builder.security.mixin"]
    _description = "Builder Package"
    _order = "name"

    name = fields.Char(
        required=True,
        help="Technical module name. Becomes the directory name and the "
        "xmlid prefix for everything the package owns.",
    )
    display_name_ = fields.Char(
        string="Title", required=True, default="Builder Package"
    )
    summary = fields.Char()
    version = fields.Char(default="18.0.1.0.0", required=True)
    category = fields.Char(default="Customization")
    author = fields.Char(default="App Builder")
    license = fields.Selection(
        LICENSES,  # pyright: ignore[reportArgumentType] -- see `state`'s own comment below.
        default=DEFAULT_LICENSE,
        help="The licence written to the package's manifest. What you build "
        "is yours: it is not a derivative of the builder, and you may pick "
        "any licence compatible with the modules it depends on (a package "
        "extending Odoo Enterprise models normally uses OPL-1 or OEEL-1).",
    )
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
    # `Selection.__init__`'s own `selection` parameter (`odoo/fields.py`)
    # carries no annotation of its own, only a `SENTINEL` default -- pyright
    # infers its type from that default alone (`Sentinel`), rejecting the
    # real `list[(value, label)]` form the field's own docstring says is the
    # normal case. A real, traced vendor-stub gap, not fixable from this
    # side; narrow ignore at each literal-list call, same idiom as every
    # other traced vendor gap in this migration.
    state = fields.Selection(STATES, default="draft", readonly=True)  # pyright: ignore[reportArgumentType]

    # `file_ids`/`model_ids`/`apply_ids` carry an explicit `One2many[Cls]`
    # annotation only to keep the *declaration* itself from being a
    # partially-unknown name: `_Relational.__get__` (`odoo/fields.py`)
    # carries no return annotation of its own, and its two-branch body
    # (`super().__get__(...)` vs `self.mapped(records)`) still infers a
    # messy, partially-`Unknown` union on every *read*. Every real read of
    # one of these three fields below therefore still goes through the same
    # `cast()`-at-the-read-site idiom `pycodegen.py`'s own
    # `record.selection_ids`/this file's own `model.field_id` already use.
    file_ids: fields.One2many[BuilderPackageFile] = fields.One2many(
        "builder.package.file", "package_id", readonly=True
    )
    record_count = fields.Integer(compute="_compute_record_count")

    model_ids: fields.One2many[BuilderPackageModel] = fields.One2many(
        "builder.package.model",
        "package_id",
        string="Models",
        help="Models this package defines, and where each definition lives.",
    )
    apply_ids: fields.One2many[BuilderPackageApply] = fields.One2many(
        "builder.package.apply", "package_id", readonly=True
    )
    reload_mode = fields.Selection(
        [  # pyright: ignore[reportArgumentType] -- see `state`'s own comment above.
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
        [("off", "Off"), ("stage", "Stage only"), ("commit", "Commit each change")],  # pyright: ignore[reportArgumentType] -- see `state`'s own comment above.
        default="stage",
        required=True,
        help="What to do with git after each write.",
    )

    _sql_constraints = [
        (
            "name_uniq",
            "unique(name)",
            "A builder package with this name already exists.",
        ),
    ]

    # -- constraints ------------------------------------------------------

    @api.constrains("name")
    def _check_name(self) -> None:
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

    @api.constrains("root_path", "name")
    def _check_root_path(self) -> None:
        """Keep a package where a package may live, whoever sets the path.

        ``builder.workspace.create_package`` checks all of this with a
        sentence each, but it is one RPC: ``root_path`` is an ordinary
        stored field, and a plain ``write`` -- from the backend form, an
        import, another module -- reaches it without going near that
        method. Everything the builder then does (write files, prune files,
        run git, ``rmtree`` a backup) happens under this path, so the
        invariant has to live with the field.
        """
        import odoo

        import odoo.addons

        # realpath, not abspath: the checkout Odoo runs from is often a
        # symlink (a nix store path behind `.odoo-nix/odoo`), and every path
        # below is compared resolved.
        core_root = os.path.dirname(os.path.dirname(os.path.realpath(odoo.__file__)))
        addons_dirs = {os.path.realpath(path) for path in odoo.addons.__path__}
        strict = _strict_root_path()
        for package in self:
            path = package.root_path
            if not path:
                continue
            if not os.path.isabs(path) or os.path.normpath(path) != path:
                raise ValidationError(
                    _(
                        "'%s' is not an absolute, normalised path; a package "
                        "directory has to be one.",
                        path,
                    )
                )
            real = os.path.realpath(path)
            parent = os.path.dirname(real)
            if real == core_root or real.startswith(core_root + os.sep):
                raise ValidationError(
                    _(
                        "%s belongs to Odoo itself; a package cannot live there.",
                        path,
                    )
                )
            if any(
                entry == real or entry.startswith(real.rstrip(os.sep) + os.sep)
                for entry in addons_dirs | {core_root}
            ):
                raise ValidationError(
                    _(
                        "%s is an addons directory (or contains one), not a "
                        "single addon; a package cannot take it over.",
                        path,
                    )
                )
            if not strict:
                continue
            if parent not in addons_dirs:
                raise ValidationError(
                    _(
                        "%s is not directly inside a directory on the addons "
                        "path. Odoo only loads addons from directories that "
                        "were on the path when the server started.",
                        path,
                    )
                )
            if os.path.basename(real) != package.name:
                raise ValidationError(
                    _(
                        "The package directory has to be named after the "
                        "package: expected '%(name)s', got '%(got)s'.",
                        name=package.name,
                        got=os.path.basename(real),
                    )
                )

    # -- computes ---------------------------------------------------------

    @api.depends("name")
    def _compute_root_path(self) -> None:
        base = typed.model(self.env, BuilderPackage)._default_addons_dir()
        for package in self:
            if not package.root_path and package.name and base:
                package.root_path = os.path.join(os.path.realpath(base), package.name)
            elif not package.root_path:
                # No writable addons directory: nowhere to put it, which is
                # the read-only deployment. A bare relative name here would
                # resolve against the server's working directory.
                package.root_path = False

    @api.depends("root_path")
    def _compute_writable(self) -> None:
        for package in self:
            path = package.root_path
            if not path:
                package.writable = False
                continue
            probe = path if os.path.isdir(path) else os.path.dirname(path)
            package.writable = bool(probe) and self._can_write_to(probe)

    @api.model
    def _can_write_to(self, directory: str) -> bool:
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
            with tempfile.NamedTemporaryFile(dir=directory, prefix=".builder-probe-"):
                return True
        except OSError:
            # Permission, a read-only mount, a parent that is not a directory,
            # a full disk. Each of them means the same thing here.
            return False

    @api.model
    def _suggested(self) -> BuilderPackage:
        """Where something created from the builder should be written.

        The one writable package when there is exactly one, and nothing when
        the choice is real. Guessing between two would put somebody's work in
        the wrong addon, which is only discovered at review time.
        """
        writable = self.search([]).filtered("writable")
        return writable[:1] if len(writable) == 1 else self.browse()

    @api.model
    def _chosen(self, package_id: int | None = None) -> BuilderPackage:
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

    def _compute_record_count(self) -> None:
        for package in self:
            package.record_count = typed.model(self.env, IrModelData).search_count(
                [("module", "=", package.name)]
            )

    def _compute_restart_required(self) -> None:
        Apply = cast("BuilderPackageApply", self.env["builder.package.apply"])
        for package in self:
            package.restart_required = bool(
                Apply.search_count(
                    [
                        ("package_id", "=", package.id),
                        ("state", "=", "awaiting_restart"),
                    ]
                )
            )

    def _compute_git_info(self) -> None:
        for package in self:
            path = package.root_path
            package.is_git = bool(path) and gitrepo.is_repo(path)
            package.git_branch = (
                gitrepo.current_branch(cast("str", path)) if package.is_git else False
            )

    # -- addons path ------------------------------------------------------

    @api.model
    def _default_addons_dir(self) -> str:
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

    def _serializer_env(self, dep_sink: set[str] | None = None) -> BuilderSerializer:
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
        return typed.model(self.env, BuilderSerializer).with_context(
            builder_package=self.name,
            builder_dep_sink=dep_sink,
            lang=None,
        )

    def _source_env(self) -> api.Environment:
        """Env for reading records during serialization: source language only."""
        self.ensure_one()
        return self.env(
            context=dict(cast("dict[str, Any]", self.env.context), lang=None)
        )

    def _owned_records(self) -> dict[str, list[tuple[str, BaseModel]]]:
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
        data = typed.model(env, IrModelData).search([("module", "=", self.name)])
        serializers = self._serializer_env()
        grouped: dict[str, list[tuple[str, BaseModel]]] = {}
        for entry in data:
            # `model` is a required Char (`ir.model.data`, core) -- the same
            # "declared str | False, never actually False" cast as this
            # file's other required-field reads. Cast once, reused for the
            # three dynamic uses below (`env[...]`, `_for_model`, the dict
            # key), rather than three separate casts.
            entry_model = cast("str", entry.model)
            if entry_model not in env:
                continue
            record = env[entry_model].browse(entry.res_id)
            if not record.exists():
                continue
            serializer = serializers._for_model(entry_model)
            if serializer is not None and not serializer._ownable(record):
                continue
            grouped.setdefault(entry_model, []).append(
                ("%s.%s" % (entry.module, entry.name), record)
            )
        return grouped

    @api.depends("model_ids.model", "model_ids.source")
    def _compute_python_models(self) -> None:
        for package in self:
            package.python_models = ", ".join(sorted(package._python_model_set()))

    def _python_model_set(self) -> set[str]:
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
            for m in cast("BuilderPackageModel", self.model_ids)
            if m.source in ("python", "frozen") and m.model and not m.extends
        }

    def _python_module_set(self) -> set[str]:
        """Models with a Python *file*, which is a different question.

        `models/__init__.py` has to import every file the package renders, and
        an extension renders one. Asking `_python_model_set` instead would leave
        the class unimported and the extension silently inert -- the worst
        failure mode available, because everything still loads.
        """
        self.ensure_one()
        return {
            m.model
            for m in cast("BuilderPackageModel", self.model_ids)
            if m.source in ("python", "frozen") and m.model
        }

    def _owned_model_names(self) -> set[str]:
        """Custom models this package owns, graduated or not.

        Read straight from ir.model.data rather than from ``_owned_records``,
        because the latter deliberately hides already-graduated metadata.
        """
        self.ensure_one()
        entries = typed.model(self.env, IrModelData).search(
            [("module", "=", self.name), ("model", "=", "ir.model")]
        )
        records = (
            typed.model(self.env, IrModel)
            .browse(cast("list[int]", entries.mapped("res_id")))
            .exists()
        )
        return set(cast("list[str]", records.mapped("model")))

    # NB: there is deliberately no "is this model graduated?" filter here.
    # Graduation demotes the metadata to state='base', and `_ownable` already
    # excludes that -- so the XML stops being emitted as a consequence of the
    # data, not of a flag. Filtering on the flag instead was an active bug: a
    # field added to an already-graduated model is manual, belongs in XML
    # (exactly as Studio adds fields to core models), and was being written to
    # no file at all.

    def _render_files(self) -> dict[str, str]:
        """Render every generated file. Returns ``{relative_path: content}``."""
        self.ensure_one()
        # Modules our refs point at; becomes the manifest 'depends'.
        dep_sink: set[str] = set()
        serializers = self._serializer_env(dep_sink)
        # (file, sort_key) -> node, accumulated then ordered in one pass so the
        # result never depends on database iteration order.
        # `serializer._sort_key(...)`'s own return type widened from
        # `tuple[int, str]` to `tuple[int | str | bool, ...]` once wave 1's
        # own real overrides showed the narrower shape was wrong (see
        # `builder_serializer.py`'s own `_sort_key` docstring) -- these two
        # local element types follow it.
        buckets: dict[
            str, list[tuple[tuple[int | str | bool, ...], LxmlElement, bool]]
        ] = {}
        csv_rows: dict[
            str, list[tuple[tuple[int | str | bool, ...], dict[str, str]]]
        ] = {}

        for model, entries in self._owned_records().items():
            serializer = serializers._for_model(model)
            if serializer is None:
                continue
            serializer = serializer.with_context(
                builder_package=self.name, builder_dep_sink=dep_sink
            )
            for xmlid, record in entries:
                target = serializer._target_file(record)
                key = serializer._sort_key(record, xmlid)
                if serializer._builder_format == "csv":
                    csv_rows.setdefault(target, []).append(
                        # `_csv_row`/`_render_csv` (further below) are not part
                        # of `BuilderSerializer`'s own base-class contract --
                        # only the `_builder_format == "csv"` subclasses
                        # (`ir_security.py`, wave 1, not yet typed) declare
                        # them, by convention rather than an abstract method.
                        # A real, pre-existing design gap, flagged rather than
                        # fixed here (this migration's own "type-adding pass
                        # only" rule); `Any` is the honest type at this one
                        # dynamically-dispatched call.
                        (key, cast("Any", serializer)._csv_row(record, xmlid))
                    )
                else:
                    node = serializer._serialize(record, xmlid)
                    buckets.setdefault(target, []).append(
                        (key, node, serializer._builder_noupdate)
                    )

        files: dict[str, str] = {}
        for target, items in buckets.items():
            items.sort(key=lambda item: item[0])
            plain = [node for _key, node, nou in items if not nou]
            noupdate = [node for _key, node, nou in items if nou]
            root = xml_writer.build_document(plain, noupdate)
            files[target] = xml_writer.serialize_document(root)

        for target, rows in csv_rows.items():
            rows.sort(key=lambda item: item[0])
            # Same "not part of the base contract" gap as `_csv_row` above --
            # but here the model name is a literal, so the cast can name the
            # real subclass exactly rather than falling back to `Any`.
            access = cast(
                "IrModelAccessSerializer", serializers._for_model("ir.model.access")
            )
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

    def _render_translations(self, serializers: BuilderSerializer) -> dict[str, str]:
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
            for code, _name in typed.model(self.env, Lang).get_installed()
            if code != "en_US"
        ]
        if not langs:
            return {}

        rows: dict[str, list[tuple[str, str, pogen.Occurrence]]] = {
            lang: [] for lang in langs
        }
        for model, entries in self._owned_records().items():
            serializer = serializers._for_model(model)
            if serializer is None:
                continue
            for xmlid, record in entries:
                # Already `module.name` -- _owned_records qualifies it.
                for fname in serializer._translatable_fields(record):
                    field = record._fields.get(fname)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
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
                        # `get_translation_dictionary`/`get_trans_terms` live
                        # on `_String` (`odoo/fields.py`), not on the plain
                        # `Field` every other read in this file goes through
                        # -- narrowed here rather than widening the `_fields`
                        # idiom everywhere, since only a translate=True field
                        # (confirmed by `_translatable_fields` above) ever
                        # reaches this line.
                        # `get_translation_dictionary` is itself unannotated,
                        # so pyright infers its return from the body alone
                        # (`defaultdict(lambda: defaultdict(dict))`) rather
                        # than the method's own documented shape (`:return:
                        # {from_lang_term: {lang: lang_term}}`) -- cast to
                        # what the docstring already promises.
                        dictionary = cast(
                            "dict[str, dict[str, str]]",
                            cast("_String", field).get_translation_dictionary(
                                source, translated
                            ),
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

        files: dict[str, str] = {}
        for lang in langs:
            relative = "i18n/%s.po" % lang
            content = pogen.merge_po(
                self._read_source(relative),
                cast("str", self.name),
                lang,
                pogen.merge_terms(rows[lang]),
            )
            if content:
                files[relative] = content
        return files

    def _render_python(self) -> dict[str, str]:
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
        owned = cast("BuilderPackageModel", self.model_ids).filtered(
            lambda m: m.source in ("python", "frozen")
        )
        if not owned:
            return {}

        files: dict[str, str] = {}
        emitted: list[str] = []
        for entry in owned.sorted(lambda m: m.model):
            # `python_path` is compute-only (`_compute_python_path`,
            # builder_package_model.py) and always derived from `model` -- the
            # field's declared type is `str | Literal[False]` like any Char,
            # but it is never actually empty for a real row.
            relative = cast("str", entry.python_path)
            # Same required-field cast as `python_path` above.
            entry_model = cast("str", entry.model)
            existing = self._read_source(relative)
            spec = entry._current_spec()  # may freeze the row as a side effect

            if spec is not None and existing is not None:
                # Splice the block back in and leave every other byte alone.
                rewritten = pycodegen.splice_block(
                    existing, pycodegen.render_block(spec), spec
                )
                files[relative] = pycodegen.ensure_imports(rewritten, spec)
                emitted.append(entry_model)
                continue

            if existing is not None:
                # Frozen, or a file whose block we could not read: keep it
                # exactly as it is rather than guessing.
                files[relative] = existing
                emitted.append(entry_model)
                continue

            seeded = self._seed_python_from_metadata(entry)
            if seeded is None:
                continue
            files[relative] = seeded
            emitted.append(entry_model)

        if emitted:
            files["models/__init__.py"] = self._render_models_init(emitted)
        return files

    def _assert_no_double_definition(
        self, data_files: dict[str, str], python_files: dict[str, str]
    ) -> None:
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
        for entry in cast("BuilderPackageModel", self.model_ids):
            if entry.extends or entry.python_path not in python_files:
                continue
            # `model` is a required Char (builder_package_model.py), so this is
            # the same "declared str | False, never actually False" cast as
            # `python_path` above.
            clash = "models/%s.xml" % cast("str", entry.model).replace(".", "_")
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

    def _seed_python_from_metadata(self, entry: BuilderPackageModel) -> str | None:
        """First render for a model that has no file yet -- i.e. adoption.

        The only direction in which ``ir.model`` is an input rather than a
        reflection artefact, and it happens exactly once per model.
        """
        self.ensure_one()
        model = typed.model(self.env, IrModel).search(
            [("model", "=", entry.model)], limit=1
        )
        if not model:
            _logger.warning(
                "Package %s claims %s but no such model exists",
                self.name,
                entry.model,
            )
            return None
        # Only fields this package owns: Odoo declares the magic columns
        # itself, and a field from another module is not ours to redeclare.
        #
        # `field_id` (`ir.model.field_id`) is a plain-string-comodel
        # One2many in core (no typed-relation syntax there), so pyright
        # cannot resolve its element type from the declaration alone and
        # falls back to an unusable union -- the same gap `pycodegen.py`'s
        # own `record.selection_ids` documents and fixes the same way.
        owned_fields = cast("IrModelFields", model.field_id).filtered(  # pyright: ignore[reportUnknownMemberType]
            lambda f: f.state == "manual"
        )
        return pycodegen.render_model(pycodegen.spec_from_ir_model(model, owned_fields))

    def _render_bootstrap_files(self) -> dict[str, str]:
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

    def _seed_source_for(self, model_name: str, spec: ModelSpec) -> str:
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

    def _seed_app_icon(self) -> str:
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
        # `_assert_writable` already raised if `root_path` were falsy -- the
        # same "invariant the caller already guaranteed, not visible from
        # here" shape as `builder_serializer.py`'s own `cast("str", self
        # ._builder_model)`.
        full = os.path.join(cast("str", self.root_path), APP_ICON_FILE)
        if not os.path.isfile(full):
            os.makedirs(os.path.dirname(full), exist_ok=True)
            shutil.copyfile(file_path(DEFAULT_APP_ICON), full)
        return "%s,%s" % (self.name, APP_ICON_FILE)

    def _read_source(self, relative: str) -> str | None:
        """Return the on-disk content of a package file, or ``None``."""
        self.ensure_one()
        full = os.path.join(self.root_path or "", relative)
        if not os.path.isfile(full):
            return None
        with open(full, encoding="utf-8") as handle:
            return handle.read()

    def _render_models_init(self, model_names: Iterable[str]) -> str:
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

    def _render_manifest(
        self, data_files: list[str], dep_sink: set[str] | None = None
    ) -> str:
        """Build the manifest, preserving hand-edited keys."""
        self.ensure_one()
        existing: Manifest = {}
        path = os.path.join(self.root_path or "", "__manifest__.py")
        if os.path.isfile(path):
            try:
                existing = manifest_tools.read_manifest(path)
            except (SyntaxError, ValueError) as err:
                _logger.warning("Unparseable manifest at %s: %s", path, err)
        generated: Manifest = {
            "name": self.display_name_ or self.name,
            "version": self.version,
            "category": self.category or "Customization",
            "author": self.author or "App Builder",
            "license": self.license or DEFAULT_LICENSE,
            "installable": True,
            # Declared dependencies, plus every module we actually reference.
            # Deriving this rather than trusting the user is what makes a
            # generated package installable into a database that does not
            # already happen to contain what it points at.
            #
            # `_effective_depends`/`_order_data_files` are genuinely
            # `list[str]`, a narrower type than `Manifest`'s own
            # `list[ManifestValue]` -- generics are invariant, so the cast
            # states plainly what is already true of every element.
            "depends": cast("list[ManifestValue]", self._effective_depends(dep_sink)),
            # Load order matters: models before views before security.
            "data": cast("list[ManifestValue]", self._order_data_files(data_files)),
        }
        if self.summary:
            generated["summary"] = self.summary
        return manifest_tools.render_manifest(
            manifest_tools.merge_manifest(existing, generated)
        )

    def _effective_depends(self, dep_sink: set[str] | None = None) -> list[str]:
        """Union of declared depends and every module we actually need."""
        self.ensure_one()
        declared = {d.strip() for d in (self.depends or "").split(",") if d.strip()}
        referenced = set(dep_sink or ())
        # 'base' is implicit but harmless (and conventional) to state.
        depends = (declared | referenced | self._python_depends() | {"base"}) - {
            self.name
        }
        return sorted(depends)

    def _python_depends(self) -> set[str]:
        """Modules our generated *classes* need, which no xmlid ref reveals.

        ``dep_sink`` is filled while serializing records, so it only ever sees
        what XML points at. A class doing ``_inherit = ["mail.thread"]`` needs
        ``mail`` just as much, and nothing in the data files says so -- the
        package installs fine here and fails on a database without mail, which
        is the same class of bug as the one recorded as design finding 4.
        """
        self.ensure_one()
        needed: set[str] = set()
        IrModelSudo = typed.model(self.env, IrModel).sudo()
        for entry in cast("BuilderPackageModel", self.model_ids).filtered(
            lambda m: m.source == "python"
        ):
            spec = entry._current_spec()
            if spec is None:
                continue
            # An extension's own `name` is a model somebody else declares, so
            # it is a dependency exactly as its mixins are -- and missing it
            # means the package installs here and fails on a database without
            # that module, which is design finding 4 all over again.
            inherited_models = spec.inherit + ((spec.name,) if spec.extends else ())
            for inherited in inherited_models:
                record = IrModelSudo.search([("model", "=", inherited)], limit=1)
                if not record:
                    continue
                needed.update(
                    part.strip() for part in (record.modules or "").split(",")
                )
        return {name for name in needed if name and name != self.name}

    @api.model
    def _order_data_files(self, paths: Iterable[str]) -> list[str]:
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

        def key(path: str) -> tuple[float, str]:
            head = rank.get(path.split("/")[0], 9)
            if path == MENUS_FILE:
                # Menus ref their action, so they must follow every view file
                # that defines one. Alphabetically "menus.xml" would sort first.
                return (head + 0.5, path)
            return (head, path)

        return sorted((p for p in paths if p.endswith((".xml", ".csv"))), key=key)

    def _has_xml_models(self) -> bool:
        """Whether any model this package owns is still defined as data.

        A mixed package -- some Python models, some manual ones, or a manual
        field on a core model -- still needs models before security.
        """
        self.ensure_one()
        python_owned = self._python_model_set()
        for _xmlid, record in self._owned_records().get("ir.model", []):
            # `_owned_records` groups by model name; every value under the
            # "ir.model" key is, by construction, really an `ir.model`
            # record -- the dict's own value type cannot say that per-key.
            if cast("IrModel", record).model not in python_owned:
                return True
        return False

    # -- disk I/O ---------------------------------------------------------

    def _assert_writable(self) -> None:
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

    def action_write_files(self) -> bool:
        """Serialize the package to disk and record checksums."""
        # `_assert_builder_manager` lives on `builder.security.mixin`
        # (`_inherit`, not a Python base class -- Odoo's registry merges
        # it in at runtime, invisibly to pyright); same cast idiom as
        # `_demote_manual_metadata`'s own `Environment.cr`.
        cast("BuilderSecurityMixin", self)._assert_builder_manager()
        for package in self:
            package._assert_writable()
            package._lock_for_write()
            files = package._render_files()
            written = package._write_files(files, prune=True)
            package._sync_file_records(files)
            package._run_auto_commit(written)
            package.state = "synced"
        return True

    def _write_files(self, files: dict[str, str], prune: bool = False) -> list[str]:
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
        # Every real caller already calls `_assert_writable()` first, which
        # raises if `root_path` is falsy -- the same "invariant guaranteed by
        # the caller's own contract, not provable from here" shape as
        # `_seed_app_icon`'s own cast above.
        root = cast("str", self.root_path)
        os.makedirs(root, exist_ok=True)
        self._claim_directory()
        _mute_dev_watcher(root)
        written: list[str] = []
        # What each file we touch held before, for `_undo_on_rollback`.
        previous: dict[str, bytes | None] = {}
        self._undo_on_rollback(root, previous)
        for relative, content in files.items():
            full = os.path.join(root, relative)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            # Skip untouched files so mtimes stay stable and the FS watcher
            # does not fire a pointless reload.
            if checksum.hash_file(full) == checksum.hash_text(content):
                continue
            previous[relative] = self._read_bytes(full)
            # Never truncate in place: a process killed between the truncate
            # and the write leaves an empty module file on the addons path.
            atomicfile.write_text(full, content)
            written.append(relative)
        # Again, after: the window is measured from the last write, not the
        # first, and the watcher hears about a file a moment after it lands.
        _mute_dev_watcher(root)

        if not prune:
            return written

        for stale in cast("BuilderPackageFile", self.file_ids).filtered(
            lambda f: f.path not in files
        ):
            # `path` is a required Char (`builder.package.file`, this file
            # below) -- same "declared str | False, never actually False"
            # cast as this file's other required-field reads.
            stale_path = cast("str", stale.path)
            full = os.path.join(root, stale_path)
            # Only remove files we generated and that nobody has since edited.
            if os.path.isfile(full) and (
                checksum.hash_file(full) == stale.generated_checksum
            ):
                previous[stale_path] = self._read_bytes(full)
                os.remove(full)
                written.append(stale_path)
        return written

    @api.model
    def _read_bytes(self, full: str) -> bytes | None:
        try:
            with open(full, "rb") as handle:
                return handle.read()
        except OSError:
            return None

    def _undo_on_rollback(self, root: str, previous: dict[str, bytes | None]) -> None:
        """Put the old bytes back if this transaction rolls back.

        The files are written inside the request's transaction, and the
        checksum rows that describe them roll back with it -- so without
        this a failure after the write (or a serialization failure, which
        makes Odoo roll back and *retry* the request) leaves source on disk
        for a change the database never made. ``previous`` is filled in as
        the write goes, so a failure half way through undoes exactly the
        half that happened.

        A commit clears the hook, which is what makes ``action_apply``'s own
        commit-then-reload safe: past that commit the files are the truth
        and restoring them is the apply record's job, not this one's. A
        savepoint rollback does not run it -- Odoo has no hook there -- so a
        caller that catches an exception around a write still owes the
        package an ``action_write_files()``.
        """

        def undo() -> None:
            if not previous:
                return
            _mute_dev_watcher(root)
            for relative, before in previous.items():
                full = os.path.join(root, relative)
                try:
                    if before is None:
                        if os.path.isfile(full):
                            os.remove(full)
                    else:
                        atomicfile.write_text(full, before.decode("utf-8"))
                except (OSError, UnicodeDecodeError) as err:
                    _logger.error(
                        "Could not restore %s after a rollback: %s", full, err
                    )
            _mute_dev_watcher(root)

        self.env.cr.postrollback.add(undo)

    # -- mutual exclusion -------------------------------------------------

    def _busy_error(self) -> UserError:
        return UserError(
            _(
                "The package %s is being written or applied by somebody else "
                "right now. Try again in a moment.",
                self.name,
            )
        )

    def _lock_for_write(self) -> None:
        """One writer per package, until this transaction ends.

        Every write renders the *whole* package and prunes what is no longer
        in it; two of them interleaved prune each other's files and leave
        checksum rows describing a tree neither of them wrote. A
        transaction-scoped advisory lock serialises them across threads and
        worker processes alike and needs no cleanup -- and it is refused,
        not waited for, because the second writer's render is already stale
        by the time the first one finishes.
        """
        self.ensure_one()
        # Same `Environment.cr` gap as `_demote_manual_metadata`'s own cast.
        cr = cast("Cursor", self.env.cr)
        key = (cast("str", cr.dbname), cast("int", self.id))
        owner = _APPLYING.get(key)
        if owner is not None and owner != threading.get_ident():
            raise self._busy_error()
        cr.execute(
            "SELECT pg_try_advisory_xact_lock(%s, %s)",
            (ADVISORY_LOCK_NAMESPACE, self.id),
        )
        row = cr.fetchone()
        if not (row and row[0]):
            raise self._busy_error()

    @contextlib.contextmanager
    def _applying(self) -> Generator[None, None, None]:
        """Hold the package for a whole apply, across its commits.

        The advisory lock above ends at the apply's own commit, which is
        *before* the reload -- the long part, and the part during which a
        second apply's snapshot/restore would trample the files the first
        one's upgrade is loading. In-place reloads only ever happen in a
        single process, so a process-wide marker is enough to span them.
        """
        self.ensure_one()
        key = (
            cast("str", cast("Cursor", self.env.cr).dbname),
            cast("int", self.id),
        )
        ident = threading.get_ident()
        with _APPLYING_GUARD:
            owner = _APPLYING.get(key)
            if owner is not None and owner != ident:
                raise self._busy_error()
            nested = owner == ident
            _APPLYING[key] = ident
        try:
            yield
        finally:
            if not nested:
                with _APPLYING_GUARD:
                    _APPLYING.pop(key, None)

    def _try_cron_lock(self) -> bool:
        """Take the lock core's module operations take, if it is free."""
        try:
            cr = cast("Cursor", self.env.cr)
            with mute_logger("odoo.sql_db"), cr.savepoint(flush=False):
                cr.execute("SELECT id FROM ir_cron FOR UPDATE NOWAIT")
        except psycopg2.OperationalError:
            return False
        return True

    def _acquire_cron_lock(self) -> None:
        """Wait, briefly, for scheduled actions to finish.

        ``_button_immediate_function`` runs ``SELECT * FROM ir_cron FOR
        UPDATE NOWAIT`` and raises if any scheduled action is running. Hit
        *after* the files are written, that sends a perfectly good apply
        down the failure path -- restore, second reload, an error -- for no
        reason but timing. So the lock is taken here first, with a short
        retry, before anything is written; holding it also keeps a cron
        from starting in between.
        """
        self.ensure_one()
        for attempt in range(CRON_LOCK_ATTEMPTS):
            if self._try_cron_lock():
                return
            if attempt + 1 < CRON_LOCK_ATTEMPTS:
                time.sleep(CRON_LOCK_DELAY)
        raise UserError(
            _(
                "Odoo is running a scheduled action, and a module cannot be "
                "reloaded while one runs. Try again in a moment."
            )
        )

    def _claim_directory(self) -> None:
        """Refuse a directory another database of this server is writing.

        ``builder.package`` rows are per database and a directory is not:
        two databases can each hold a row for the same addon, each with its
        own checksums and apply history, and a rollback in one restores
        bytes the other has since replaced. The directory remembers which
        database wrote it last; a different one *that this same process is
        serving* is refused. A copy of the database on another server, or a
        renamed one, simply takes the directory over.
        """
        self.ensure_one()
        root = cast("str", self.root_path)
        marker = os.path.join(root, OWNER_FILE)
        dbname = cast("str", cast("Cursor", self.env.cr).dbname)
        owner = ""
        # No marker yet: nobody has claimed the directory.
        with contextlib.suppress(OSError), open(marker, encoding="utf-8") as handle:
            owner = handle.read().strip()
        if owner == dbname:
            return
        if owner and owner in self._loaded_databases():
            raise UserError(
                _(
                    "The directory %(path)s is managed by the builder in "
                    "the database '%(db)s', which this server is also "
                    "serving. Two databases writing one package would "
                    "overwrite each other's work; edit it from that "
                    "database, or remove %(marker)s if it no longer does.",
                    path=root,
                    db=owner,
                    marker=marker,
                )
            )
        self._ignore_builder_dir()
        atomicfile.write_text(marker, dbname + "\n")

    def _ignore_builder_dir(self) -> None:
        """Keep ``.builder/`` out of the package's git history.

        Backups and markers live inside the package directory, and both the
        "before" commit and auto-commit stage with ``git add .`` -- which
        would put a second copy of every file the builder ever replaced into
        the repository. A ``.gitignore`` of its own inside the directory
        does it without touching the developer's.
        """
        self.ensure_one()
        ignore = os.path.join(cast("str", self.root_path), BUILDER_DIR, ".gitignore")
        if not os.path.isfile(ignore):
            atomicfile.write_text(ignore, "*\n")

    @api.model
    def _loaded_databases(self) -> set[str]:
        """Other databases this process has a registry for."""
        current = cast("str", cast("Cursor", self.env.cr).dbname)
        names = cast("list[str]", list(_registries().d))
        return {name for name in names if name != current}

    def _other_databases_using(self) -> list[str]:
        """Databases in this process that have this package installed.

        ``_reimport_module`` rewrites ``sys.modules`` and
        ``MetaModel.module_to_models``, and both belong to the process, not
        to a database. Another database with the package installed would
        build its next registry from the re-imported classes without its
        own schema upgrade -- new fields, no columns.
        """
        self.ensure_one()
        current = cast("str", cast("Cursor", self.env.cr).dbname)
        using: list[str] = []
        loaded = cast("list[tuple[str, Any]]", list(_registries().d.items()))
        for name, registry in loaded:
            if name == current:
                continue
            if self.name in getattr(registry, "_init_modules", ()):
                using.append(name)
        return sorted(using)

    def _sync_file_records(self, files: dict[str, str]) -> None:
        self.ensure_one()
        existing = {f.path: f for f in cast("BuilderPackageFile", self.file_ids)}
        for relative, content in files.items():
            digest = checksum.hash_text(content)
            record = existing.pop(relative, None)
            if record:
                # Both checksums: disk_checksum drives `drifted`, so leaving it
                # at its previous value marks every file we just wrote as
                # drifted until someone runs a drift check.
                record.write({"generated_checksum": digest, "disk_checksum": digest})
            else:
                # `create()`'s own declared signature (`odoo/models.py`) takes
                # only `list[ValuesType]` -- `@api.model_create_multi`
                # (`odoo/api.py`) is a bare passthrough decorator (`def
                # model_create_multi(method: T) -> T`), so it does not widen
                # the type to also cover the single-dict form it genuinely
                # accepts at runtime (unwrapping the list back to one record
                # on return). The same shape of decorator-stub gap already
                # documented for `@tools.ormcache`/`assert_log_admin_access`.
                vals: dict[str, Any] = {
                    "package_id": self.id,
                    "path": relative,
                    "generated_checksum": digest,
                    "disk_checksum": digest,
                }
                typed.model(self.env, BuilderPackageFile).create(vals)  # pyright: ignore[reportArgumentType]
        if existing:
            typed.model(self.env, BuilderPackageFile).browse(
                [r.id for r in existing.values()]
            ).unlink()

    def _run_auto_commit(self, written: list[str]) -> None:
        self.ensure_one()
        if not written or self.auto_commit == "off" or not self.is_git:
            return
        root = cast("str", self.root_path)
        paths = [os.path.join(root, p) for p in written]
        if self.auto_commit == "stage":
            gitrepo.add(root, paths)
        else:
            # After the database commit, not before it: a git commit cannot
            # be rolled back with the transaction, and one made here would
            # record a change the database may yet refuse.
            self.env.cr.postcommit.add(
                functools.partial(
                    gitrepo.commit,
                    root,
                    "builder(%s): update %s"
                    % (self.name, ", ".join(sorted(written)[:5])),
                    paths,
                )
            )

    def builder_capture(
        self, records: BaseModel | Iterable[BaseModel] | None, write_files: bool = True
    ) -> bool:
        """Take ownership of ``records`` and flush the package to disk.

        This is the single entry point every builder module calls after it
        changes something. Assigning the xmlid and writing the file happen in
        the caller's transaction, and the write registers its own undo for a
        rollback (``_undo_on_rollback``), so the database and the source
        tree advance together or not at all -- which is what lets us treat
        the DB write as an optimisation rather than a second source of
        truth. Files are replaced atomically, and a git commit is made only
        once the database has committed.

        ``write_files=False`` takes ownership without touching the disk, and
        leaves the package marked as having a write pending. It is for a
        caller that captures several things in one gesture -- a field, then
        the view it lands in -- and wants the directory written once, last:
        a file written for the first step and then a failure in the second
        would leave source on disk for a change the transaction rolled back.
        The caller owes the package an ``action_write_files()``.
        """
        # `_assert_builder_manager` lives on `builder.security.mixin`
        # (`_inherit`, not a Python base class -- Odoo's registry merges
        # it in at runtime, invisibly to pyright); same cast idiom as
        # `_demote_manual_metadata`'s own `Environment.cr`.
        cast("BuilderSecurityMixin", self)._assert_builder_manager()
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

    def action_adopt(self, model_names: Iterable[str]) -> dict[str, Any]:
        """Bring an existing ``x_`` manual model under Python management.

        Not a milestone, and not a handoff. New models are Python from the
        first save; this is the migration path for what came before -- a
        package built by an older version of the builder, or a model somebody
        made by hand in Settings -> Technical.

        Afterwards the model is exactly like any other the builder owns: the
        marked block inside its class stays in sync, and everything outside it
        is the developer's. Adopting does not close any door.

        The new class takes effect once the package reloads, which
        ``--dev=reload`` does for you.
        """
        # `_assert_builder_manager` lives on `builder.security.mixin`
        # (`_inherit`, not a Python base class -- Odoo's registry merges
        # it in at runtime, invisibly to pyright); same cast idiom as
        # `_demote_manual_metadata`'s own `Environment.cr`.
        cast("BuilderSecurityMixin", self)._assert_builder_manager()
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
            cast("BuilderPackageModel", self.env["builder.package.model"])._adopt(
                self, model_name, source="python"
            )
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

    def _assert_module_installed(self) -> None:
        """Refuse to adopt into a package Odoo has not installed as a module.

        Odoo only imports Python for modules in the dependency graph. If the
        package is merely a directory of files that nobody installed, demoting
        the metadata removes the manual definition while nothing replaces it,
        and the model disappears from the registry at the next restart.
        """
        self.ensure_one()
        module = (
            typed.model(self.env, IrModuleModule)
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

    def _write_adopted_source(self, model_names: Iterable[str]) -> None:
        """Emit the Python for ``model_names`` from their live metadata.

        Written directly rather than through ``action_write_files`` because
        this has to happen while the metadata still exists, and before the
        pruning pass that removes the XML it replaces.
        """
        self.ensure_one()
        env = self._source_env()
        # `_assert_writable` was already called by every real caller
        # (`action_adopt`) before this -- same invariant as `_write_files`'s
        # own `root` cast above.
        root = cast("str", self.root_path)
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
            model = typed.model(env, IrModel).search(
                [("model", "=", model_name)], limit=1
            )
            if not model:
                continue
            owned = cast("IrModelFields", model.field_id).filtered(  # pyright: ignore[reportUnknownMemberType]
                lambda f: f.state == "manual"
            )
            atomicfile.write_text(
                os.path.join(root, relative),
                pycodegen.render_model(pycodegen.spec_from_ir_model(model, owned)),
            )

        atomicfile.write_text(
            os.path.join(root, "models/__init__.py"),
            self._render_models_init(emitted),
        )
        atomicfile.write_text(
            os.path.join(root, "__init__.py"), pycodegen.render_package_init(True)
        )

    def _demote_manual_metadata(self, model_names: Iterable[str]) -> None:
        """Retire the manual metadata rows, keeping the table and its data.

        Without this the graduation does not survive a restart. Two things go
        wrong if the ``state='manual'`` rows are left behind:

        * ``_add_manual_models`` rebuilds a custom class for the model from
          those rows on every ``setup_models``, competing with the Python class
          for the same ``_name``;
        * ``_process_end`` then finds the builder's ``ir.model.data`` rows absent
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
        # `Environment.cr` is declared `BaseCursor` (`odoo/api.py`), which
        # has no `.execute`/`.commit` of its own -- those live on the real
        # `Cursor` subclass every live request actually gets. The same
        # "declared type too abstract for what's really there at runtime"
        # shape as `Environment.user` (builder_security.py's own cast).
        cr = cast("Cursor", self.env.cr)
        cr.execute(
            """
            UPDATE ir_model_fields SET state = 'base'
             WHERE model IN %s AND state = 'manual'
            """,
            (tuple(names),),
        )
        cr.execute(
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

    def action_delete_records(self) -> bool:
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
        # `_assert_builder_manager` lives on `builder.security.mixin`
        # (`_inherit`, not a Python base class -- Odoo's registry merges
        # it in at runtime, invisibly to pyright); same cast idiom as
        # `_demote_manual_metadata`'s own `Environment.cr`.
        cast("BuilderSecurityMixin", self)._assert_builder_manager()
        self.ensure_one()
        data = self._deletable_data()
        by_model: dict[str, list[int]] = {}
        for entry in data:
            # Same required-Char cast as `_owned_records`'s own `entry_model`.
            by_model.setdefault(cast("str", entry.model), []).append(entry.res_id)

        env = self.env(
            context=dict(cast("dict[str, Any]", self.env.context), _force_unlink=True)
        )
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
        cast("BuilderPackageFile", self.file_ids).unlink()
        self.state = "draft"
        return True

    def _deletable_data(self) -> IrModelData:
        """The package's ``ir.model.data`` rows minus reflection artefacts.

        A row is ours to delete only if the record behind it is one the
        serializers would have emitted. Anything reflected from a Python class
        -- ``state='base'`` metadata, mixin fields, magic columns -- carries our
        module name purely because our class declared it, and deleting it is
        Odoo's job during uninstall, not ours.
        """
        self.ensure_one()
        data = typed.model(self.env, IrModelData).search([("module", "=", self.name)])
        serializers = self._serializer_env()
        keep: list[IrModelData] = []
        for entry in data:
            # Same required-Char cast as `_owned_records`'s own `entry_model`.
            entry_model = cast("str", entry.model)
            if entry_model not in self.env:
                continue
            record = self.env[entry_model].browse(entry.res_id)
            if not record.exists():
                keep.append(entry)  # a dangling row: dropping it is harmless
                continue
            serializer = serializers._for_model(entry_model)
            if serializer is not None and not serializer._ownable(record):
                continue
            keep.append(entry)
        return typed.model(self.env, IrModelData).browse([e.id for e in keep])

    # -- apply -------------------------------------------------------------

    def _compute_reload_mode(self) -> None:
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
        does not install a module that is only marked for it. The builder
        reloads its own packages in process instead, and mutes the watcher
        for its own writes (``_mute_dev_watcher``).
        """
        workers = cast("int", tools_config["workers"])
        for package in self:
            # Several databases in one process is the same problem as several
            # workers, turned sideways: the re-import is process-wide and the
            # upgrade that has to follow it is per database.
            manual = bool(workers) or bool(package._other_databases_using())
            package.reload_mode = "manual" if manual else "inproc"

    def _manual_reload_reason(self) -> str:
        """Why this package cannot be reloaded in place, as a sentence."""
        self.ensure_one()
        workers = cast("int", tools_config["workers"])
        if workers:
            return _(
                "This server runs %(workers)s worker processes, so a package "
                "cannot be reloaded in place: the other workers would rebuild "
                "their registry against the Python they already have in "
                "memory. Restart the server to pick this change up.",
                workers=workers,
            )
        return _(
            "This server process also serves the database(s) %(dbs)s, which "
            "have %(name)s installed. Reloading its Python in place would "
            "change it under them without upgrading their schema. Restart "
            "the server to pick this change up, and upgrade the package in "
            "those databases too (-u %(name)s).",
            dbs=", ".join(self._other_databases_using()),
            name=self.name,
        )

    def _can_install_in_place(self) -> bool:
        """Whether this is a first install, which any server can do in place.

        What makes an in-place *reload* wrong under workers is Python that
        other processes already hold. A package that is not installed has
        never been imported by anybody -- Odoo only imports installed
        modules -- so installing it is exactly what the Apps menu does on a
        multi-worker server every day: this process imports and installs,
        signals, and the others import it fresh when they rebuild.
        """
        self.ensure_one()
        if "odoo.addons.%s" % self.name in sys.modules:
            return False
        module = (
            typed.model(self.env, IrModuleModule)
            .sudo()
            .search([("name", "=", self.name)], limit=1)
        )
        return module.state in (False, "uninstalled")

    def _mark_for_restart(self) -> str:
        """Make the restart the user is told about create the schema.

        Written to disk and not loaded, an installed package is new Python
        beside an old schema, and a plain boot does not close that gap:
        ``load_modules`` imports the classes and runs ``init_models`` only
        for a module that is marked. Left alone, the restart would bring up
        a model whose new fields have no columns, and every read of it
        would fail until somebody ran ``-u`` from a shell.

        A module in state ``to upgrade`` *is* upgraded by any registry load,
        with or without ``-u`` (``odoo/modules/loading.py``: ``needs_update``
        is true for that state, and the first ``load_marked_modules`` pass
        is unconditional) -- pre-migrations included. So the mark is set
        here, durably, and the restart does the rest. A package that is not
        installed needs nothing: its Python is not imported at boot.

        Returns what the restart has to be, as a sentence for the user.
        """
        self.ensure_one()
        self._invalidate_module_caches()
        Module = typed.model(self.env, IrModuleModule).sudo()
        module = Module.search([("name", "=", self.name)], limit=1)
        if module.state not in ("installed", "to upgrade"):
            return _(
                "Restart the server, then install %(name)s (from the builder "
                "or the Apps menu).",
                name=self.name,
            )
        if module.state == "installed":
            try:
                # Core's own entry point: it also marks whatever depends on
                # this package, which has to be upgraded with it.
                module.button_upgrade()
            except UserError:
                _logger.exception(
                    "Could not mark %s for upgrade through button_upgrade; "
                    "marking the module itself",
                    self.name,
                )
                module.write({"state": "to upgrade"})
        if Module.search_count([("state", "=", "to install")]):
            # A dependency the package gained is not installed, and a plain
            # boot does not install: only `-u`/`-i` runs that pass.
            return _(
                "Restart the server with -u %(name)s: the package now "
                "depends on a module that is not installed yet, and only an "
                "explicit upgrade installs it.",
                name=self.name,
            )
        return _(
            "Restart the server. %(name)s is marked for upgrade, so the "
            "restart also updates the database schema; no -u is needed.",
            name=self.name,
        )

    def _reimport_module(self) -> None:
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

    def _reload_now(self) -> Any:
        """Make the running process see the source that is on disk.

        Order is load-bearing and was measured, not reasoned about: purge
        first, so the import happens at all; *then* upgrade, so ``init_models``
        runs and the schema follows. Purging alone leaves the new field in the
        ORM and absent from Postgres, because ``Registry.new`` only runs
        ``init_models`` for modules marked ``to upgrade``.
        """
        self.ensure_one()
        if self.reload_mode == "manual" and not self._can_install_in_place():
            raise UserError(self._manual_reload_reason())
        self._reimport_module()
        module = self._find_or_create_module()
        if module.state == "installed":
            return module.button_immediate_upgrade()
        return module.button_immediate_install()

    def _assert_sources_compile(self, files: dict[str, str]) -> None:
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

    def _assert_specs_reparse(self, files: dict[str, str]) -> None:
        """Everything we are about to write must read back as what it says.

        Cheap here, and the alternative is discovering on the next save that a
        file we generated is one the parser refuses -- at which point the model
        freezes and the builder appears to have broken itself.
        """
        self.ensure_one()
        for entry in cast("BuilderPackageModel", self.model_ids).filtered(
            lambda m: m.source == "python"
        ):
            # Same compute-derived-never-False cast as `_render_python`'s own
            # `relative`.
            entry_path = cast("str", entry.python_path)
            content = files.get(entry_path)
            if content is None:
                continue
            try:
                spec = pyparse.parse_model(content)
            except pyparse.UnsupportedConstruct as err:
                raise UserError(
                    _(
                        "Generated %(path)s is not something the builder can "
                        "read back (%(err)s). Nothing was written.",
                        path=entry_path,
                        err=err,
                    )
                ) from err
            if pycodegen.render_model(spec) != content:
                raise UserError(
                    _(
                        "Generated %(path)s does not round-trip. Nothing was "
                        "written; please report this.",
                        path=entry_path,
                    )
                )

    def _destructive_changes(self, files: dict[str, str]) -> dict[str, tuple[str, ...]]:
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
        dropped: dict[str, tuple[str, ...]] = {}
        owned_field_ids = self._owned_field_ids()
        # Extensions excluded: one declares no fields of its own, so its empty
        # field list is not "every column removed" -- it is "this class is not
        # where the columns are declared".
        for entry in cast("BuilderPackageModel", self.model_ids).filtered(
            lambda m: m.source == "python" and not m.extends
        ):
            # Same required-Char cast as `_render_python`'s own `entry_model`.
            entry_model = cast("str", entry.model)
            source = files.get(cast("str", entry.python_path))
            if source is None:
                continue
            try:
                after = pyparse.parse_model(source)
            except pyparse.UnsupportedConstruct:
                continue  # frozen; we are not rewriting it anyway
            model = typed.model(self.env, IrModel).search(
                [("model", "=", entry_model)], limit=1
            )
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
                    keeping |= set(self.env[mixin]._fields)  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType, reportUnknownMemberType]
            # Same `field_id` gap as `_seed_python_from_metadata`'s own cast.
            model_fields = cast("IrModelFields", model.field_id)  # pyright: ignore[reportUnknownMemberType]
            gone = sorted(
                cast("str", record.name)
                for record in model_fields
                if record.id in owned_field_ids
                and record.store
                and record.name not in keeping
            )
            if gone:
                dropped[entry_model] = tuple(gone)
        return dropped

    def _owned_field_ids(self) -> set[int]:
        """ids of ``ir.model.fields`` records carrying this package's xmlid."""
        self.ensure_one()
        entries = typed.model(self.env, IrModelData).search(
            [("module", "=", self.name), ("model", "=", "ir.model.fields")]
        )
        return set(cast("list[int]", entries.mapped("res_id")))

    def _bump_version_for_migration(self) -> str:
        """Move the package to a version its pre-migration can run under.

        Odoo runs ``migrations/<v>/pre-*.py`` only when ``installed < v <=
        manifest version`` (``odoo/modules/migration.py``). A script filed
        under the version that is already installed is therefore skipped --
        silently, and ``_process_end`` then drops the very columns it was
        written to save. So a destructive apply is a new version of the
        package: the manifest says so, and the script lives under it.

        The baseline is whichever is higher of the package's own version
        and what the database says is installed, so a version raised by
        hand in the manifest cannot leave the new one at or below it.
        """
        self.ensure_one()
        base = cast("str", self.version)
        try:
            adapted = _adapt_version(base)
        except ValueError as err:
            raise UserError(
                _(
                    "The package version '%(version)s' is not one Odoo "
                    "understands (%(err)s). Fix it before removing fields: "
                    "the migration that keeps their data is filed by version.",
                    version=base,
                    err=err,
                )
            ) from err
        module = (
            typed.model(self.env, IrModuleModule)
            .sudo()
            .search([("name", "=", self.name)], limit=1)
        )
        installed = module.latest_version
        if installed and parse_version(installed) >= parse_version(adapted):
            base = installed
        version = migrationgen.bump_version(base)
        self.version = version
        return version

    def _render_pre_migration(
        self, dropped: dict[str, tuple[str, ...]], stamp: str
    ) -> str | None:
        """Rename everything this apply would drop aside, in one script.

        One script for the whole apply, not one per model: they would all
        share a path, and the last model's would be the only one written.

        The table is the model's real one, read from the registry. A
        many2many has no column on it; what Odoo drops with a *manual*
        many2many is its relation table, unless another field still uses
        it, so that is what is renamed. A many2many declared in Python is
        left alone because core leaves its relation table alone too
        (``IrModelFields._drop_column`` only drops for ``state='manual'``):
        the links are still there, under the name they always had.
        """
        self.ensure_one()
        Fields = typed.model(self.env, ir_model_module.IrModelFields).sudo()
        columns: list[tuple[str, str]] = []
        relations: list[str] = []
        doomed = Fields.browse()
        by_model: dict[str, dict[str, IrModelFields]] = {}
        for model_name, names in dropped.items():
            records = Fields.search(
                [("model", "=", model_name), ("name", "in", list(names))]
            )
            doomed |= records
            by_model[model_name] = {
                cast("str", record.name): record for record in records
            }
        for model_name, names in sorted(dropped.items()):
            model = cast("BaseModel | None", self.env.get(model_name))
            table = (
                cast("str", model._table)
                if model is not None
                else model_name.replace(".", "_")
            )
            for name in names:
                record = by_model[model_name].get(name)
                if record is None or record.ttype != "many2many":
                    columns.append((table, name))
                    continue
                if record.state != "manual":
                    continue
                relation: Any = record.relation_table
                if not relation and model is not None:
                    declared: Any = cast("dict[str, Any]", model._fields).get(name)
                    relation = getattr(declared, "relation", None)
                if isinstance(relation, str) and not Fields.search_count(
                    [("relation_table", "=", relation), ("id", "not in", doomed.ids)]
                ):
                    relations.append(relation)
        return migrationgen.render_pre_migrations(columns, relations, stamp)

    def action_apply(
        self,
        reason: str = "",
        allow_destructive: bool = False,
        overlay: dict[str, str] | None = None,
        reload: bool | None = None,
    ) -> BuilderPackageApply:
        """Write the package and make the running process see it.

        The sequence is fixed and none of it is optional -- see the class
        docstring on ``builder.package.apply`` for why a half-finished apply is
        not something the ORM can roll back for us.

        ``overlay`` is content a caller has for files the render would
        otherwise produce from disk -- a draft's rewritten ``.py`` -- and
        it goes through this sequence *instead of* being written first:
        the snapshot at step 3 has to record the bytes the file had before
        the change, or a rollback puts the change back.

        ``reload=False`` -- and any apply on a server that cannot reload
        in place -- stops after step 5. The files are on disk and
        committed, the apply is ``awaiting_restart``, the module is marked
        ``to upgrade`` so that the restart creates the schema
        (``_mark_for_restart``), and the restart the user is told about is
        what makes the change live. Nothing is restored, because nothing
        was loaded and nothing could have gone wrong yet.

        One apply per package at a time (``_applying``): a second one is
        refused rather than queued, because what it rendered is stale by
        the time the first has finished.
        """
        # `_assert_builder_manager` lives on `builder.security.mixin`
        # (`_inherit`, not a Python base class -- Odoo's registry merges
        # it in at runtime, invisibly to pyright); same cast idiom as
        # `_demote_manual_metadata`'s own `Environment.cr`.
        cast("BuilderSecurityMixin", self)._assert_builder_manager()
        self.ensure_one()
        self._assert_writable()
        with self._applying():
            return self._apply(reason, allow_destructive, overlay, reload)

    def _apply(
        self,
        reason: str,
        allow_destructive: bool,
        overlay: dict[str, str] | None,
        reload: bool | None,
    ) -> BuilderPackageApply:
        self.ensure_one()
        self._lock_for_write()
        in_place = reload is not False and (
            self.reload_mode != "manual" or self._can_install_in_place()
        )
        if in_place:
            # Before anything is written: a scheduled action in flight makes
            # the reload fail, and failing here costs nothing.
            self._acquire_cron_lock()

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
            migration = self._render_pre_migration(dropped, stamp)
            if migration:
                # Ordering is what makes this work: migrate_module(pkg, 'pre')
                # runs long before _process_end, so by the time _drop_column
                # looks the column is already gone under its old name and it
                # drops nothing. And the *version* is what makes it run at
                # all -- see `_bump_version_for_migration`.
                version = self._bump_version_for_migration()
                # The manifest carries the version, so it is rendered again.
                files = self._render_files()
                files.update(overlay or {})
                files[migrationgen.migration_path(version, stamp)] = migration
        apply_model = cast("BuilderPackageApply", self.env["builder.package.apply"])
        apply = apply_model._snapshot(  # 3. keep the old bytes
            self, files, reason=reason, stamp=stamp
        )
        if self.is_git:
            root = cast("str", self.root_path)
            gitrepo.commit(root, "builder: before %s" % (reason or "apply"))

        written = self._write_files(files, prune=True)  # 4. write
        self._sync_file_records(files)
        self._run_auto_commit(written)
        # Same `Environment.cr` gap as `_demote_manual_metadata`'s own cast.
        cast("Cursor", self.env.cr).commit()  # 5. commit BEFORE the reload
        # The apply row is durable now; the on-disk journal that stood in
        # for it while the files were being written has done its job.
        apply._clear_journal()

        if not in_place:
            apply.write(
                {
                    "state": "awaiting_restart",
                    "restart_hint": self._mark_for_restart(),
                }
            )
            self.state = "synced"
            return apply

        try:
            # Again: the commit above released the lock taken before the
            # write, and core will ask for it without waiting.
            self._acquire_cron_lock()
            self._reload_now()  # 6. reimport, then upgrade
        except Exception as err:  # 7. restore and go back to a good registry
            _logger.exception("Apply failed for package %s", self.name)
            apply._restore()
            cast("Cursor", self.env.cr).commit()
            try:
                self._reload_now()
            except Exception:  # pragma: no cover - already in trouble
                _logger.exception(
                    "Could not reload %s after a failed apply; the package on "
                    "disk has been restored but this process may be stale",
                    self.name,
                )
                cast("Cursor", self.env.cr).rollback()
            apply.write({"state": "failed", "error": str(err)})
            # The UserError below rolls this request back; without a commit
            # the row would stay 'pending' and the failure would be recorded
            # nowhere but the log.
            cast("Cursor", self.env.cr).commit()
            raise UserError(
                _(
                    "This change could not be applied and has been rolled "
                    "back:\n\n%(err)s",
                    err=err,
                )
            ) from err

        apply.state = "applied"
        self.state = "synced"
        self._close_awaiting_restart()
        return apply

    def _close_awaiting_restart(self) -> None:
        """A reload from disk makes every earlier written-not-loaded apply
        live with it: there is nothing left for a restart to do."""
        self.ensure_one()
        waiting = cast("BuilderPackageApply", self.apply_ids).filtered(
            lambda a: a.state == "awaiting_restart"
        )
        if waiting:
            waiting.write({"state": "applied", "restart_hint": False})

    @api.model
    def _warn_orphans_on_uninstall(self) -> list[str]:
        """Name the packages uninstalling the builder leaves without an owner.

        Uninstalling removes the builder's own records -- the package
        registry, the apply history and its snapshots -- and nothing a
        package *contains*. For a package that is installed as a module
        that is the right outcome: the module still owns its records and
        Odoo manages them as it does any addon's. A package that was never
        installed is different: the views, fields and menus it captured
        stay live, under xmlids no installed module answers to, and with
        the builder gone nothing is left that knows they belong together.
        That is not destructive, and it is not something to do silently.
        """
        Module = typed.model(self.env, IrModuleModule).sudo()
        Data = typed.model(self.env, IrModelData).sudo()
        orphaned: list[str] = []
        for package in self.sudo().search([]):
            module = Module.search([("name", "=", package.name)], limit=1)
            if module.state == "installed":
                continue
            count = Data.search_count([("module", "=", package.name)])
            if not count:
                continue
            orphaned.append(cast("str", package.name))
            _logger.warning(
                "Uninstalling App Builder while package %s is not installed "
                "as a module: its %d record(s) stay in the database under "
                "the '%s.' xmlid prefix with no module managing them. Its "
                "source is kept at %s; install that addon to give them an "
                "owner again, or delete them by hand.",
                package.name,
                count,
                package.name,
                package.root_path or "(no directory)",
            )
        return orphaned

    def _schema_behind(self) -> list[str]:
        """What this package's Python declares and the database lacks.

        The half-way state a restart without an upgrade leaves: the class
        is imported, the registry has the field, and the table has no
        column for it -- or no table at all. Empty when the two agree.
        """
        self.ensure_one()
        missing: list[str] = []
        for entry in cast("BuilderPackageModel", self.model_ids).filtered(
            lambda m: m.source in ("python", "frozen") and m.model
        ):
            name = cast("str", entry.model)
            model = cast("BaseModel | None", self.env.get(name))
            if model is None:
                missing.append(name)
                continue
            if model._abstract or not model._auto:
                continue
            columns = cast(
                "dict[str, Any]",
                sql.table_columns(
                    cast("Cursor", self.env.cr), cast("str", model._table)
                ),
            )
            if not columns:
                missing.append(name)
                continue
            declared = cast("dict[str, Any]", model._fields)
            missing.extend(
                "%s.%s" % (name, field_name)
                for field_name, field in declared.items()
                if field.store and field.column_type and field_name not in columns
            )
        return missing

    # -- drift ------------------------------------------------------------

    def action_check_drift(self) -> bool:
        """Compare disk against what we last generated."""
        # Same `_inherit`-mixin cast as `_assert_builder_manager` above.
        cast("BuilderSecurityMixin", self)._assert_builder_user()
        for package in self:
            cast("BuilderPackageFile", package.file_ids)._refresh_disk_checksum()
            if not os.path.isdir(package.root_path or ""):
                package.state = "missing"
            elif any(f.drifted for f in cast("BuilderPackageFile", package.file_ids)):
                package.state = "drifted"
            elif package.state != "draft":
                package.state = "synced"
        return True

    def action_view_diff(self) -> dict[str, Any]:
        # Same `_inherit`-mixin cast as `_assert_builder_manager` above.
        cast("BuilderSecurityMixin", self)._assert_builder_user()
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "builder.package",
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
            "context": dict(
                cast("dict[str, Any]", self.env.context),
                builder_diff=gitrepo.diff(cast("str", self.root_path)),
            ),
        }

    # -- module lifecycle -------------------------------------------------

    def action_reload(self) -> Any:
        """Re-read the package from disk into the database.

        This is the file->DB direction, and the repair path for drift. The two
        cache_clear calls are not optional: Odoo caches manifests in an
        lru_cache that nothing ever invalidates, and never calls
        importlib.invalidate_caches(), so without them a package edited on disk
        stays invisible for the lifetime of the process.
        """
        # `_assert_builder_manager` lives on `builder.security.mixin`
        # (`_inherit`, not a Python base class -- Odoo's registry merges
        # it in at runtime, invisibly to pyright); same cast idiom as
        # `_demote_manual_metadata`'s own `Environment.cr`.
        cast("BuilderSecurityMixin", self)._assert_builder_manager()
        self.ensure_one()
        if self.reload_mode == "manual" and not self._can_install_in_place():
            # The same reason `_reload_now` refuses: the other workers (or
            # databases) would rebuild their registry against the Python
            # already in memory.
            raise UserError(self._manual_reload_reason())
        self._invalidate_module_caches()
        with self._applying():
            self._acquire_cron_lock()
            module = self._find_or_create_module()
            if module.state == "installed":
                action = module.button_immediate_upgrade()
            else:
                action = module.button_immediate_install()
        self._close_awaiting_restart()
        self.action_check_drift()
        # Returning Odoo's own {'tag': 'reload'} action matters: the registry
        # has just been rebuilt, so the browser is holding stale views and
        # menus until it reloads.
        return action

    @api.model
    def _invalidate_module_caches(self) -> None:
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

    def _find_or_create_module(self) -> IrModuleModule:
        self.ensure_one()
        Module = typed.model(self.env, IrModuleModule)
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

    def action_open_form(self) -> dict[str, Any]:
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "builder.package",
            "res_id": self.id,
            "view_mode": "form",
        }

    # -- xmlid allocation -------------------------------------------------

    @api.model
    def _flatten(
        self, records: BaseModel | Iterable[BaseModel | None] | None
    ) -> Iterator[BaseModel]:
        """Yield individual records from a recordset or a list of them.

        A single builder operation typically touches several models at once (a
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

    def _assign(
        self,
        records: BaseModel | Iterable[BaseModel] | None,
        suggested_name: str | None = None,
    ) -> list[str]:
        """Give ``records`` an xmlid in this package, creating it if needed.

        Everything the builder creates must be reachable by xmlid, otherwise it
        cannot be referenced from generated XML and cannot survive a reload.
        """
        self.ensure_one()
        Data = typed.model(self.env, IrModelData)
        serializers = self._serializer_env()
        result: list[str] = []
        for record in self._flatten(records):
            # `BaseModel._name` is declared `str | None` (`None` for an
            # abstract mixin with no table of its own) -- every real,
            # instantiated record flowing through here always has one, the
            # same invariant `typed.py`'s own docstring already states.
            record_name = cast("str", record._name)
            serializer = serializers._for_model(record_name)
            if serializer is not None and not serializer._ownable(record):
                # e.g. a model's magic columns, which arrive as part of
                # field_id but belong to Odoo, not to this package.
                continue
            existing = cast("dict[Any, str]", record.get_external_id()).get(record.id)
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
            # Same `@api.model_create_multi` passthrough-decorator gap as
            # `_sync_file_records`'s own `create()` call.
            vals: dict[str, Any] = {
                "module": self.name,
                "name": name,
                "model": record_name,
                "res_id": record.id,
                "noupdate": False,
            }
            Data.create(vals)  # pyright: ignore[reportArgumentType]
            result.append("%s.%s" % (self.name, name))
        return result

    @api.model
    def _suggest_xmlid(self, record: BaseModel) -> str:
        """Derive a readable xmlid stem from the record itself.

        Model, field and selection xmlids deliberately reuse Odoo's *own*
        reflection helpers rather than a convention of our own. That is what
        makes "graduate to code" safe: when a manual model becomes a Python
        class, `_reflect_models` / `_reflect_fields` / `_reflect_selections`
        re-register the very same xmlids, so they appear in
        ``pool.loaded_xmlids`` and `_process_end` does not treat the records as
        stale and delete them.
        """
        # Same `BaseModel._name` cast as `_assign`'s own `record_name`.
        record_name = cast("str", record._name)
        prefix = record_name.replace(".", "_")
        # A serializer may name its own records. Consulted first so per-model
        # knowledge lives with the serializer rather than accumulating here;
        # the branches below stay because they reuse Odoo's *own* reflection
        # helpers, which is what makes graduation safe.
        serializer = self._serializer_env()._for_model(record_name)
        if serializer is not None:
            suggested = serializer._suggest_xmlid(record)
            if suggested:
                return suggested
        # `model_xmlid`/`field_xmlid`/`selection_xmlid` (core, `ir_model.py`)
        # take fully unannotated parameters, so nothing below needs a value
        # cast for *their* sake -- only the attribute reads that get there
        # need one, `record` being declared the bare `BaseModel` this whole
        # method receives. They are reached as `ir_model_module` attributes
        # because a `from ... import` of them is itself a partially-unknown
        # name.
        if record_name == "ir.model":
            return ir_model_module.model_xmlid(
                "", cast("IrModel", record).model
            ).lstrip(".")
        if record_name == "ir.model.fields":
            record_fields = cast("IrModelFields", record)
            # `model_id` (`ir.model.fields`) is a plain-string-comodel
            # Many2one in core -- same `_Relational.__get__` gap as this
            # file's own `model_ids`/`file_ids`/`apply_ids`.
            field_model = cast("IrModel", record_fields.model_id)  # pyright: ignore[reportUnknownMemberType]
            return ir_model_module.field_xmlid(
                "", field_model.model, record_fields.name
            ).lstrip(".")
        if record_name == "ir.model.fields.selection":
            selection = cast("IrModelSelection", record)
            # Same gap as `model_id` above, one level up: `field_id`
            # (`ir.model.fields.selection`) is also a plain-string-comodel
            # Many2one.
            field = cast("IrModelFields", selection.field_id)  # pyright: ignore[reportUnknownMemberType]
            field_model = cast("IrModel", field.model_id)  # pyright: ignore[reportUnknownMemberType]
            return ir_model_module.selection_xmlid(
                "",
                field_model.model,
                field.name,
                selection.value,
            ).lstrip(".")
        if record_name == "ir.ui.view":
            view_name = cast("View", record).name
            return "view_%s" % (view_name or "").lower().replace(" ", "_").replace(
                ".", "_"
            )
        if record_name == "ir.model.access":
            access_name = cast("IrModelAccess", record).name
            return "access_%s" % (access_name or "").lower().replace(".", "_").replace(
                " ", "_"
            )
        label = getattr(record, "name", False) or record.display_name or str(record.id)
        slug = str(label).lower().replace(" ", "_").replace(".", "_")
        return "%s_%s" % (prefix, slug)

    def _unique_xmlid(self, name: str) -> str:
        self.ensure_one()
        Data = typed.model(self.env, IrModelData)
        candidate = name
        suffix = 1
        while Data.search_count([("module", "=", self.name), ("name", "=", candidate)]):
            suffix += 1
            candidate = "%s_%d" % (name, suffix)
        return candidate


class BuilderPackageFile(models.Model):
    _name = "builder.package.file"
    _description = "Builder Package File"
    _order = "path"

    # Annotated only so the declaration is not a partially-unknown name --
    # same read-side gap as `BuilderPackage`'s own `file_ids`/`model_ids`/
    # `apply_ids` above.
    package_id: fields.Many2one[BuilderPackage] = fields.Many2one(
        "builder.package", required=True, ondelete="cascade"
    )
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
    def _compute_drifted(self) -> None:
        for record in self:
            record.drifted = record.disk_checksum != record.generated_checksum

    def _refresh_disk_checksum(self) -> None:
        for record in self:
            # Same `cast()`-at-the-read-site idiom as `BuilderPackage`'s own
            # `model_ids`/`file_ids` -- `package_id` carries the identical
            # untyped-relation gap.
            package = cast("BuilderPackage", record.package_id)  # pyright: ignore[reportUnknownMemberType]
            full = os.path.join(package.root_path or "", cast("str", record.path))
            record.disk_checksum = checksum.hash_file(full) or False
