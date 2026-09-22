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

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, cast

if TYPE_CHECKING:
    # Only used inside annotations (`from __future__ import annotations`
    # defers all of them to strings), never at runtime -- same bargain
    # `compat.py`'s own `TYPE_CHECKING`-guarded imports make.
    from collections.abc import Callable

    from odoo.fields import Field
    from odoo.models import BaseModel

# lxml ships no type stubs in this environment (a compiled extension with no
# `.pyi`/`py.typed` marker; `lxml-stubs`/`types-lxml` is not an installed
# dependency here), so pyright cannot resolve `etree` as an exported member
# of `lxml` at all -- confirmed directly, `from lxml import etree` alone
# reports both `reportMissingTypeStubs` (on `lxml`) and
# `reportAttributeAccessIssue` ("etree" is unknown import symbol, on
# `etree`). Ignored narrowly on each name rather than rewriting the import
# (e.g. `import lxml.etree as etree`), which trades this gap for a different
# one: ruff's own `PLR0402` auto-fixes that form straight back to `from lxml
# import etree` (`fix = true` project-wide), silently reintroducing the
# failure. Same pattern as `xml_writer.py`/`placement.py`/`canvas_stamp.py`.
from lxml import (  # pyright: ignore[reportMissingTypeStubs]
    etree,  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]
)

from odoo import api, models
from odoo.exceptions import UserError
from odoo.tools.translate import _

from ..tools import xml_writer

# `LxmlElement` (`tools/lxml_types.py`, shared with `xml_writer.py`,
# `placement.py` and `app_builder_view/tools/canvas_stamp.py`) is the real,
# checkable type for every element this module builds -- a <record>/<field>
# node. Used below to build the `Element` alias itself (a runtime
# assignment, not only an annotation), so -- unlike the `TYPE_CHECKING`-only
# names above -- it cannot be guarded the same way; same as `placement.py`'s
# own top-level `from .lxml_types import LxmlElement`.
from ..tools.lxml_types import LxmlElement

_logger = logging.getLogger(__name__)

Element: TypeAlias = LxmlElement

# `etree.Element` is the one constructor this module calls; grabbing it once,
# behind a single documented cast, keeps the "Unknown member of an unstubbed
# module" gap to two lines instead of a `# pyright: ignore` at each of the
# three call sites. Same idiom as `placement.py`'s own `_element`/
# `_sub_element` wrapper -- this file never calls `etree.SubElement`, so only
# the one wrapper is needed. The raw attribute access is unavoidably Unknown
# twice over -- pyright cannot name the member's own type, so it cannot name
# the *variable's* type either -- hence two rule codes on the one line that
# touches `etree` directly.
_element_raw = etree.Element  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
_element: Callable[..., Element] = cast("Callable[..., Element]", _element_raw)

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
# After the field it defaults (SEQ_FIELD), since field_id refs it.
SEQ_DEFAULT = 25
# After the server action it delegates to (SEQ_SERVER_ACTION), which it refs.
SEQ_CRON = 47


