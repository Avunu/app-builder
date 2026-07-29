# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""One guard, called first in every studio method reachable over RPC.

``ir.model.access`` does not protect this product. The builders are
``AbstractModel``s, which ACL rows do not apply to at all, and
``/web/dataset/call_kw`` is ``auth="user"`` and performs no access check of its
own -- ``get_public_method`` (``odoo/service/model.py``) rejects only
underscore-prefixed and ``@api.private`` methods. So every public method on a
studio model is callable by any authenticated user, including a portal one,
unless it says otherwise here.

That matters more than it would in an ordinary addon: these methods write
Python and XML into a directory on ``addons_path`` and reload modules, so an
unguarded entry point is arbitrary code execution as the Odoo process user, not
merely a data leak.

``group_studio_user`` and ``group_studio_manager`` both live in
``base.module_category_hidden``, so neither can be granted through the Users
form. The only way into them is ``base.group_system``, which implies the
manager group -- which is why checking the manager group *is* "settings
administrators only", while leaving the two-tier split available if the groups
are ever surfaced.
"""

from odoo import _, api, models
from odoo.exceptions import AccessError

STUDIO_USER = "app_builder_base.group_studio_user"
STUDIO_MANAGER = "app_builder_base.group_studio_manager"


class StudioSecurityMixin(models.AbstractModel):
    _name = "studio.security.mixin"
    _description = "Studio Access Guard"

    @api.model
    def _assert_studio_user(self):
        """Guard for methods that only read studio metadata."""
        return self._assert_studio_group(
            STUDIO_USER,
            _("Reading studio metadata is restricted to Studio Builders."),
        )

    @api.model
    def _assert_studio_manager(self):
        """Guard for anything that writes a record, a file, or the registry."""
        return self._assert_studio_group(
            STUDIO_MANAGER,
            _(
                "Building with the studio is restricted to Studio "
                "Administrators, because it writes source files into the "
                "addons path and reloads modules."
            ),
        )

    @api.model
    def _assert_studio_group(self, group, message):
        # env.su is the trusted-internal-code path: module install, data
        # loading and the test bootstrap all run as superuser and must not be
        # locked out of their own machinery. Core's own IrModelAccess.check
        # short-circuits on env.su for exactly this reason. RPC never sets it.
        if self.env.su or self.env.user.has_group(group):
            return True
        raise AccessError(message)
