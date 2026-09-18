# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Generated ``i18n/<lang>.po`` files.

A ``translate=True`` column is jsonb -- ``{"en_US": "Deadline", "fr_FR":
"Échéance"}`` -- and an XML data file has room for exactly one of those. Odoo's
own answer is the one every addon uses: the data file carries the source term
and ``i18n/<lang>.po`` carries the rest. So does this.

Deliberately **not** ``odoo.tools.translate.PoFileWriter``, which is otherwise
exactly right. It stamps ``POT-Creation-Date`` and ``PO-Revision-Date`` with
``utcnow()``, so every save would rewrite every PO file with no change in
content -- churning the diff the project exists to keep readable, and breaking
the byte-identical render the round trip asserts. Everything else here follows
it, including using polib so the escaping and wrapping are the ones Odoo's own
importer round-trips.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Only for `merge_terms`'s own parameter annotation below -- `rows` is
    # never mutated, only iterated once, so `Iterable` is the honest,
    # minimal type rather than the concrete `list` every real caller
    # happens to pass (`studio_package.py`'s `rows[lang]`). `from __future__
    # import annotations` (above) means the annotation is never evaluated
    # at runtime, so this stays out of the real import list.
    from collections.abc import Iterable

# polib ships as one unstubbed ``polib.py`` -- no ``py.typed`` marker, no
# companion ``.pyi``, checked directly in this project's own site-packages --
# so pyright falls back to inferring from polib's own unannotated source
# rather than a real stub. That source builds every entry from a bare
# ``**kwargs`` (``_BaseEntry.__init__``), which taints ``msgid``/``msgstr``/
# ``msgctxt``/``occurrences``/``obsolete`` as partially unknown even on a
# freshly constructed instance, and ``pofile()`` routes through a parser
# whose own return type is built the same untyped way. Not something this
# file can fix from its own side -- the same "narrow, not blanket" vendor-gap
# precedent ``compat.py`` established for OCB's own bare ``Field`` generic,
# applied here at each of the handful of lines that actually touch a value
# polib handed back (never a config-level suppression: this is local to
# polib, not a tree-wide pattern the way ``reportPrivateUsage`` is).
import polib  # pyright: ignore[reportMissingTypeStubs]


@dataclass(frozen=True)
class Occurrence:
    """Where a term lives, in the form Odoo's importer resolves.

    ``kind`` is ``model`` for a whole-value field and ``model_terms`` for one
    Odoo splits into terms (an html body, a view arch). The importer branches on
    it -- ``model_terms`` matches the term inside the stored value rather than
    replacing the value outright -- so getting it wrong silently drops the
    translation on load.
    """

    kind: str
    model: str
    fname: str
    xmlid: str

    def render(self) -> str:
        return "%s:%s,%s:%s" % (self.kind, self.model, self.fname, self.xmlid)


@dataclass
class Term:
    msgid: str
    msgstr: str
    # `field(default_factory=list)` alone infers `list[Unknown]` here, not
    # `list[Occurrence]` -- a real pyright/dataclasses quirk, confirmed in
    # isolation, unrelated to polib's own untyped taint above. The
    # subscripted generic itself (`list[Occurrence]`) is a real, callable
    # factory at runtime (Python 3.9+) and produces the identical `[]`.
    occurrences: list[Occurrence] = field(default_factory=list[Occurrence])


# No timestamps, for the reason in the module docstring. The rest matches what
# Odoo writes, because its importer is what has to read this back.
METADATA = {
    "Project-Id-Version": "Odoo Server 18.0",
    "Report-Msgid-Bugs-To": "",
    "Last-Translator": "",
    "Language-Team": "",
    "MIME-Version": "1.0",
    "Content-Type": "text/plain; charset=UTF-8",
    "Content-Transfer-Encoding": "",
    "Plural-Forms": "",
}


