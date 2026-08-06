# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Create a model as real Python, and everything that makes it an app.

The lifecycle, and why it is in this order:

1. write an *empty* module and install it, so ``pkg`` is a real installed
   module Odoo will import Python for. Doing this first means the expensive
   step happens once, on a module with nothing in it that can fail.
2. render the model class, apply, reload. The ORM model, its table and its
   reflected metadata now exist.
3. build the UI records **in the database**, against the live model, and let
   the existing serializers write them out.

Step 3 is deliberately not "render the view XML from the spec at step 2". That
would create a second, independent producer of the same file format and destroy
the round-trip invariant, which has exactly one path from record to XML. One
extra reload is a cheap price for keeping it that way.
"""

import logging

from odoo import _, api, models
from odoo.exceptions import UserError

from odoo.addons.app_builder_base.tools import modelspec, scaffold

_logger = logging.getLogger(__name__)


class StudioAppBuilder(models.AbstractModel):
    _name = "studio.app.builder"
    _inherit = ["studio.security.mixin"]
    _description = "Studio App Builder"

    # -- naming -----------------------------------------------------------

    @api.model
    def technical_name(self, label, package):
        """``Workshop Project`` -> ``x_workshop.project``-free, real dotted name.

        A Python-defined model has no ``x_`` requirement -- that CHECK
        constraint only covers ``state='manual'`` rows -- so the name a user
        sees in filters and domains can be an ordinary one.
        """
        slug = "".join(c if c.isalnum() else "_" for c in (label or "").lower())
        slug = "_".join(part for part in slug.split("_") if part)
        prefix = (package.name or "studio").removeprefix("x_")
        return "%s.%s" % (prefix, slug) if slug else prefix

    # -- the gesture ------------------------------------------------------

    @api.model
    def create_app(self, package, label, model_name=None, options=None, groups=None):
        """Build a usable app and return the pieces it is made of."""
        self._assert_studio_manager()
        package._assert_writable()
        options = options or scaffold.ScaffoldOptions()
        model_name = model_name or self.technical_name(label, package)

        # Companions first: Tags and Lines are models of their own, and the
        # parent's many2many/one2many name them. Seeded before the parent and
        # applied with it, in one reload rather than one per model -- a class
        # body only names its comodel as a string, so there is no import order
        # to satisfy, only a registry that has to end up holding both.
        companions = scaffold.companion_specs(model_name, label, options)
        spec = scaffold.scaffold_spec(model_name, label, options)

        taken = set(self.env["ir.model"].sudo().search([]).mapped("model"))
        for candidate in [*companions, spec]:
            errors = modelspec.validate_spec(candidate, taken_model_names=taken)
            if errors:
                raise UserError(
                    _("This model cannot be built:\n\n%s", "\n".join(errors))
                )
            taken.add(candidate.name)

        self._ensure_module_installed(package)
        for candidate in [*companions, spec]:
            self.env["studio.package.model"]._adopt(
                package, candidate.name, source="python"
            )
            package._seed_source_for(candidate.name, candidate)
        package.action_apply(reason=_("create %s", model_name))

        if model_name not in self.env:
            raise UserError(
                _(
                    "%(model)s was written to source but did not load. Check "
                    "the server log for the import error.",
                    model=model_name,
                )
            )

        built = self._build_ui(package, spec, options, groups)
        # A companion needs an access rule or nobody can read it -- and a tag
        # model with no ACL makes the parent's form fail to load rather than
        # merely hiding the tags. No menu and no views: a tag is edited through
        # the parent's widget and a line inside the parent's list, which is
        # what makes them companions rather than apps.
        built["companions"] = [
            self._build_access(
                self.env["ir.model"].search([("model", "=", candidate.name)], limit=1),
                groups or self.env.ref("base.group_user"),
                unlink=True,
            )
            for candidate in companions
        ]
        if built["companions"]:
            package.studio_capture(built["companions"])
        package.action_apply(reason=_("scaffold %s", model_name))
        return built

    @api.model
    def _ensure_module_installed(self, package):
        """A package must be an installed module before its Python is imported.

        Odoo only imports code for modules in the dependency graph, so writing
        a class into a directory nobody installed leaves it inert. The module
        we install here is empty, which keeps the one slow step boring.
        """
        # Bootstrap first: update_list only sees a directory that already has
        # a manifest, so asking about the module before writing one is asking
        # about something that does not exist yet.
        package._render_bootstrap_files()
        package._invalidate_module_caches()
        module = package._find_or_create_module()
        if module.state != "installed":
            module.button_immediate_install()
            module = package._find_or_create_module()
        return module

    # -- the UI half ------------------------------------------------------

    @api.model
    def _build_ui(self, package, spec, options, groups=None):
        model = self.env[spec.name]
        ir_model = self.env["ir.model"].search([("model", "=", spec.name)], limit=1)
        groups = groups or self.env.ref("base.group_user")

        access = self._build_access(ir_model, groups)
        views = self._build_views(model, spec, options)
        action = self._build_action(spec, views)
        menus = self._build_menu(spec, action, package)
        sequence = self._build_sequence(spec, options)

        captured = [access, action, menus["root"], menus["item"]]
        captured.extend(views.values())
        if sequence:
            captured.append(sequence)
        package.studio_capture(captured)
        return {
            "model": ir_model,
            "views": views,
            "action": action,
            "menu": menus["item"],
            "root_menu": menus["root"],
            "access": access,
            "sequence": sequence,
        }

    @api.model
    def _build_access(self, ir_model, groups, unlink=False):
        """Real ACL rows for real groups, in the same transaction.

        A model with no ACL is invisible to every non-superuser and takes its
        menu with it -- and because env.su bypasses the check, it looks
        perfectly fine to whoever built it.

        ``unlink`` is off for the app's own model, where deleting records is a
        decision the builder should make deliberately. It is *on* for a line
        companion, and that is not a policy difference: the line's link to its
        parent cascades, so Odoo turns both x2many removal commands into
        ``comodel.unlink()`` in the user's environment (`odoo/fields.py:4717`).
        Without it, taking a row out of the table and saving raises AccessError
        for exactly the group the app was built for.
        """
        rows = self.env["ir.model.access"]
        for group in groups:
            rows |= self.env["ir.model.access"].create(
                {
                    "name": "%s %s" % (ir_model.model, group.name),
                    "model_id": ir_model.id,
                    "group_id": group.id,
                    "perm_read": True,
                    "perm_write": True,
                    "perm_create": True,
                    "perm_unlink": unlink,
                }
            )
        return rows

    @api.model
    def _build_views(self, model, spec, options):
        """The three every model gets, plus the ones its features asked for.

        `Feature.views` records that Date & Calendar wants a calendar and
        Pipeline stages wants a kanban. That intent was computed by
        `ScaffoldOptions.view_types` and read by nothing, so the wizard's own
        help text promised "a kanban to move records across" and delivered a
        `state` field. Both scaffolds existed the whole time.
        """
        View = self.env["ir.ui.view"]
        arches = {
            "list": scaffold.scaffold_list_arch(model, spec, options),
            "form": scaffold.scaffold_form_arch(model, spec, options),
            "search": scaffold.scaffold_search_arch(model, spec, options),
        }
        for view_type in options.view_types:
            builder = scaffold.SCAFFOLD_BUILDERS.get(view_type)
            if builder is None or view_type in arches:
                continue
            extra = self._scaffold_arguments(model, view_type)
            if extra is None:
                # The view needs something this model does not have. Skipping
                # beats raising: the feature that asked for it is one of
                # several the user ticked, and losing the whole app over a
                # missing date field would be absurd.
                _logger.info(
                    "%s wanted a %s view and has nothing to build it from",
                    model._name,
                    view_type,
                )
                continue
            arches[view_type] = builder(model, spec, options, **extra)
        views = {}
        for view_type, arch in arches.items():
            views[view_type] = View.create(
                {
                    "name": "%s.%s" % (spec.name, view_type),
                    "model": spec.name,
                    "type": view_type,
                    "arch": scaffold.arch_to_string(arch),
                }
            )
        return views

    @api.model
    def _scaffold_arguments(self, model, view_type):
        """What a view type needs beyond the model, or None if it cannot be had."""
        needed = scaffold.SCAFFOLD_REQUIRES.get(view_type, ())
        out = {}
        for requirement in needed:
            if requirement == "date_field":
                # `date` is what the Date & Calendar feature creates, and
                # `date_start` what Date range creates; either will do.
                found = scaffold.first_field_of(
                    model, ("date", "datetime"), prefer=("date", "date_start")
                )
            else:
                found = scaffold.first_field_of(
                    model, ("selection", "many2one"), prefer=("state", "user_id")
                )
            if not found:
                return None
            out[requirement] = found
        return out

    @api.model
    def _build_action(self, spec, views):
        # A view no action offers is a view nobody can open, so the extra types
        # go into view_mode -- kanban first, because a model with one is
        # usually meant to be seen that way. `search` is not a mode: it is
        # attached through search_view_id.
        order = ("kanban", "list", "form", "calendar", "activity", "pivot", "graph")
        modes = [t for t in order if t in views]
        modes += sorted(set(views) - set(order) - {"search"})
        return self.env["ir.actions.act_window"].create(
            {
                "name": spec.description,
                "res_model": spec.name,
                "view_mode": ",".join(modes),
                "search_view_id": views["search"].id,
                "help": (
                    "<p class='o_view_nocontent_smiling_face'>%s</p>"
                    % _("Create the first one")
                ),
            }
        )

    @api.model
    def _build_menu(self, spec, action, package):
        """A real app menu, not a child of the Studio menu.

        The generated menu must be a *root* -- parent_id unset, no groups -- or
        two things go wrong: web_icon is only read for root menus, so there is
        no app tile; and nesting it under the Studio root hides the whole app
        behind the studio group, so the staff it was built for cannot see it.
        """
        Menu = self.env["ir.ui.menu"]
        root = Menu.create(
            {
                "name": spec.description,
                "parent_id": False,
                "web_icon": "fa fa-cube,#FFFFFF,#875A7B",
                "sequence": 90,
            }
        )
        item = Menu.create(
            {
                "name": spec.description,
                "parent_id": root.id,
                "action": "ir.actions.act_window,%d" % action.id,
                "sequence": 10,
            }
        )
        return {"root": root, "item": item}

    @api.model
    def _build_sequence(self, spec, options):
        if not options.reference:
            return None
        return self.env["ir.sequence"].create(
            {
                "name": "%s Reference" % spec.description,
                "code": spec.sequence_code,
                "prefix": "%s" % spec.description[:3].upper(),
                "padding": 4,
                "implementation": "standard",
            }
        )

    # -- honesty check ----------------------------------------------------

    @api.model
    def check_visibility(self, model_name, groups):
        """Can the people this was built for actually see it?

        ``IrModelAccess.check`` returns True immediately for ``env.su``, so an
        app with wrong or missing ACLs looks perfect to the administrator who
        built it and is invisible to everybody else. Asking the question as a
        real user is the only way to find out before they do.
        """
        results = []
        for group in groups:
            user = (
                self.env["res.users"]
                .sudo()
                .search([("groups_id", "in", group.id), ("active", "=", True)], limit=1)
            )
            if not user:
                results.append(
                    {"group": group.display_name, "ok": None, "detail": _("no users")}
                )
                continue
            try:
                self.env[model_name].with_user(user).check_access("read")
                ok, detail = True, ""
            except Exception as err:  # noqa: BLE001 - see below
                # Deliberately blind. The question being asked is "can this
                # group read the model", and *any* failure is a No worth
                # reporting -- narrowing to AccessError would let a different
                # error through as an apparent success.
                ok, detail = False, str(err).splitlines()[0]
            results.append({"group": group.display_name, "ok": ok, "detail": detail})
        return results
