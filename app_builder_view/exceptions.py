# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Errors the view editor raises that a client has to tell apart.

A ``UserError`` carries a sentence for a person. ``BuilderStaleView`` carries
one too, but it is first a *signal*: the right response is to reload the view
silently and ask for the gesture again, not to show a warning about something
the user cannot act on. It has to be a class of its own because the RPC layer
serialises an exception's class name (``err.data.name``) and nothing else a
client could match on reliably -- the message is translated.
"""

from __future__ import annotations

from odoo.exceptions import UserError
from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__, default_lang="en_US")

# Lazy, because an exception has no ``env`` to translate with: the raise site
# resolves it through ``env._()``, and a bare ``BuilderStaleView()`` -- a test,
# a log line -- still reads as English rather than as a warning about a
# missing language.
STALE_VIEW_MESSAGE = _lt(
    "This view changed since it was loaded; it has been refreshed — please try again."
)


class BuilderStaleView(UserError):
    """The view changed between the client loading it and the edit arriving.

    Raised before anything is written, so the caller can retry against the
    refreshed view with nothing to undo. Two builders on one view, or a module
    update between two clicks, both land here rather than as an edit minted
    against a tree that no longer exists.
    """

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or str(STALE_VIEW_MESSAGE))


class BuilderConfirmRequired(UserError):
    """The edit is refused until the user has said yes to it.

    Removing a container removes everything in it, and a click on the wrong
    outline would take a dozen fields with it; so the first ask is refused
    with the count, and the client comes back with ``force`` once the user
    has confirmed. A class of its own for the same reason ``BuilderStaleView``
    is: the client has to tell "ask first" from "cannot", and matching a
    translated sentence is not telling. The count travels in ``context``,
    which the RPC layer serialises alongside the message, so a client can
    word its own question rather than re-parse this one.
    """

    def __init__(self, message: str, count: int = 0, fields: int = 0) -> None:
        super().__init__(message)
        self.context = {"confirm_required": True, "count": count, "fields": fields}