def merge_po(
    existing: str | None, module: str, lang: str, terms: list[Term]
) -> str | None:
    """Fold generated terms into whatever is already in the file.

    Every other generated file is read before it is written -- the Python is
    spliced around a marker, the manifest and ``models/__init__.py`` keep the
    keys and imports somebody added by hand. The PO file was the exception, and
    it is the one generated file an external workflow legitimately owns:
    ``msgmerge``, a translation platform, a ``.pot``-derived entry for a string
    in code.

    The rule is the manifest's rule. A msgid this package emits is the
    database's to state, because that is where the studio's own users translate
    and the record is ours. A msgid it does not emit is left exactly as found.
    So a PO entry for a term we manage is refreshed on the next save, and
    everything else survives.
    """
    generated = render_po(module, lang, terms)
    if not existing:
        return generated

    try:
        before = polib.pofile(existing)  # pyright: ignore[reportUnknownVariableType]
    except OSError:  # pragma: no cover - polib raises this on malformed input
        return generated

    ours = {(entry.msgid, entry.msgctxt) for entry in polib.pofile(generated or "")}  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    kept = [e for e in before if not e.obsolete and (e.msgid, e.msgctxt) not in ours]  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    if not kept:
        return generated
    if generated is None:
        # Nothing of ours left to say, but somebody else's entries are still
        # in the file. Keep it rather than pruning it out from under them.
        merged = polib.pofile(existing)  # pyright: ignore[reportUnknownVariableType]
        merged[:] = kept
        return str(merged)  # pyright: ignore[reportUnknownArgumentType]

    merged = polib.pofile(generated)  # pyright: ignore[reportUnknownVariableType]
    for entry in kept:  # pyright: ignore[reportUnknownVariableType]
        merged.append(entry)
    merged.sort(key=lambda e: (e.msgid, e.msgstr))  # pyright: ignore[reportUnknownLambdaType, reportUnknownMemberType]
    return str(merged)  # pyright: ignore[reportUnknownArgumentType]


def render_po(module: str, lang: str, terms: list[Term]) -> str | None:
    """Render one language's PO file, or ``None`` when there is nothing to say.

    Returning None rather than an empty file matters: an addon with no
    translations should have no ``i18n/`` directory, and a file containing only
    a header is a file somebody has to wonder about.
    """
    terms = [t for t in terms if t.msgstr and t.msgstr != t.msgid]
    if not terms:
        return None

    po = polib.POFile()  # pyright: ignore[reportUnknownVariableType]
    po.header = (
        "Translation of Odoo Server.\n"
        "This file contains the translation of the following modules:\n"
        "\t* %s\n"
        "\n"
        "Entries below come from App Builder and are rewritten from the\n"
        "database on every save -- change those in Odoo, not here. Entries\n"
        "this package does not emit are left alone." % module
    )
    po.metadata = dict(METADATA, Language=lang)

    # Sorted, and one entry per source term with its occurrences gathered, so
    # the output depends on content rather than on database iteration order.
    for term in sorted(terms, key=lambda t: (t.msgid, t.msgstr)):
        entry = polib.POEntry(  # pyright: ignore[reportUnknownVariableType]
            msgid=term.msgid, msgstr=term.msgstr
        )
        entry.comment = "module: %s" % module
        # `polib`'s own real (unstubbed, see the `import polib` comment
        # above) implementation accepts `None` for "no line number" here --
        # confirmed by constructing one directly and rendering it, which
        # produces `#: <path>` with no trailing `:<line>` -- but its
        # inferred signature (built from an untyped `**kwargs`) resolves
        # `occurrences` to `list[tuple[str, str]]`, which rejects `None`
        # for the second element. A stub-vs-runtime gap local to this one
        # assignment, not a tree-wide pattern; kept as `None` rather than
        # substituted with `""` to avoid a real, if likely inconsequential,
        # value change for a type-adding pass.
        entry.occurrences = [  # pyright: ignore[reportAttributeAccessIssue]
            (occurrence, None)
            for occurrence in sorted({o.render() for o in term.occurrences})
        ]
        po.append(entry)
    return str(po)  # pyright: ignore[reportUnknownArgumentType]


def merge_terms(rows: Iterable[tuple[str, str, Occurrence]]) -> list[Term]:
    """Collapse ``(msgid, msgstr, Occurrence)`` rows into one Term per source.

    Two records with the same label and the same translation are one PO entry
    with two ``#:`` lines -- which is what Odoo's exporter does, and what makes
    a generated file look like a hand-written one.
    """
    merged: dict[tuple[str, str], Term] = {}
    for msgid, msgstr, occurrence in rows:
        if not msgid or not msgstr or msgstr == msgid:
            continue
        term = merged.get((msgid, msgstr))
        if term is None:
            term = merged[(msgid, msgstr)] = Term(msgid, msgstr)
        term.occurrences.append(occurrence)
    return list(merged.values())
