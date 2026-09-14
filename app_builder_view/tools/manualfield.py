# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""From what the picker says to what ``ir.model.fields`` takes.

The picker speaks the spec's language -- ``comodel``, ``inverse_name``,
``ondelete``, a ``selection`` of ``{value, label, sequence}`` -- because
that is what a Python-owned model is written from, and one vocabulary for
both paths is what lets the same tile drop on either kind of model. A live
field is not a spec: it is a row of ``ir.model.fields``, whose columns are
called ``relation``, ``relation_field``, ``on_delete`` and whose values live
in ``ir.model.fields.selection`` rows. This module is the translation, and
nothing else: it builds the ``create`` payload and refuses, in a sentence,
what core would refuse with a traceback.

The refusals mirror core's own checks (``ir_model.py``: the relation must
exist, a one2many needs a many2one back, an amount needs a currency field,
a related path must end in a field of the declared type) and run *before*
the row is written. That is not only for the nicer message: creating a
manual field rebuilds the registry in the same transaction, and a bad
``related`` is not refused there but logged and skipped, which yields a row
with no field behind it.

Not quite pure -- the checks read the registry through ``env`` -- but they
read only, and a ``UserError`` is the only way out that is not a payload.
Messages are translated through ``env._`` for the same reason: a module
function has no ``self`` for the translator to find a language on.
"""

from odoo.exceptions import UserError

from odoo.addons.app_builder_base.tools import modelspec

# What a manual row can be. Everything the picker offers, less what has no
# ``ir.model.fields`` column to hold it: ``properties`` needs a definition
# record, ``json`` has no widget, and both are already disabled entries.
SUPPORTED_TTYPES = frozenset(
    {
        "char",
        "text",
        "html",
        "boolean",
        "integer",
        "float",
        "monetary",
        "date",
        "datetime",
        "selection",
        "reference",
        "binary",
        "many2one",
        "one2many",
        "many2many",
    }
)

# Spec attributes that are class-level facts with no manual-field column,
# or that the live path deliberately does not offer. Refused by name rather
# than dropped: a default the user typed and never saw applied is a bug
# report, not a convenience.
UNSUPPORTED_LIVE = {
    "default": "a default value is a class attribute; set it on the field afterwards",
    "compute": "a computed field is written through the composer",
    "compute_body": "a computed field is written through the composer",
    "digits": "decimal precision is a class attribute",
}

# Types whose values can be translated; ``translate`` on anything else is
# refused by core's own field setup.
TRANSLATABLE = frozenset({"char", "text", "html"})

# Where a monetary field looks for its currency when nobody named one --
# the same two names core's ``_check_currency_field`` falls back to.
CURRENCY_FALLBACKS = ("currency_id", "x_currency_id")


def field_name_for(label, prefix="x_"):
    """``x_delivery_date`` for "Delivery date": the name a live field gets
    when the user gave only a label.

    The ``x_`` prefix is what Odoo requires of a manual field; the draft
    path passes an empty prefix, since a class attribute has no such rule
    and a clean name is the whole point of that path.
    """
    slug = "".join(c if c.isalnum() else "_" for c in (label or "").lower())
    parts = [part for part in slug.split("_") if part]
    name = "_".join(parts)
    if name and name[0].isdigit():
        name = "_" + name
    return "%s%s" % (prefix, name)


def unique_name(name, taken):
    """``name`` as it is when nothing in ``taken`` has it, else the first
    of ``name_2``, ``name_3``, ... that is free.

    For a name derived from a label the user has not typed: the second
    Text tile dropped before the first was renamed is the same "New Text",
    and a refusal for that would be blaming the user for a name they did
    not choose. The suffix is the one the composer's popover gives.
    """
    if name not in taken:
        return name
    counter = 2
    while "%s_%d" % (name, counter) in taken:
        counter += 1
    return "%s_%d" % (name, counter)


def needs_dialog(entry_key, has_default_currency=False):
    """Whether a tile of ``entry_key`` has to ask before it can create.

    A scalar has nothing to ask: it is created as "New Text" and the label
    row takes the cursor. A link needs to know what it links to, a
    selection needs its values -- unless the entry brings them, as
    Priority does -- a related field needs its path, and an amount needs a
    currency field when the model has none of the two names core falls
    back to.
    """
    entry = modelspec.field_type_for(entry_key)
    if entry is None:
        return False
    if entry.picker_key == "related":
        return True
    if entry.ttype in modelspec.RELATIONAL:
        return True
    if entry.ttype in ("selection", "reference"):
        return not any(name == "selection" for name, _preset in entry.preset)
    if entry.ttype == "monetary":
        return not has_default_currency
    return False


def creatable_live(entry_key):
    """Whether a tile of ``entry_key`` can become a manual field at all."""
    entry = modelspec.field_type_for(entry_key)
    if entry is None or not entry.supported:
        return False
    # A related field's placeholder type is `char`; what it really becomes
    # is decided by the path, and every supported end type is a live type.
    return entry.picker_key == "related" or entry.ttype in SUPPORTED_TTYPES


def default_currency_field(model_name, env):
    """The currency field core would fall back to on ``model_name``, or ``""``."""
    if model_name not in env:
        return ""
    fields_ = env[model_name]._fields
    for name in CURRENCY_FALLBACKS:
        field = fields_.get(name)
        if (
            field is not None
            and field.type == "many2one"
            and field.comodel_name == "res.currency"
        ):
            return name
    return ""


def ir_model_fields_vals(values, model_name, env):
    """The ``ir.model.fields.create`` payload for a spec-shaped ``values``.

    ``values`` has been through ``modelspec.apply_preset`` already, so its
    ``ttype`` is a real type and a Priority arrives with its four values.
    Raises ``UserError`` for anything core would refuse, before the row
    exists.
    """
    values = dict(values or {})
    for key, why in UNSUPPORTED_LIVE.items():
        if values.get(key):
            raise UserError(
                env._(
                    "'%(key)s' cannot be set on a field created here: %(why)s.",
                    key=key,
                    why=why,
                )
            )
    if model_name not in env:
        raise UserError(env._("Unknown model '%s'.", model_name))

    label = (values.get("field_description") or values.get("string") or "").strip()
    if not label:
        raise UserError(env._("The field needs a label."))
    name = values.get("name") or field_name_for(label)
    vals = {
        "name": _checked_name(name, model_name, env),
        "field_description": label,
        "ttype": values.get("ttype") or "char",
        "model_id": env["ir.model"]._get(model_name).id,
    }
    relation = values.get("comodel") or values.get("relation") or ""
    related = (values.get("related") or "").strip()
    if related:
        # The picker's placeholder type gives way to what the path ends at:
        # core's `_check_related` demands the end field's type and comodel,
        # and a related field is not stored unless somebody says so -- a
        # stored copy of another record's value is a column that goes stale.
        end = _related_end(env, model_name, related)
        vals["ttype"] = end.ttype
        relation = end.relation or ""
        vals["related"] = related
        vals["store"] = bool(values.get("store"))
    ttype = vals["ttype"]
    if ttype not in SUPPORTED_TTYPES:
        raise UserError(
            env._("A field of type '%s' cannot be created on a live model.", ttype)
        )
    vals.update(_relational_vals(values, model_name, ttype, relation, related, env))
    if ttype == "monetary":
        vals["currency_field"] = _check_currency(
            env, model_name, values.get("currency_field") or ""
        )
    if ttype in ("selection", "reference") and not related:
        vals["selection_ids"] = [
            (0, 0, row) for row in selection_rows(values.get("selection"), env)
        ]
    vals.update(_flag_vals(values, ttype, env))
    return vals


def _checked_name(name, model_name, env):
    if not name.startswith("x_"):
        raise UserError(env._("A custom field name must start with 'x_'."))
    if not name.isidentifier():
        raise UserError(env._("'%s' is not a usable field name.", name))
    if name in env[model_name]._fields:
        raise UserError(env._("%s already has a field called %s.", model_name, name))
    return name


def _relational_vals(values, model_name, ttype, relation, related, env):
    """``relation``, ``relation_field``, ``on_delete`` and the many2many
    table names, checked the way core's ``create`` checks them."""
    if ttype not in modelspec.RELATIONAL:
        return {}
    if not relation:
        raise UserError(env._("Choose the model this field should link to."))
    if relation not in env or not env["ir.model"]._get_id(relation):
        raise UserError(env._("There is no model called %s to link to.", relation))
    vals = {"relation": relation}
    if ttype == "many2one":
        # Without this Odoo defaults to 'set null', which is right often
        # enough, but saying it makes the generated source explicit.
        vals["on_delete"] = values.get("ondelete") or "set null"
    if ttype == "one2many" and not related:
        inverse = values.get("inverse_name") or values.get("relation_field") or ""
        _check_inverse(env, model_name, relation, inverse)
        vals["relation_field"] = inverse
    if ttype == "many2many":
        for key in ("relation_table", "column1", "column2"):
            if values.get(key):
                vals[key] = values[key]
    if values.get("domain"):
        domain = values["domain"]
        vals["domain"] = domain if isinstance(domain, str) else str(domain)
    return vals