class StudioSerializer(models.AbstractModel):
    _name = "studio.serializer"
    _description = "Studio Serializer"

    # -- subclass contract ------------------------------------------------
    _studio_model: str | None = None  # target model name
    _studio_sequence: int = 100  # emission order across serializers
    _studio_fields: tuple[str, ...] = ()  # ordered list of significant fields
    _studio_ignored: tuple[str, ...] = ()  # stored fields knowingly *not* emitted
    _studio_refused: dict[str, str] = {}  # {field: why it cannot be written to source}
    _studio_dir: str = "data"  # subdirectory under the package root
    _studio_suffix: str = ""  # filename suffix before '.xml'
    _studio_format: Literal["xml", "csv"] = "xml"
    _studio_noupdate: bool = False  # emit inside <data noupdate="1">

    # -- dispatch ---------------------------------------------------------

    @api.model
    def _for_model(self, model_name: str) -> BaseModel | None:
        """Return the serializer for ``model_name``, or ``None``."""
        return self.env.get("studio.serializer.%s" % model_name)

    @api.model
    def _suggest_xmlid(self, record: BaseModel) -> str | None:
        """An xmlid stem for ``record``, or None to let the package decide."""
        return

    @api.model
    def _ownable(self, record: BaseModel) -> bool:
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
    def _serializable_models(self) -> list[str]:
        """Every model the studio knows how to emit."""
        prefix = "studio.serializer."
        return sorted(
            name[len(prefix) :] for name in self.env.registry if name.startswith(prefix)
        )

    # -- xmlid helpers ----------------------------------------------------

    @api.model
    def _package_name(self) -> str | None:
        return self.env.context.get("studio_package")

    @api.model
    def _xmlid_of(self, record: BaseModel) -> str | Literal[False]:
        """Full xmlid of ``record``, or ``False``."""
        if not record:
            return False
        return record.get_external_id().get(record.id) or False

    @api.model
    def _ref_of(self, record: BaseModel, source: str | None = None) -> str:
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
        #
        # The real caller (`studio_package.py`'s `_serializer_env`) builds
        # this as a plain `dep_sink = set()`, so `set[str] | None` is the
        # honest type for what `Context.get` returns here -- `Context` itself
        # is a generic Mapping-like object, and there is no way for pyright to
        # know the value type at this one key from the dict alone.
        sink: set[str] | None = self.env.context.get("studio_dep_sink")
        if sink is not None and module:
            sink.add(module)
        return xmlid

    # -- field emission ---------------------------------------------------

    @api.model
    def _should_skip(self, record: BaseModel, fname: str) -> bool:
        """Skip a field whose value already equals its declared default.

        Comparing for *equality* rather than dropping every falsy value is what
        keeps the round-trip honest in both directions: omitting ``False`` for a
        field that defaults to ``True`` would silently flip it on reload, while
        emitting ``domain="[]"`` on every field is pure diff noise. Callable
        defaults are never skipped, since we cannot evaluate them
        deterministically.
        """
        # `_fields` is OCB's own bare, unparameterized `dict[str, Field]` --
        # `Unknown` before this annotation applies, the same gap `compat.py`'s
        # `groups_field`/`manualfield.py`'s `default_currency_field` already
        # hit and fixed with this exact idiom.
        fields_: dict[str, Field[Any]] = record._fields  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        field = fields_[fname]
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
        if value == default:
            return True

        # Two ways a value can equal its default and not compare equal to it,
        # both of which used to emit something worse than noise.

        # An unset Selection or Char reads back as Python False while its
        # declared default is the empty string. `False == ''` is False, so the
        # comparison above let it through and the emitter wrote the *string*
        # "False" into the column -- which reloads as a value the selection does
        # not have. Emptiness is emptiness, whatever it is spelled as.
        if field.type != "boolean" and not value and not default:
            return True

        # A default may be declared in a different type from the one the column
        # stores: ir.actions.act_window.context declares `default={}` and stores
        # the string "{}", so every action carried `<field name="context">{}` in
        # its diff forever. Comparing through the field's own coercion is what
        # makes the two spellings agree.
        try:
            return value == field.convert_to_cache(default, record, validate=False)
        except (ValueError, TypeError):
            return False

    @api.model
    def _value_depends(self) -> dict[str, dict[str, str]]:
        """``{field: {value: module}}`` -- values that need a module installed.

        The manifest's ``depends`` is otherwise derived entirely from the
        xmlids emitted (``_ref_of``), which covers every *reference* and misses
        a whole class of dependency: a selection value contributed by another
        module. ``review_type="expression"`` comes from
        ``base_tier_validation_formula``, and a file carrying it loads into a
        database without that module as an invalid selection value -- silently,
        because nothing checks a selection on load.

        This is the third time in this project that a package has installed
        here and failed elsewhere for want of a derived dependency; see design
        finding 4 in DESIGN.md. Extended through ``super()``, so a bridge for an
        optional module can declare its own values.
        """
        return {}

    @api.model
    def _note_value_dependency(self, fname: str, value: Any) -> None:
        module = (self._value_depends().get(fname) or {}).get(value)
        # See `_ref_of`'s own comment on this same read.
        sink: set[str] | None = self.env.context.get("studio_dep_sink")
        if module and sink is not None:
            sink.add(module)

    @api.model
    def _translatable_fields(self, record: BaseModel) -> list[str]:
        """Emitted fields whose value carries more than the source term.

        A ``translate=True`` column is jsonb and the XML file has room for one
        string, so what is emitted is always ``en_US`` and the rest belongs in
        ``i18n/<lang>.po``. This says which fields that applies to; the package
        does the gathering.

        Derived from ``_studio_fields`` rather than listed, so a field added to
        an allowlist is covered the day it is added rather than the day someone
        notices. Overridden where the translated value lives somewhere other
        than the field emitted -- see the view serializer and ``arch_db``.
        """
        # Same `_fields` idiom as `_should_skip` above.
        fields_: dict[str, Field[Any]] = record._fields  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        return [
            fname
            for fname in self._studio_fields
            if getattr(fields_.get(fname), "translate", False)
        ]

    @api.model
    def _field_node(self, record: BaseModel, fname: str) -> Element | None:
        """Emit one ``<field>`` node, or ``None`` to omit it."""
        # Same `_fields` idiom as `_should_skip` above.
        fields_: dict[str, Field[Any]] = record._fields  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        if fname not in fields_:
            return None
        if self._should_skip(record, fname):
            return None
        self._note_value_dependency(fname, record[fname])

        field = fields_[fname]
        value = record[fname]
        node = _element("field")
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
        elif ftype == "reference":
            # Stores "model,id" as a string, and core's importer resolves a
            # plain ref= into exactly that (convert.py:405-407) -- so a
            # Reference is as portable as a many2one and needs no special
            # spelling. Worth stating because the neighbouring branch refuses
            # many2one_reference, which sounds similar and is not: that one is
            # a bare integer whose model lives in a separate column, with
            # nothing for an xmlid to attach to.
            node.set("ref", self._ref_of(value, source=self._studio_model))
        elif ftype == "many2one_reference":
            # A bare integer id, with a companion field naming the model it
            # belongs to. Emitting the integer would write one database's id
            # into a file loaded into another -- but the companion field is
            # exactly what makes the pair resolvable, so the record can be
            # found and emitted as an xmlid after all. ``ref()`` returns the id
            # on load (convert.py:217), which is what the column wants.
            #
            # Without a companion field there is genuinely nothing to look the
            # id up in, and that is the case worth refusing.
            node.set("eval", "ref(%r)" % self._reference_xmlid(record, fname))
        elif ftype in ("date", "datetime"):
            node.text = str(value)
        elif ftype == "binary":
            node.text = (value or b"").decode("ascii", "ignore") if value else ""
        else:
            node.text = value if isinstance(value, str) else str(value)
        return node

    @api.model
    def _reference_xmlid(
        self, record: BaseModel, fname: str, comodel: str | None = None
    ) -> str:
        """The xmlid behind a bare-integer reference.

        Resolving one needs the model it points at. Usually that is the field's
        declared ``model_field`` companion -- ``base.automation.trg_field_ref``
        reads its model from ``trg_field_ref_model_name`` -- and a caller that
        knows better passes ``comodel`` outright, which is how
        ``ir.actions.act_window.res_id`` resolves through its own ``res_model``
        despite being a plain Integer with no companion declared.

        The companion is often computed and unstored. That is fine: it is read
        here rather than emitted, because the model and the id travel together
        inside the xmlid.
        """
        if comodel is None:
            # Same `_fields` idiom as `_should_skip` above.
            fields_: dict[str, Field[Any]] = record._fields  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
            field = fields_[fname]
            # `Many2oneReference.model_field` (`odoo/fields.py`) is the only
            # `Field` subclass that declares this attribute -- `Field` itself
            # does not, hence `getattr` with a default rather than plain
            # attribute access, unchanged from the original.
            model_field: str | None = getattr(field, "model_field", None)
            comodel = record[model_field] if model_field else None
        if not comodel or comodel not in self.env:
            raise UserError(
                _(
                    "Field %(field)s on %(model)s holds a raw database id and "
                    "does not say which model it points at, so App Builder "
                    "cannot write it to source in a form that survives a fresh "
                    "install. Set it per environment instead of recording it "
                    "in the package.",
                    field=fname,
                    model=self._studio_model,
                )
            )
        target = self.env[comodel].browse(record[fname]).exists()
        if not target:
            raise UserError(
                _(
                    "Field %(field)s on %(model)s points at %(comodel)s record "
                    "#%(res_id)s, which no longer exists.",
                    field=fname,
                    model=self._studio_model,
                    comodel=comodel,
                    res_id=record[fname],
                )
            )
        return self._ref_of(target, source=self._studio_model)

    # -- record emission --------------------------------------------------

    @api.model
    def _record_id(self, record: BaseModel, xmlid: str) -> str:
        """The ``id`` attribute: bare name when the record is ours."""
        package = self._package_name()
        module, _sep, name = xmlid.partition(".")
        return name if package and module == package else xmlid

    @api.model
    def _serialize(self, record: BaseModel, xmlid: str) -> Element:
        """Build the ``<record>`` node for ``record``."""
        self._assert_complete(record)
        node = _element("record")
        node.set("id", self._record_id(record, xmlid))
        # `_studio_model` is declared `str | None` at the base (never set
        # standalone) and overridden with a literal string by every real
        # subclass before `_serialize` is ever reachable -- the same
        # "invariant the type system cannot see from here" shape as
        # `studio_security.py`'s own `cast("Users", self.env.user)`.
        node.set("model", cast("str", self._studio_model))
        for fname in self._emitted_field_names():
            child = self._field_node(record, fname)
            if child is not None:
                node.append(child)
        return node

    # -- the completeness guard -------------------------------------------
    #
    # ``_studio_fields`` is an allowlist, which is what keeps the output small
    # enough to review -- but nothing checked that what it leaves out was
    # actually safe to leave out. A field omitted from the list is dropped from
    # the generated source *silently*, and the package still reports clean, so
    # I3 (load_from_files(serialize(db)) == db) breaks in the one way no test
    # would notice. Everything below exists to turn that into a loud failure.
    #
    # Two exemptions are mechanical rather than judgements, and are applied
    # automatically so that ``_studio_ignored`` stays short enough to read:
    #
    #   * ``field.automatic`` -- the magic columns Odoo adds to every model
    #     (``models.py:278``): id, display_name, create_uid/date, write_uid/date.
    #   * ``not field.store`` -- a value derived on read. It has no independent
    #     existence to lose, and *reading* one here would trigger arbitrary
    #     compute code on the write path.
    #
    # What remains is a stored field carrying a user-settable value, so leaving
    # it out is a decision somebody has to make and write down.

    @api.model
    def _emitted_field_names(self) -> tuple[str, ...]:
        """Ordered field names this serializer writes out.

        A method rather than the tuple directly, for two reasons. A CSV
        serializer emits by column and answers differently. And a bridge addon
        for an optional module -- mail contributing ``template_id`` to
        ``ir.actions.server`` -- has to *add* to the list: setting the class
        attribute from a second module replaces it instead, so two bridges
        would silently clobber each other, while a ``super()`` chain composes.
        """
        return tuple(self._studio_fields)

    @api.model
    def _emitted_fields(self) -> set[str]:
        return set(self._emitted_field_names())

    @api.model
    def _ignored_fields(self) -> set[str]:
        """Stored fields knowingly not emitted. Extended the same way."""
        return set(self._studio_ignored)

    @api.model
    def _accountable_fields(self, record: BaseModel) -> set[str]:
        """Stored, non-magic fields -- the ones an omission could actually lose."""
        # Same `_fields` idiom as `_should_skip` above.
        fields_: dict[str, Field[Any]] = record._fields  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        return {
            name
            for name, field in fields_.items()
            if field.store and not field.automatic
        }

    @api.model
    def _classified_fields(self) -> set[str]:
        """Every field name this serializer has an answer for.

        Three answers, and every stored field must have one: emit it, ignore it
        because it cannot carry intent, or refuse it because it can but has no
        portable form. The static coverage test asserts the union is total,
        which is what catches a *newly installed module* contributing a field
        nobody has classified -- long before a user happens to set it.
        """
        return (
            self._emitted_fields() | self._ignored_fields() | set(self._studio_refused)
        )

    @api.model
    def _unclassified_fields(self, record: BaseModel) -> set[str]:
        """Stored fields nobody has decided about."""
        return self._accountable_fields(record) - self._classified_fields()

    @api.model
    def _assert_complete(self, record: BaseModel) -> Literal[True]:
        """Refuse to emit a record whose source would be missing something.

        Only fires when a value actually differs from its default. An
        unclassified field nobody ever set is a gap in our bookkeeping rather
        than data loss, and failing somebody's write over it would be
        obstructive -- reporting that case is the static test's job, not this
        one's.
        """
        # Read as superuser. The guard's whole job is to look at fields nobody
        # classified, and some of those are group-restricted --
        # ir.ui.view.visibility_password carries groups='base.group_system' and
        # raises AccessError on read. Failing somebody's write because the check
        # itself was not allowed to look would be absurd, and this reads data to
        # count it rather than to show it.
        record = record.sudo()
        # Same `_fields` idiom as `_should_skip` above.
        fields_: dict[str, Field[Any]] = record._fields  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        for fname, why in sorted(self._studio_refused.items()):
            if fname in fields_ and not self._should_skip(record, fname):
                raise UserError(
                    _(
                        "%(model)s record %(name)s sets %(field)s, which OCA "
                        "Studio cannot write to source: %(why)s",
                        model=self._studio_model,
                        name=record.display_name or record.id,
                        field=fname,
                        why=why,
                    )
                )
        lost = sorted(
            name
            for name in self._unclassified_fields(record)
            if not self._should_skip(record, name)
        )
        if not lost:
            return True
        raise UserError(
            _(
                "Cannot serialize %(model)s record %(name)s without losing "
                "data: %(fields)s %(verb)s a value the generated source would "
                "not carry, so reloading the package would not reproduce this "
                "record.\n\nThis is a gap in App Builder rather than a mistake "
                "you made. The field needs adding to the serializer's "
                "_studio_fields, or to _studio_ignored with the reason it "
                "cannot matter.",
                model=self._studio_model,
                name=record.display_name or record.id,
                fields=", ".join(lost),
                verb=_("has") if len(lost) == 1 else _("have"),
            )
        )

    # -- file placement ---------------------------------------------------

    @api.model
    def _group_model(self, record: BaseModel) -> str | None:
        """Model name used to group records into files.

        Grouping by the *subject* model rather than by the record's own model is
        what makes generated output read like a hand-written addon: everything
        about ``x_project`` lands in ``models/x_project.xml`` and
        ``views/x_project_views.xml``.
        """
        return

    @api.model
    def _target_file(self, record: BaseModel) -> str:
        group = self._group_model(record)
        stem = (group or "misc").replace(".", "_")
        return "%s/%s%s.xml" % (self._studio_dir, stem, self._studio_suffix)

    # -- sorting ----------------------------------------------------------

    @api.model
    def _sort_key(self, record: BaseModel, xmlid: str) -> tuple[int, str]:
        """Order within a file: by serializer, then xmlid. Never by id."""
        return (self._studio_sequence, xmlid)


class StudioXmlSerializerMixin(models.AbstractModel):
    """Helpers shared by serializers that emit an ``arch``-style XML field."""

    _name = "studio.serializer.mixin.arch"
    _description = "Studio Arch Serializer Mixin"

    @api.model
    def _arch_node(self, arch: str | bytes) -> Element:
        """Build ``<field name="arch" type="xml">`` with parsed children."""
        node = _element("field")
        node.set("name", "arch")
        node.set("type", "xml")
        parsed = xml_writer.parse_arch(arch)
        node.append(parsed)
        return node
