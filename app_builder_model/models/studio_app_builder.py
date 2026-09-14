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

from odoo.addons.app_builder_base.tools import compat, modelspec, pycodegen, scaffold

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
    def create_app(
        self, package, label, model_name=None, options=None, groups=None, menu=None
    ):
        """Build a usable app and return the pieces it is made of.

        ``menu`` says where the app goes in the apps menu: ``None`` or
        ``{"new_root": True}`` for an app of its own, with an icon;
        ``{"parent_id": id}`` for an item under an existing app. The parent
        has to carry an xmlid, since the menu file refers to it by one.
        """
        self._assert_studio_manager()
        package._assert_writable()
        options = options or scaffold.ScaffoldOptions()
        model_name = model_name or self.technical_name(label, package)
        parent = self._menu_parent(menu)

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

        built = self._build_ui(package, spec, options, groups, parent=parent)
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
    def _menu_parent(self, menu):
        """The menu a new app goes under, checked, or ``None`` for a root."""
        if not menu or not menu.get("parent_id"):
            return None
        parent = self.env["ir.ui.menu"].browse(int(menu["parent_id"])).exists()
        if not parent:
            raise UserError(_("The menu to put the app under no longer exists."))
        if not parent.get_external_id().get(parent.id):
            raise UserError(
                _(
                    "%s has no external id, so a menu file cannot refer to it. "
                    "Pick a menu a module declares, or make the app a root.",
                    parent.complete_name,
                )
            )
        return parent

    @api.model
    def _build_ui(self, package, spec, options, groups=None, parent=None):
        model = self.env[spec.name]
        ir_model = self.env["ir.model"].search([("model", "=", spec.name)], limit=1)
        groups = groups or self.env.ref("base.group_user")

        access = self._build_access(ir_model, groups)
        views = self._build_views(model, spec, options)
        action = self._build_action(spec, views)
        menus = self._build_menu(spec, action, package, parent=parent)
        sequence = self._build_sequence(spec, options)

        captured = [access, action, menus["item"]]
        if menus["root"]:
            captured.append(menus["root"])
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
    def _build_menu(self, spec, action, package, parent=None):
        """A real app menu, not a child of the Studio menu.

        The generated menu must be a *root* -- parent_id unset, no groups -- or
        two things go wrong: web_icon is only read for root menus, so there is
        no app tile; and nesting it under the Studio root hides the whole app
        behind the studio group, so the staff it was built for cannot see it.

        The icon is a file in the package, seeded before the menu exists so
        that ``ir.ui.menu`` finds it when it decodes ``web_icon`` on create.
        Not a built ``fa-class,color,background`` icon: that form is core's,
        but the apps menu ``web_responsive`` replaces cannot render it and
        takes the whole web client down instead (``studio.package``
        ``_seed_app_icon`` has the detail).
        """
        Menu = self.env["ir.ui.menu"]
        if parent is not None:
            # Under an existing app: one item, no root and no icon.
            item = Menu.create(
                {
                    "name": spec.description,
                    "parent_id": parent.id,
                    "action": "ir.actions.act_window,%d" % action.id,
                    "sequence": 10,
                }
            )
            return {"root": Menu.browse(), "item": item}
        root = Menu.create(
            {
                "name": spec.description,
                "parent_id": False,
                "web_icon": package._seed_app_icon(),
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
                .search(
                    [
                        (compat.groups_field(self.env), "in", group.id),
                        ("active", "=", True),
                    ],
                    limit=1,
                )
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

    # -- over the wire ----------------------------------------------------
    #
    # The console calls these with ids and gets dicts back; the methods
    # above take and return records, which the probes and the tests use.

    @api.model
    def features(self):
        """The scaffold features, with what each implies and builds."""
        self._assert_studio_user()
        out = []
        for entry in scaffold.features_json():
            feature = scaffold.FEATURES_BY_KEY[entry["key"]]
            out.append(
                {
                    **entry,
                    "implies": list(feature.implies),
                    "companion": feature.companion or "",
                    "offered": entry["key"] in scaffold.WIZARD_FEATURES,
                }
            )
        return {"features": out, "defaults": sorted(scaffold.DEFAULT_FEATURES)}

    @api.model
    def suggest_name(self, label, package_id):
        """The technical name a label gets, and whether it is free."""
        self._assert_studio_user()
        package = self.env["studio.package"].browse(package_id).exists()
        if not package:
            raise UserError(_("That package no longer exists."))
        name = self.technical_name(label, package)
        taken = name in self.env or bool(
            self.env["ir.model"].sudo().search_count([("model", "=", name)])
        )
        return {"model": name, "taken": taken}

    @api.model
    def create_app_rpc(self, package_id, spec):
        """``create_app`` for the console: ids in, ids out."""
        self._assert_studio_manager()
        package = self.env["studio.package"].browse(package_id).exists()
        if not package:
            raise UserError(_("That package no longer exists."))
        label = (spec.get("label") or "").strip()
        if not label:
            raise UserError(_("The app needs a name."))
        try:
            options = scaffold.ScaffoldOptions.from_keys(spec.get("features") or ())
        except ValueError as err:
            raise UserError(str(err)) from err
        group_ids = [int(g) for g in (spec.get("groups") or []) if g]
        groups = self.env["res.groups"].browse(group_ids) if group_ids else None
        built = self.create_app(
            package,
            label,
            model_name=(spec.get("model_name") or "").strip() or None,
            options=options,
            groups=groups,
            menu=spec.get("menu"),
        )
        ir_model = built["model"]
        return {
            "model": ir_model.model,
            "model_id": ir_model.id,
            "action_id": built["action"].id,
            "menu_id": built["menu"].id,
            "root_menu_id": built["root_menu"].id if built["root_menu"] else False,
            "views": {vtype: view.id for vtype, view in built["views"].items()},
            "access_ids": built["access"].ids,
            "sequence_id": built["sequence"].id if built["sequence"] else False,
            "companions": [
                {"model": rows.model_id.model, "access_ids": rows.ids}
                for rows in built["companions"]
                if rows
            ],
            "visibility": self.check_visibility(
                ir_model.model, groups or self.env.ref("base.group_user")
            ),
        }

    # Features that cannot be added to a model that exists: each builds a
    # second model with an access rule of its own, which is New Model's job.
    NEEDS_SECOND_MODEL = ("tags", "lines")

    @api.model
    def add_feature(self, package_id, model_name, key):
        """Stage a scaffold feature on a model the package defines in Python.

        The same fields and model options the feature would have given a
        new model, staged on the model's draft so they are previewed and
        applied like any other change; the views a feature owes -- a
        kanban, a chatter -- are added after the apply, when the columns
        exist (``studio.model.draft._apply_features``).
        """
        self._assert_studio_manager()
        if key not in scaffold.FEATURES_BY_KEY:
            raise UserError(_("There is no feature called '%s'.", key))
        if key in self.NEEDS_SECOND_MODEL:
            raise UserError(
                _(
                    "Tags and Lines build a second model each. Create it with "
                    "New Model, then drop a Tags or Lines field that points at it."
                )
            )
        Draft = self.env["studio.model.draft"]
        draft = Draft.browse(Draft.open_for_model(model_name)["id"])
        if draft.package_id.id != package_id:
            raise UserError(
                _(
                    "%(model)s is defined by %(owner)s; switch to that package "
                    "to change it.",
                    model=model_name,
                    owner=draft.package_id.name,
                )
            )
        spec = draft._spec()
        label = spec.description or model_name
        bare = scaffold.scaffold_spec(
            model_name, label, scaffold.ScaffoldOptions.from_keys(())
        )
        wanted = scaffold.scaffold_spec(
            model_name, label, scaffold.ScaffoldOptions.from_keys((key,))
        )
        bare_names = {f.name for f in bare.fields}
        wanted_json = modelspec.spec_to_json(wanted)["fields"]
        added, already = [], []
        for index, field in enumerate(wanted.fields):
            if field.name in bare_names:
                continue
            if spec.field(field.name):
                already.append(field.name)
                continue
            placement = modelspec.default_placement(field.ttype)
            draft.add_field({**wanted_json[index], "placement": dict(placement)})
            added.append(field.name)
        options = {}
        missing_mixins = [m for m in wanted.inherit if m not in spec.inherit]
        if missing_mixins:
            options["inherit"] = list(spec.inherit) + missing_mixins
        if key == "ordering" and wanted.order and wanted.order != spec.order:
            options["order"] = wanted.order
        if wanted.active_name and not spec.active_name:
            options["active_name"] = wanted.active_name
        if wanted.sequence_code and not spec.sequence_code:
            options["sequence_code"] = wanted.sequence_code
            options["sequence_field"] = wanted.sequence_field
        if options:
            draft.set_model_options(options)
        if not added and not options:
            raise UserError(
                _(
                    "%(model)s already has everything %(key)s adds.",
                    model=model_name,
                    key=key,
                )
            )
        draft.stage_feature(key)
        feature = scaffold.FEATURES_BY_KEY[key]
        return {
            "draft_id": draft.id,
            "added": added,
            "already": already,
            "options": options,
            "views": list(feature.views),
            "chatter": key == "chatter",
        }

    # -- adopt --------------------------------------------------------------

    @api.model
    def adoptable_models(self):
        """Manual models no package defines in Python, with a preview each."""
        self._assert_studio_user()
        owned_python = set(
            self.env["studio.package.model"]
            .sudo()
            .search([("source", "in", ("python", "frozen"))])
            .mapped("model")
        )
        Package = self.env["studio.package"].sudo()
        out = []
        for model in self.env["ir.model"].sudo().search([("state", "=", "manual")]):
            if model.model in owned_python:
                continue
            xmlid = model.get_external_id().get(model.id) or ""
            module = xmlid.partition(".")[0]
            owner = (
                Package.search([("name", "=", module)], limit=1) if module else Package
            )
            manual_fields = model.field_id.filtered(lambda f: f.state == "manual")
            try:
                preview = pycodegen.render_model(
                    pycodegen.spec_from_ir_model(model, manual_fields)
                )
            except Exception as err:  # noqa: BLE001 - the preview says why
                preview = "# %s" % err
            count = 0
            if model.model in self.env:
                count = self.env[model.model].sudo().search_count([])
            out.append(
                {
                    "id": model.id,
                    "model": model.model,
                    "name": model.name,
                    "origin": "studio" if module else "manual",
                    "owner_package": (
                        {"id": owner.id, "name": owner.name} if owner else None
                    ),
                    "field_count": len(manual_fields),
                    "record_count": count,
                    "preview": preview,
                }
            )
        return out

    @api.model
    def adopt(self, package_id, model_names, apply=True):
        """Bring manual models under Python management, in the package."""
        self._assert_studio_manager()
        package = self.env["studio.package"].browse(package_id).exists()
        if not package:
            raise UserError(_("That package no longer exists."))
        names = [n for n in (model_names or []) if n]
        if not names:
            raise UserError(_("Choose at least one model."))
        # A hand-made model belongs to no package; the user just said which.
        already = package._owned_model_names()
        captured = []
        for model in self.env["ir.model"].search([("model", "in", names)]):
            if model.model in already:
                continue
            package.studio_capture(
                [model, model.field_id.filtered(lambda f: f.state == "manual")]
            )
            captured.append(model.model)
        package.action_adopt(names)
        # The class is on disk; one reload makes it the model. `apply`
        # is separable for the tests, which cannot sit through a commit.
        applied = False
        if apply:
            result = package.action_apply(reason=_("adopt %s", ", ".join(names)))
            applied = result.state == "applied"
        return {
            "adopted": names,
            "captured": captured,
            "applied": applied,
            "restart_required": package.reload_mode == "manual",
        }

    @api.model
    def create_field(self, package_id, model_name, values):
        """A manual ``x_`` field on any model, written to the package.

        The console's drop creates a field where it lands; this is the
        field with no place yet -- a computed one, say -- made from the
        model's own list.
        """
        self._assert_studio_manager()
        package = self.env["studio.package"].browse(package_id).exists()
        if not package:
            raise UserError(_("That package no longer exists."))
        name = (values.get("name") or "").strip()
        if not name.startswith("x_"):
            raise UserError(_("A custom field name must start with 'x_'."))
        ir_model = (
            self.env["ir.model"].sudo().search([("model", "=", model_name)], limit=1)
        )
        if not ir_model:
            raise UserError(_("Unknown model '%s'.", model_name))
        ttype = values.get("ttype") or "char"
        vals = {
            "name": name,
            "field_description": values.get("field_description") or name,
            "ttype": ttype,
            "model_id": ir_model.id,
            "required": bool(values.get("required")),
            "store": values.get("store", True),
        }
        if ttype in ("many2one", "one2many", "many2many"):
            if not values.get("relation"):
                raise UserError(_("A relational field needs a related model."))
            vals["relation"] = values["relation"]
        if ttype == "one2many":
            if not values.get("relation_field"):
                raise UserError(_("A one2many field needs an inverse field."))
            vals["relation_field"] = values["relation_field"]
        if values.get("compute"):
            vals.update(
                {
                    "compute": values["compute"],
                    "depends": values.get("depends") or False,
                }
            )
        field = (
            self.env["ir.model.fields"]
            .with_context(studio_skip_autocapture=True)
            .create(vals)
        )
        package.studio_capture(field)
        return {"field_id": field.id, "name": field.name}
