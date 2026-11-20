# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""One guard, called first in every builder method reachable over RPC.

``ir.model.access`` does not protect this product. The builders are
``AbstractModel``s, which ACL rows do not apply to at all, and
``/web/dataset/call_kw`` is ``auth="user"`` and performs no access check of its
own -- ``get_public_method`` (``odoo/service/model.py``) rejects only
underscore-prefixed and ``@api.private`` methods. So every public method on a
builder model is callable by any authenticated user, including a portal one,
unless it says otherwise here.

That matters more than it would in an ordinary addon: these methods write
Python and XML into a directory on ``addons_path`` and reload modules, so an
unguarded entry point is arbitrary code execution as the Odoo process user, not
merely a data leak.

``group_builder_user`` and ``group_builder_manager`` both live in
``base.module_category_hidden``, so neither can be granted through the Users
form. The only way into them is ``base.group_system``, which implies the
manager group -- which is why checking the manager group *is* "settings
administrators only", while leaving the two-tier split available if the groups
are ever surfaced.

Two things narrow that further, and both are deliberate.

**Writing code is opt-in, per server process.** Stock Odoo does not let a
database administrator run arbitrary Python: server actions go through
``safe_eval`` and ``base_import_module`` refuses Python files. This product
does, by design, so the group alone is not allowed to be the whole gate.
``code_write_enabled()`` reads a switch that lives *outside* the database --
``APP_BUILDER_ENABLE_WRITE`` in the process environment, or
``app_builder_enable_write`` in ``odoo.conf`` -- and that defaults to off.
Nobody can flip it from the UI, an RPC call or a stolen admin session: it
takes the access that already amounts to a shell. With it off the manager
guard refuses every caller, the superuser included, and every package
reports itself read-only. See ``SECURITY.md``.

**``sudo()`` is not a way in.** Only the superuser *itself* (uid 1: module
install, data loading, crons, the test bootstrap) passes without a group.
``env.su`` set by a ``sudo()`` on behalf of an ordinary user does not: some
other addon creating an ``ir.ui.view`` under ``sudo()`` while forwarding the
client's context (``builder_package_id`` is a context key, and context is
client-controlled on ``call_kw``) would otherwise be a confused deputy that
writes into a package's source tree for a user who was never a builder.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal, cast

from odoo import SUPERUSER_ID, api, models
from odoo.exceptions import AccessError
from odoo.tools import config

from ..tools.i18n import _

if TYPE_CHECKING:
    # Only for the `cast` below; with `from __future__ import annotations`
    # nothing here needs it at runtime.
    from odoo.addons.base.models.res_users import Users

BUILDER_USER = "app_builder_base.group_builder_user"
BUILDER_MANAGER = "app_builder_base.group_builder_manager"

#: The process environment variable that turns code writing on.
WRITE_ENV_VAR = "APP_BUILDER_ENABLE_WRITE"
#: The same switch as an ``[options]`` key of ``odoo.conf``.
WRITE_CONFIG_KEY = "app_builder_enable_write"

_TRUE = frozenset({"1", "true", "yes", "on"})


def code_write_enabled() -> bool:
    """Has the operator of this *server* allowed the builder to write code?

    Read on every call rather than cached at import: it is two dictionary
    lookups, and a test (or an operator's ``odoo shell``) that changes the
    environment must see the change. The environment variable, when it is
    set at all, wins over ``odoo.conf`` -- so ``APP_BUILDER_ENABLE_WRITE=0``
    turns writing off on a host whose shared config file turns it on.

    Deliberately not an ``ir.config_parameter``: a system parameter is a row
    a Settings administrator can edit, which is exactly the account this
    switch exists to not trust on its own.
    """
    env = os.environ.get(WRITE_ENV_VAR)
    # `config.get` is unannotated; `odoo.conf` parsing leaves a real `bool`
    # for `True`/`False` and the raw string for anything else.
    raw: object = (
        env if env and env.strip() else cast("object", config.get(WRITE_CONFIG_KEY))
    )
    if isinstance(raw, bool):
        return raw
    return str(raw or "").strip().lower() in _TRUE


class BuilderSecurityMixin(models.AbstractModel):
    _name = "builder.security.mixin"
    _description = "Builder Access Guard"

    @api.model
    def _assert_builder_user(self) -> Literal[True]:
        """Guard for methods that only read builder metadata."""
        return self._assert_builder_group(
            BUILDER_USER,
            _("Reading builder metadata is restricted to Builder Users."),
        )

    @api.model
    def _assert_builder_manager(self) -> Literal[True]:
        """Guard for anything that writes a record, a file, or the registry.

        The group first, so somebody who is not a builder at all learns
        nothing about how the server is configured; then the server-side
        switch, which no group membership -- and no superuser -- overrides.
        """
        self._assert_builder_group(
            BUILDER_MANAGER,
            _(
                "Building with the builder is restricted to Builder "
                "Administrators, because it writes source files into the "
                "addons path and reloads modules."
            ),
        )
        reason = self._builder_write_disabled_reason()
        if reason:
            raise AccessError(reason)
        return True

    @api.model
    def _builder_write_enabled(self) -> bool:
        """``code_write_enabled()``, reachable from a recordset."""
        return code_write_enabled()

    @api.model
    def _builder_write_disabled_reason(self) -> str:
        """Why nothing can be built here, or ``""`` when something can.

        One sentence, shown wherever the builder explains that it is
        read-only, so the person reading it knows it is a decision made on
        the server and not a permission they are missing.
        """
        if code_write_enabled():
            return ""
        return _(
            "The builder is read-only on this server: writing source code "
            "has not been enabled. It is switched on outside the database, "
            "by setting %(env)s=1 in the server's environment or "
            "%(key)s = True in odoo.conf, and should only be switched on "
            "where every Settings administrator is trusted with shell "
            "access.",
            env=WRITE_ENV_VAR,
            key=WRITE_CONFIG_KEY,
        )

    @api.model
    def _assert_builder_group(self, group: str, message: str) -> Literal[True]:
        # The superuser itself is the trusted-internal-code path: module
        # install, data loading, crons and the test bootstrap all run as
        # uid 1 and must not be locked out of their own machinery. That is
        # narrower than `env.su`, which a `sudo()` on behalf of any user
        # also sets -- see the module docstring. RPC is not uid 1: the
        # superuser's own account is archived and cannot log in.
        #
        # `Environment.user` (`odoo/api.py`) carries no return annotation of
        # its own; pyright infers one from its body (`self(su=True)['res
        # .users'].browse(self.uid)`), which bottoms out at the bare
        # `BaseModel` every `Environment.__getitem__` call returns -- the
        # same untyped hole `typed.model()` exists for elsewhere, but that
        # helper turns a model *name* into an empty recordset handle
        # (`env[cls._name]`), not an already-obtained record like this one,
        # so a direct, narrow `cast` is the honest fix here instead.
        if self.env.uid == SUPERUSER_ID:
            return True
        if cast("Users", self.env.user).has_group(group):
            return True
        raise AccessError(message)