def _flag_vals(values, ttype, env):
    """The booleans and the small extras, only where they were stated.

    The spec says ``copy``, as the class attribute is spelt; the row's
    column is ``copied``, and a payload that used the spec's word would be
    refused by ``create`` with a traceback rather than a sentence.
    """
    vals = {}
    for key in ("required", "readonly", "index"):
        if values.get(key) is not None:
            vals[key] = bool(values[key])
    if values.get("copy") is not None:
        vals["copied"] = bool(values["copy"])
    if values.get("translate") is not None:
        if values["translate"] and ttype not in TRANSLATABLE:
            raise UserError(env._("Only text fields can be translated."))
        vals["translate"] = bool(values["translate"])
    if values.get("help"):
        vals["help"] = values["help"]
    if ttype == "char" and values.get("size"):
        vals["size"] = int(values["size"])
    return vals


def selection_rows(entries, env):
    """``ir.model.fields.selection`` rows for a list of ``{value, label,
    sequence}``, checked the way the row's own constraints would check them
    -- a value and a label each, no value twice -- and never empty, since
    ``fields.Selection()`` with no values raises at registry setup rather
    than here."""
    rows = []
    seen = set()
    for position, entry in enumerate(entries or ()):
        entry = dict(entry or {})
        value = str(entry.get("value") or "").strip()
        label = str(entry.get("label") or entry.get("name") or "").strip()
        if not value or not label:
            raise UserError(env._("Every selection value needs a value and a label."))
        if value in seen:
            raise UserError(env._("The selection value '%s' is listed twice.", value))
        seen.add(value)
        sequence = entry.get("sequence")
        rows.append(
            {
                "value": value,
                "name": label,
                "sequence": int(sequence) if sequence is not None else position,
            }
        )
    if not rows:
        raise UserError(env._("A selection needs at least one value."))
    return rows


