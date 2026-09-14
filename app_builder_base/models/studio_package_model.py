# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Which models a package defines, and where their definition lives.

Replaces the comma-joined ``graduated_models`` char field, which could not
carry the per-model state this needs and was doing double duty as both an
ownership registry and a rendering flag.

Three sources, and the difference between them decides what gets written:

``python``
    The package defines the model as a real class in ``models/<m>.py``. That
    file is the definition; ``ir.model`` and ``ir.model.fields`` are reflection
    artefacts of it. Nothing is emitted as XML for it.
``xml``
    The model is ``state='manual'`` metadata, emitted as ``<record>`` data.
    This is what a legacy package looks like before adoption, and what a
    manual field on a *core* model always looks like.
``frozen``
    The file exists but the builder could not parse it, so it must never be
    rewritten. Entered on evidence, not by default -- and it is the one state
    where the builder shows the model read-only.
"""

import logging
import os

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..tools import pycodegen, pyparse

_logger = logging.getLogger(__name__)


class StudioPackageModel(models.Model):
    _name = "studio.package.model"
    _description = "Studio Package Model"
    _order = "model"

    package_id = fields.Many2one(
        "studio.package", required=True, ondelete="cascade", index=True
    )
    model = fields.Char(
        required=True,
        index=True,
        help="Technical model name, e.g. workshop.project.",
    )
    extends = fields.Boolean(
        string="Extends an existing model",
        help="The class adds to a model another module declares, rather than "
        "declaring one. It renders as _inherit with no _name.",
    )
    source = fields.Selection(
        [
            ("python", "Python class"),
            ("xml", "Data records"),
            ("frozen", "Code-owned (unparseable)"),
        ],
        required=True,
        default="python",
    )
    parse_error = fields.Char(
        readonly=True,
        help="Why the builder had to stop rewriting this file.",
    )
    python_path = fields.Char(compute="_compute_python_path")

    _sql_constraints = [
        (
            "model_uniq_per_package",
            "unique(package_id, model)",
            "A package defines each model at most once.",
        ),
    ]

    @api.depends("model")
    def _compute_python_path(self):
        for record in self:
            record.python_path = "models/%s" % pycodegen.module_file_for(record.model)

    # -- the spec ---------------------------------------------------------

    def _current_spec(self):
        """The authoritative spec: parsed from disk, never from ``ir.model``.

        Returns ``None`` when there is nothing to render -- either the file is
        gone, or it is code-owned and must be left exactly as it is.
        """
        self.ensure_one()
        if self.source != "python":
            return None
        source = self.package_id._read_source(self.python_path)
        if source is None:
            return None
        try:
            return pyparse.parse_model(source)
        except pyparse.UnsupportedConstruct as err:
            # Freeze rather than guess. Rewriting a file we cannot fully read
            # would delete whatever we failed to understand, silently, on the
            # next save.
            self.write({"source": "frozen", "parse_error": str(err)})
            _logger.info(
                "Package %s: %s is now code-owned (%s)",
                self.package_id.name,
                self.model,
                err,
            )
            return None

    def action_compose(self):
        """Open the builder on this model.

        The builder is the console, and ``app_builder_view`` ships it, so the
        override that returns it lives there: the engine cannot name a
        client action it does not carry. What the engine can do is say so
        rather than fail obscurely when nothing has overridden this -- a
        shell caller, or a database with the view addon missing.
        """
        self.ensure_one()
        raise UserError(
            _(
                "Composing a model needs the studio console; install "
                "app_builder_view, which app_builder_model depends on."
            )
        )

    def action_retry_parse(self):
        """Give a frozen model another chance after the file was fixed."""
        for record in self.filtered(lambda r: r.source == "frozen"):
            source = record.package_id._read_source(record.python_path)
            if source is None:
                continue
            try:
                pyparse.parse_model(source)
            except pyparse.UnsupportedConstruct as err:
                record.parse_error = str(err)
                continue
            record.write({"source": "python", "parse_error": False})
        return True

    # -- lookups ----------------------------------------------------------

    @api.model
    def _is_python_owned(self, model_name):
        """Whether any package *declares* ``model_name`` as a Python class.

        Used by the serializers: a row still marked ``state='manual'`` for such
        a model is a reconciliation artefact, not a definition, and emitting it
        would produce the competing-definition state that ``_add_manual_models``
        turns into a reap.

        Declares, not touches. An *extension* -- `_inherit` with no `_name` --
        adds to a model somebody else owns, and a manual `x_` field on that
        model is still ordinary metadata that belongs in XML. Counting an
        extension here would suppress it and lose the field.
        """
        if not model_name:
            return False
        return bool(
            self.sudo().search_count(
                [
                    ("model", "=", model_name),
                    ("source", "in", ("python", "frozen")),
                    ("extends", "=", False),
                ],
                limit=1,
            )
        )

    @api.model
    def _adopt(self, package, model_name, source="python", extends=False):
        """Record ownership, or return the existing row."""
        existing = self.search(
            [("package_id", "=", package.id), ("model", "=", model_name)], limit=1
        )
        if existing:
            return existing
        return self.create(
            {
                "package_id": package.id,
                "model": model_name,
                "source": source,
                "extends": extends,
            }
        )

    def unlink(self):
        for record in self:
            if record.source == "python" and record.package_id.writable:
                full = os.path.join(
                    record.package_id.root_path or "", record.python_path
                )
                if os.path.isfile(full):
                    raise UserError(
                        _(
                            "%(model)s is still defined by %(path)s. Remove the "
                            "file first, or the next reload would bring the "
                            "model straight back.",
                            model=record.model,
                            path=record.python_path,
                        )
                    )
        return super().unlink()
