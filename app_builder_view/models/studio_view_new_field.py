# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Creating a field from inside the view editor, where you noticed it was missing.

The gesture has two answers, and choosing between them is most of the work.

On a model this package **defines in Python**, a clean-named field is a class
attribute, and a new column needs the class re-imported -- so the honest
behaviour is to hand off to the composer, where edits batch behind one Apply,
rather than pretend the field appeared. The anchor travels with the handoff, so
placing it afterwards is still one click.

On a **core or adopted** model there is no such wait: a manual field is an
``ir.model.fields`` row, it is live the moment it is written, and the ``x_``
prefix Odoo requires there is expected anyway. So create-and-place is one
gesture, and the field lands on the screen you were looking at as an inheriting
view.
"""

from odoo import _, api, models
from odoo.exceptions import UserError

# What the panel offers. Deliberately short: these are the types whose whole
# definition is a name and a label. A selection needs its values, a one2many
# needs an inverse that may not exist yet, and a computed field needs a body --
# each is a conversation, and the composer is where conversations happen.
QUICK_TYPES = (
    ("char", "Text"),
    ("text", "Multiline text"),
    ("integer", "Whole number"),
    ("float", "Decimal"),
    ("monetary", "Money"),
    ("boolean", "Checkbox"),
    ("date", "Date"),
    ("datetime", "Date & time"),
    ("html", "Rich text"),
    ("binary", "File"),
    ("many2one", "Link to a record"),
)


class StudioViewEditor(models.AbstractModel):
    _inherit = "studio.view.editor"

    @api.model
    def quick_field_types(self):
        self._assert_studio_user()
        return [{"value": key, "label": label} for key, label in QUICK_TYPES]

    @api.model
    def _python_owner(self, model_name):
        """The package that defines ``model_name`` as a Python class, if any."""
        for package in self.env["studio.package"].search([]):
            if model_name in package._python_model_set():
                return package
        return self.env["studio.package"].browse()

    @api.model
    def new_field_plan(self, view_id):
        """Which of the two answers applies here, and what to say about it.

        Asked before the form is shown rather than after it is submitted: a
        panel that takes a name and a type and then explains it cannot use them
        is worse than one that says so first.
        """
        self._assert_studio_user()
        view = self.env["ir.ui.view"].browse(view_id).exists()
        if not view or not view.model:
            return {"can_create": False, "reason": _("This view has no model.")}
        owner = self._python_owner(view.model)
        if owner:
            return {
                "can_create": False,
                "handoff": owner.id,
                "model": view.model,
                "reason": _(
                    "%(model)s is defined in Python by %(package)s, so a new "
                    "field is a class attribute and the model has to be "
                    "re-imported before it exists. The composer batches that "
                    "behind one Apply — it will open with this spot remembered.",
                    model=view.model,
                    package=owner.name,
                ),
            }
        return {"can_create": True, "model": view.model, "prefix": "x_"}

    @api.model
    def create_field_at(self, view_id, package_id, anchor, values):
        """Create a manual field and place it, in one gesture.

        Only on a model no package defines in Python: everywhere else this
        would write a row that the next Apply has to reconcile against a class,
        which is the drift the project exists to prevent.
        """
        self._assert_studio_manager()
        view = self.env["ir.ui.view"].browse(view_id).exists()
        if not view:
            raise UserError(_("The view being edited no longer exists."))
        plan = self.new_field_plan(view_id)
        if not plan.get("can_create"):
            raise UserError(plan.get("reason") or _("A field cannot be created here."))

        package = self.env["studio.package"].browse(package_id).exists()
        if not package:
            raise UserError(_("Choose a studio package to record this field in."))

        label = (values.get("field_description") or "").strip()
        if not label:
            raise UserError(_("The field needs a label."))
        name = values.get("name") or self._quick_field_name(label)
        if not name.startswith("x_"):
            raise UserError(_("A custom field name must start with 'x_'."))
        if name in self.env[view.model]._fields:
            raise UserError(_("%s already has a field called %s.", view.model, name))
        ttype = values.get("ttype") or "char"
        if ttype not in dict(QUICK_TYPES):
            raise UserError(_("'%s' is not one of the quick field types.", ttype))

        payload = {
            "name": name,
            "field_description": label,
            "ttype": ttype,
            "model_id": self.env["ir.model"]._get(view.model).id,
        }
        if ttype == "many2one":
            relation = values.get("relation")
            if not relation or relation not in self.env:
                raise UserError(_("Choose the model this field should link to."))
            payload["relation"] = relation
            # Without this Odoo defaults to 'set null', which is right often
            # enough, but saying it makes the generated source explicit.
            payload["on_delete"] = "set null"

        field = (
            self.env["ir.model.fields"]
            .with_context(studio_skip_autocapture=True)
            .create(payload)
        )
        package.studio_capture(field)
        # And onto the screen it was created from. Creating a field and leaving
        # the user to find it in a palette is two gestures for one intention.
        self.add_field_at(view_id, package_id, anchor, name)
        return {"name": name, "label": label}

    @api.model
    def _quick_field_name(self, label):
        slug = "".join(c if c.isalnum() else "_" for c in label.lower())
        return "x_%s" % "_".join(part for part in slug.split("_") if part)