def _check_inverse(env, model_name, relation, inverse):
    """A one2many needs a many2one back, and it has to point *here*.

    Core only checks that a many2one of that name exists on the comodel;
    one aimed at another model would load and then show nothing, which is
    the kind of failure a user cannot read.
    """
    if not inverse:
        raise UserError(
            env._(
                "A related list needs the field on %s that links back to this model.",
                relation,
            )
        )
    field = env[relation]._fields.get(inverse) if relation in env else None
    if field is None or field.type != "many2one":
        raise UserError(
            env._(
                "%(relation)s has no link field called %(inverse)s. Add a "
                "'Link to one record' there first, then pick it here.",
                relation=relation,
                inverse=inverse,
            )
        )
    if field.comodel_name != model_name:
        raise UserError(
            env._(
                "%(relation)s.%(inverse)s links to %(other)s, not to %(model)s.",
                relation=relation,
                inverse=inverse,
                other=field.comodel_name,
                model=model_name,
            )
        )


def _check_currency(env, model_name, currency_field):
    """The currency field an amount will use, named explicitly.

    Core accepts an empty ``currency_field`` when the model has a
    ``currency_id``; the name is written out anyway so the generated
    source says which field it is rather than relying on the reader to
    know the fallback rule.
    """
    name = currency_field or default_currency_field(model_name, env)
    field = env[model_name]._fields.get(name) if name else None
    if field is None:
        raise UserError(
            env._(
                "An amount needs a currency field on %s. Add a 'Link to one "
                "record' pointing at res.currency first.",
                model_name,
            )
        )
    if field.type != "many2one" or field.comodel_name != "res.currency":
        raise UserError(env._("%s is not a link to res.currency.", name))
    return name


def _related_end(env, model_name, path):
    """The ``ir.model.fields`` row a dotted ``path`` ends at, walked the way
    core's ``_related_field`` walks it -- on the reflected rows, since those
    are what the constraint compares against."""
    steps = [part for part in path.split(".") if part]
    if not steps:
        raise UserError(env._("Choose a field to follow."))
    field = None
    for index, step in enumerate(steps):
        field = env["ir.model.fields"]._get(model_name, step)
        if not field:
            raise UserError(
                env._(
                    "%(step)s is not a field of %(model)s.",
                    step=step,
                    model=model_name,
                )
            )
        if index < len(steps) - 1:
            if not field.relation:
                raise UserError(
                    env._("%s is not a relation, so nothing can follow it.", step)
                )
            model_name = field.relation
    return field
