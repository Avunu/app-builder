# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""PDF reports: make a new one, or patch one somebody else wrote.

The second is the interesting half, and it is the one thing in this project
Odoo Studio structurally cannot do. Its own documentation tells you to
*duplicate* the standard report and edit the copy -- which is why a
Studio-customised database fights every upgrade, and why the copy stops
receiving fixes the day it is made.

A report template is an ``ir.ui.view`` of type qweb, so it inherits like any
other view, and core does exactly this routinely: ``sale_product_matrix``
patches ``sale.report_saleorder_document`` with an ``<xpath>``
(``sale_product_matrix/report/sale_report_templates.xml:3``). The studio's
existing view editor therefore needs nothing new for reports -- the same
``apply_operation`` that emits an inheriting form view emits an inheriting
report template.

**The three names that must agree.** ``report_name`` is handed to qweb as a
template reference (``ir_actions_report.py:1103`` → ``_render_template``), so it
resolves through ``ir.ui.view``'s xmlid-or-key lookup. A generated report
therefore sets the view's key, the view's xmlid and ``report_name`` to the same
``<package>.<slug>`` string. Get one of them wrong and the action exists, the
template exists, and printing renders nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypedDict, cast

from odoo import _, api, models
from odoo.exceptions import UserError

from odoo.addons.base.models.ir_actions_report import IrActionsReport
from odoo.addons.base.models.ir_model import IrModel, IrModelData
from odoo.addons.base.models.ir_ui_view import View
from odoo.addons.app_builder_base.models.studio_package import StudioPackage
from odoo.addons.app_builder_base.tools import scaffold, typed

if TYPE_CHECKING:
    # `studio_package_id` is added to `ir.actions.report` by `studio.owned
    # .mixin` (`app_builder_ui/models/studio_owned.py`'s own `_inherit`,
    # registry-level, never a real Python base class of the imported
    # `IrActionsReport`) -- invisible to pyright on a `report` variable the
    # same way `studio_owned_mixin.py`'s own `_inverse_studio_package_id`
    # needed a cast to read the identical field off `model_id`.
    # `TYPE_CHECKING`-only: no runtime binding needed for a plain `cast()`.
    # `name` (Action Name) lives on `ir.actions.actions` (`ir_actions.py`),
    # which `IrActionsReport` composes only through the string `_inherit =
    # 'ir.actions.actions'` core itself writes -- registry-level, never a
    # real Python base class -- so it is exactly the shape of gap `typed
    # .py`'s own module docstring describes for `_inherit` mixins
    # generally, applied here to a core base model instead of one of ours.
    from odoo.addons.base.models.ir_actions import IrActions
    from odoo.addons.app_builder_base.models.studio_owned_mixin import (
        StudioOwnedMixin,
    )


class ReportSummaryJSON(TypedDict):
    """One entry of ``reports_for()``'s return -- a report that prints the
    model, ours or somebody else's."""

    id: int
    name: str
    report_name: str
    view_id: int | Literal[False]
    owned: bool
    editable: bool


class ReportActionJSON(TypedDict):
    """``action_open()``'s return: Odoo's own report list, scoped."""

    type: str
    name: str
    res_model: str
    view_mode: str
    views: list[tuple[bool, str]]
    domain: list[tuple[str, str, object]]
    context: dict[str, object]
    help: str


class CreateReportJSON(TypedDict):
    """``create_report()``'s return: ids and reference of the new report."""

    report_id: int
    view_id: int
    report_name: str


class OpenConsoleParamsJSON(TypedDict):
    """``edit_action()``'s ``params``: which pane and view the console opens on."""

    pane: str
    res_model: str
    view_id: int
    view_type: str


class OpenConsoleActionJSON(TypedDict):
    """``edit_action()``'s return: opens the studio console on this report's
    template."""

    type: str
    tag: str
    name: str
    target: str
    params: OpenConsoleParamsJSON


