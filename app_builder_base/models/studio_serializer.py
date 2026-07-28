# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The record -> source-file emitter.

Odoo community has a complete XML *import* path (``odoo/tools/convert.py``) and
no export path at all, so this is the novel half of the project. Concrete
serializers subclass :class:`StudioSerializer` and are found by naming
convention -- ``studio.serializer.<model>`` -- which makes dispatch an O(1)
registry lookup rather than a scan.

Every design choice here serves one invariant, asserted in
``test_roundtrip.py``::

    load_from_files(serialize(db_state)) == db_state

If that holds, writing the DB and the file in the same transaction is an
optimisation rather than two competing sources of truth.
"""

import logging

from lxml import etree

from odoo import api, models
from odoo.exceptions import UserError
from odoo.tools.translate import _

from ..tools import xml_writer

_logger = logging.getLogger(__name__)

# Relative emission order between serializers. Referencing records must sort
# after what they reference, because a data file is loaded top to bottom.
SEQ_MODEL = 10
SEQ_FIELD = 20
SEQ_SELECTION = 30
SEQ_VIEW = 40
SEQ_SERVER_ACTION = 45
SEQ_ACT_WINDOW = 50
SEQ_ACT_WINDOW_VIEW = 55
SEQ_REPORT = 60
SEQ_MENU = 70
SEQ_RULE = 80
SEQ_AUTOMATION = 90
SEQ_ACCESS = 95
# Sequences are referenced by a create() override, not by an xmlid ref, so
# they only need to exist before records are made -- not before the views.
SEQ_SEQUENCE = 15


class StudioSerializer(models.AbstractModel):
    _name = "studio.serializer"
    _description = "Studio Serializer"

    # -- subclass contract ------------------------------------------------
    _studio_model = None  # target model name
    _studio_sequence = 100  # emission order across serializers
    _studio_fields = ()  # ordered list of significant fields
    _studio_dir = "data"  # subdirectory under the package root
    _studio_suffix = ""  # filename suffix before '.xml'
    _studio_format = "xml"  # 'xml' or 'csv'
    _studio_noupdate = False  # emit inside <data noupdate="1">

    # -- dispatch ---------------------------------------------------------

    @api.model
    def _for_model(self, model_name):
        """Return the serializer for ``model_name``, or ``None``."""
        return self.env.get("studio.serializer.%s" % model_name)

    @api.model
    def _ownable(self, record):
        """Whether a studio package may take ownership of ``record``.

        Defaults to True; subclasses narrow it. The important case is
        ``ir.model.fields``: a model's ``field_id`` includes the magic columns
        (id, create_uid, create_date, ...) which Odoo reflects with
        ``state='base'``. Emitting those as records would produce nonsense that
        a reload cannot reproduce, and Odoo would refuse to unlink them anyway
        ("This column contains module data and cannot be removed!").
        """
        return True

    @api.model
    def _serializable_models(self):
        """Every model the studio knows how to emit."""
        prefix = "studio.serializer."
        return sorted(
            name[len(prefix) :] for name in self.env.registry if name.startswith(prefix)
        )

    # -- xmlid helpers ----------------------------------------------------

    @api.model
    def _package_name(self):
        return self.env.context.get("studio_package")

    @api.model
    def _xmlid_of(self, record):
        """Full xmlid of ``record``, or ``False``."""
        if not record:
            return False
        return record.get_external_id().get(record.id) or False

    @api.model
    def _ref_of(self, record, source=None):
        """Reference string for ``record``, shortened when same-module.

        A referenced record with no xmlid is a hard error rather than a silently
        emitted integer id: raw ids are not portable across databases, and
        letting one through would break the round-trip invariant in a way that
        only shows up on a fresh install.
        """
        xmlid = self._xmlid_of(record)
        if not xmlid:
            # NB: no kwarg here may be called 'source' -- that is the name of
            # _()'s own first parameter and would collide.
            raise UserError(
                _(
                    "Cannot serialize %(origin)s: it references %(model)s "
                    "record #%(res_id)s, which has no external ID. Assign it to "
                    "a studio package first.",
                    origin=source or self._studio_model,
                    model=record._name,
                    res_id=record.id,
                )
            )
        package = self._package_name()
        module, _sep, name = xmlid.partition(".")
        if package and module == package:
            return name
        # Record the foreign module: the generated manifest must depend on
        # whatever it references, or installing the package into a fresh
        # database fails on an unresolvable ref.
        sink = self.env.context.get("studio_dep_sink")
        if sink is not None and module:
            sink.add(module)
        return xmlid

    # -- field emission ---------------------------------------------------

    @api.model
    def _should_skip(self, record, fname):
        """Skip a field whose value already equals its declared default.

        Comparing for *equality* rather than dropping every falsy value is what
        keeps the round-trip honest in both directions: omitting ``False`` for a
        field that defaults to ``True`` would silently flip it on reload, while
        emitting ``domain="[]"`` on every field is pure diff noise. Callable
        defaults are never skipped, since we cannot evaluate them
        deterministically.
        """
        field = record._fields[fname]
        value = record[fname]

        if field.type in ("many2one", "one2many", "many2many"):
            # Relational values are recordsets; comparing them to a default id
            # is meaningless, and an empty relation is always safe to omit.
            return not value

        default = field.default
        if default is None:
            return not value
        if callable(default):
            # Odoo wraps every scalar default in `lambda model: value`
            # (odoo/fields.py:511), so a declared default is *always* callable
            # and must be evaluated rather than skipped.
            try:
                default = default(record)
            except Exception:  # noqa: BLE001 - see below
                # Deliberately blind: a default is arbitrary user-reachable code
                # (including safe_eval'd manual defaults), and anything it raises
                # only means "we cannot prove this equals the default". Emitting
                # the value is the safe answer; letting the exception escape
                # would fail the whole write over one unserialisable field.
                return False
        return value == default

    @api.model
    def _field_node(self, record, fname):
        """Emit one ``<field>`` node, or ``None`` to omit it."""
        if fname not in record._fields:
            return None
        if self._should_skip(record, fname):
            return None

        field = record._fields[fname]
        value = record[fname]
        node = etree.Element("field")
        node.set("name", fname)
        ftype = field.type

        if ftype == "boolean":
            node.set("eval", "True" if value else "False")
        elif ftype in ("integer", "float", "monetary"):
            node.set("eval", repr(value))
        elif ftype == "many2one":
            node.set("ref", self._ref_of(value, source=self._studio_model))
        elif ftype in ("many2many", "one2many"):
            # Sorted, because recordset order follows the comodel's _order --
            # for res.groups that is a translated, non-unique column, so the
            # emitted order would vary between databases and between locales.
            refs = ", ".join(
                "ref(%r)" % ref
                for ref in sorted(
                    self._ref_of(rec, source=self._studio_model) for rec in value
                )
            )
            node.set("eval", "[(6, 0, [%s])]" % refs)
        elif ftype == "many2one_reference":
            # An integer holding another record's id, with a companion field
            # naming its model. There is no portable way to express that as a
            # ref, and emitting the integer would write one database's id into
            # a file loaded into another. Fail loudly rather than corrupt.
            raise UserError(
                _(
                    "Field %(field)s on %(model)s is a many2one_reference, whose "
                    "value is a raw database id. App Builder cannot serialize it "
                    "portably; set it per-environment instead of recording it in "
                    "the package.",
                    field=fname,
                    model=self._studio_model,
                )
            )
        elif ftype in ("date", "datetime"):
            node.text = str(value)
        elif ftype == "binary":
            node.text = (value or b"").decode("ascii", "ignore") if value else ""
        else:
            node.text = value if isinstance(value, str) else str(value)
        return node

    # -- record emission --------------------------------------------------

    @api.model
    def _record_id(self, record, xmlid):
        """The ``id`` attribute: bare name when the record is ours."""
        package = self._package_name()
        module, _sep, name = xmlid.partition(".")
        return name if package and module == package else xmlid

    @api.model
    def _serialize(self, record, xmlid):
        """Build the ``<record>`` node for ``record``."""
        node = etree.Element("record")
        node.set("id", self._record_id(record, xmlid))
        node.set("model", self._studio_model)
        for fname in self._studio_fields:
            child = self._field_node(record, fname)
            if child is not None:
                node.append(child)
        return node

    # -- file placement ---------------------------------------------------

    @api.model
    def _group_model(self, record):
        """Model name used to group records into files.

        Grouping by the *subject* model rather than by the record's own model is
        what makes generated output read like a hand-written addon: everything
        about ``x_project`` lands in ``models/x_project.xml`` and
        ``views/x_project_views.xml``.
        """
        return

    @api.model
    def _target_file(self, record):
        group = self._group_model(record)
        stem = (group or "misc").replace(".", "_")
        return "%s/%s%s.xml" % (self._studio_dir, stem, self._studio_suffix)

    # -- sorting ----------------------------------------------------------

    @api.model
    def _sort_key(self, record, xmlid):
        """Order within a file: by serializer, then xmlid. Never by id."""
        return (self._studio_sequence, xmlid)


class StudioXmlSerializerMixin(models.AbstractModel):
    """Helpers shared by serializers that emit an ``arch``-style XML field."""

    _name = "studio.serializer.mixin.arch"
    _description = "Studio Arch Serializer Mixin"

    @api.model
    def _arch_node(self, arch):
        """Build ``<field name="arch" type="xml">`` with parsed children."""
        node = etree.Element("field")
        node.set("name", "arch")
        node.set("type", "xml")
        parsed = xml_writer.parse_arch(arch)
        node.append(parsed)
        return node