class StudioReport(models.AbstractModel):
    _name = "studio.report"
    _inherit = ["studio.security.mixin"]
    _description = "Studio: PDF Reports"

    @api.model
    def layouts(self) -> list[scaffold.ReportLayoutJSON]:
        """External / Internal / Blank, as Odoo Studio names them."""
        typed.security(self)._assert_studio_user()
        return scaffold.report_layouts_json()

    @api.model
    def reports_for(self, model_name: str) -> list[ReportSummaryJSON]:
        """Every report that prints this model, ours and everybody else's.

        Both, deliberately: the point of the feature is that somebody else's is
        editable too, so a list showing only ours would hide the thing worth
        showing.
        """
        typed.security(self)._assert_studio_user()
        reports = typed.model(self.env, IrActionsReport).search(
            [("model", "=", model_name)]
        )
        out: list[ReportSummaryJSON] = []
        for report in reports:
            view = self._template_of(report)
            out.append(
                {
                    "id": cast("int", report.id),
                    "name": cast("str", cast("IrActions", report).name),
                    "report_name": cast("str", report.report_name),
                    "view_id": cast("int", view.id) or False,
                    "owned": bool(cast("StudioOwnedMixin", report).studio_package_id),
                    # No template means nothing to edit, and it is worth saying
                    # rather than offering an editor that opens on nothing.
                    "editable": bool(view),
                }
            )
        return out

    @api.model
    def action_open(
        self, model_name: str | None = None, package_id: int | None = None
    ) -> ReportActionJSON:
        """Odoo's report list, scoped and with a package to record into."""
        typed.security(self)._assert_studio_user()
        package = typed.model(self.env, StudioPackage)._chosen(package_id)
        # qweb-text and the non-qweb types have no template to click into, so
        # showing them here would be offering an editor that cannot open.
        domain: list[tuple[str, str, object]] = [
            ("report_type", "in", ["qweb-pdf", "qweb-html"])
        ]
        context: dict[str, object] = {"studio_package_id": package.id or False}
        if model_name:
            if model_name not in self.env:
                raise UserError(_("Unknown model '%s'.", model_name))
            domain.append(("model", "=", model_name))
            context["default_model"] = model_name
        return {
            "type": "ir.actions.act_window",
            "name": _("Reports"),
            "res_model": "ir.actions.report",
            "view_mode": "list,form",
            # Spelled out because the dict is also returned over plain RPC,
            # and the client derives nothing from view_mode on that path.
            "views": [(False, "list"), (False, "form")],
            "domain": domain,
            "context": context,
            "help": self._empty_state(),
        }

    @api.model
    def _empty_state(self) -> str:
        return "<p class='o_view_nocontent_smiling_face'>%s</p><p>%s</p>" % (
            _("Put this on paper"),
            _(
                "New reports you create here are written into your studio "
                "package. Reports that came with Odoo are editable too — the "
                "changes land in a view of your own that inherits theirs, so "
                "the original keeps receiving fixes."
            ),
        )

    @api.model
    def _template_of(self, report: IrActionsReport) -> View:
        """The qweb view ``report_name`` resolves to, or an empty recordset.

        The same two-step lookup qweb itself does -- key first, then xmlid --
        but deliberately not through ``_get_view_id``, which fails three
        different ways for a reference that does not resolve: ``ValueError``
        for a name with no dot, ``ValueError`` for an unknown xmlid, and an
        ``AssertionError`` when the xmlid names something that is not a view.
        A report rendered from a template built in Python is an ordinary thing
        to come across, and the answer to it is "nothing to edit here".
        """
        Views = typed.model(self.env, View)
        name = report.report_name or ""
        if "." not in name:
            return Views.browse()
        # sudo to look up, browse to hand back: a view found past the current
        # user's rights must not leave here still elevated.
        found = Views.sudo().search([("key", "=", name)], limit=1)
        if found:
            # `.browse()`'s own `int | Iterable[IdType]` does not accept
            # `found.id`'s declared `IdType | Literal[False]` un-narrowed --
            # same cast as `ir_ui_view.py`'s own `_concrete_action()`.
            return Views.browse(cast("int", found.id))
        model, res_id = typed.model(self.env, IrModelData)._xmlid_to_res_model_res_id(
            name, raise_if_not_found=False
        )
        if model != "ir.ui.view" or not res_id:
            return Views.browse()
        return Views.browse(res_id).exists()

    @api.model
    def create_report(
        self,
        package_id: int,
        model_name: str,
        name: str,
        layout: str = "external",
        paperformat_id: int | None = None,
    ) -> CreateReportJSON:
        """A new report on ``model_name``, as source."""
        typed.security(self)._assert_studio_manager()
        package = typed.model(self.env, StudioPackage).browse(package_id).exists()
        if not package:
            raise UserError(_("Choose a studio package to record this report in."))
        package._assert_writable()
        if model_name not in self.env:
            raise UserError(_("Unknown model '%s'.", model_name))
        if layout not in scaffold.REPORT_LAYOUTS_BY_KEY:
            raise UserError(_("'%s' is not a report layout.", layout))

        # The technical name can be deduplicated; the one on the Print menu
        # cannot. Two reports both called "Job Sheet" would work perfectly and
        # be indistinguishable to whoever has to pick one.
        if typed.model(self.env, IrActionsReport).search_count(
            [("model", "=", model_name), ("name", "=", name)], limit=1
        ):
            raise UserError(
                _(
                    "%(model)s already has a report called %(name)s.",
                    model=model_name,
                    name=name,
                )
            )

        arch = scaffold.arch_to_string(scaffold.scaffold_report_arch(name, layout))
        view = typed.model(self.env, View).create(
            {  # pyright: ignore[reportArgumentType] -- `@api.model_create_multi`
                # (`odoo/api.py`) is a bare passthrough decorator that does not
                # widen `create()`'s own declared `list[ValuesType]`-only
                # signature to also cover the single-dict form it genuinely
                # accepts at runtime (TYPING.md's own "Known traps").
                "name": name,
                # REQUIRED. Without it create() infers the type from the arch
                # root tag and raises "Invalid view type: 't'"
                # (`ir_ui_view.py:498`) -- and that is a ValidationError, so the
                # `except (ParseError, ValueError, TypeError)` below it does not
                # swallow it.
                "type": "qweb",
                # `model` is deliberately left empty, as core leaves it on every
                # report template. Setting it looks harmless and quietly makes
                # the report un-extensible by anyone but us:
                # `_get_inheriting_views` joins on
                # `coalesce(model,'') = coalesce(parent.model,'')`
                # (`ir_ui_view.py:645`), and `_tag_template` never emits a model
                # field (`convert.py:488`) -- so every
                # `<template inherit_id="...">` a human or another addon writes
                # arrives with model NULL, fails that join, and is dropped with
                # no exception and no warning. Which file the template lands in
                # is the emitter's problem, and is solved there.
                "arch": arch,
            }
        )
        # One value, not three that happen to agree. `_assign` is what resolves
        # a collision, so asking it first and then *deriving* the key and
        # report_name from what it gave back is the only ordering in which the
        # three cannot come apart.
        reference = package._assign(view, suggested_name=self._slug(name))[0]
        # Odoo mints `gen_key.<uuid>` for a qweb view created without a key
        # (`ir_ui_view.py:519`), and a random key is not something `report_name`
        # can name.
        view.key = reference
        report = typed.model(self.env, IrActionsReport).create(
            {  # pyright: ignore[reportArgumentType] -- same passthrough-decorator
                # gap as the view `create()` call above.
                "name": name,
                "model": model_name,
                "report_type": "qweb-pdf",
                "report_name": reference,
                # Odoo's own convention: the file stem, used when the PDF is
                # saved as an attachment.
                "report_file": reference,
                "paperformat_id": paperformat_id or False,
                # Without a binding the report exists and appears in no menu,
                # which reads as the builder having done nothing.
                "binding_model_id": typed.model(self.env, IrModel)._get(model_name).id,
                "binding_type": "report",
            }
        )
        package.studio_capture([view, report])
        return {
            "report_id": cast("int", report.id),
            "view_id": cast("int", view.id),
            "report_name": reference,
        }

    @api.model
    def _slug(self, name: str | None) -> str:
        cleaned = "".join(c if c.isalnum() else "_" for c in (name or "").lower())
        cleaned = "_".join(part for part in cleaned.split("_") if part)
        return "report_%s" % (cleaned or "document")

    @api.model
    def edit_action(self, report_id: int) -> OpenConsoleActionJSON:
        """Open the studio's view editor on a report's template.

        The same editor, on purpose. A report template is a qweb view, the
        editor already emits inheriting views for anything it does not own, and
        that is precisely the behaviour this feature exists to provide.
        """
        typed.security(self)._assert_studio_user()
        report = typed.model(self.env, IrActionsReport).browse(report_id).exists()
        if not report:
            raise UserError(_("That report no longer exists."))
        # Same `_inherit = 'ir.actions.actions'`-composed-not-subclassed gap
        # as `reports_for`'s own `cast("IrActions", report).name` above.
        action = cast("IrActions", report)
        view = self._template_of(report)
        if not view:
            raise UserError(
                _(
                    "%(name)s renders through %(template)s, which is not a view "
                    "in this database — so there is nothing to edit. A report "
                    "whose template is built in Python has to be changed in "
                    "Python.",
                    name=action.name,
                    template=report.report_name,
                )
            )
        return {
            "type": "ir.actions.client",
            "tag": "app_builder_console",
            "name": _("Edit %s", action.name),
            "target": "fullscreen",
            "params": {
                "pane": "views",
                "res_model": cast("str", report.model),
                "view_id": cast("int", view.id),
                "view_type": "qweb",
            },
        }
