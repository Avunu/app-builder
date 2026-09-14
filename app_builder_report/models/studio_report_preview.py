# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Rendering a report so it can be clicked, and resolving what was clicked.

A report is a template, not a view type. The web client lays out a form or a
list from an arch; it has no renderer for qweb, so the editor's preview pane
cannot mount one. What it can show is the report's *output*, rendered to HTML
here and handed over as markup.

**How a click finds its way back to the arch.** Not through
``data-oe-xpath``: that is stamped by ``inherit_branding`` during inheritance
combination (``ir_ui_view.py:775``) and describes which view contributed a spec,
and node-level branding of rendered output is a ``website`` feature that
community's base does not have. What base does have is field branding --
``ir_qweb_fields.attributes`` (``ir_qweb_fields.py:101``) stamps
``data-oe-expression`` on every ``t-field`` when ``inherit_branding`` is on --
and for a report that is the better anchor anyway: it names the qweb expression,
which is the thing the arch also names.

**Not through ir.actions.report.** ``_render_template`` forces
``inherit_branding=False`` (``ir_actions_report.py:765``), so a report rendered
the ordinary way comes back with no branding at all whatever context it is given.
The template is rendered directly through ``ir.qweb`` instead, with the same
``docs`` the report would have passed.
"""

import time

from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StudioReportPreview(models.AbstractModel):
    _inherit = "studio.report"

    @api.model
    def _preview_record(self, model_name):
        """Something real to render, because a report of nothing shows nothing.

        The most recently created record: a report is about the shape of the
        document, and the newest record is the one the builder most likely just
        made while trying this out.
        """
        if model_name not in self.env:
            return None
        model = self.env[model_name]
        return model.search([], order="id desc", limit=1) or None

    @api.model
    def preview_html(self, view_id):
        """The report's own output, branded so its fields can be clicked."""
        self._assert_studio_user()
        view = self.env["ir.ui.view"].browse(view_id).exists()
        if not view or view.type != "qweb":
            raise UserError(_("That is not a report template."))
        report = self.env["ir.actions.report"].search(
            [("report_name", "=", view.key)], limit=1
        )
        model_name = report.model or view.model
        record = self._preview_record(model_name) if model_name else None
        if record is None:
            return {
                "html": "",
                "model": model_name,
                "reason": _(
                    "There is no %s to preview this on yet. Create one and the "
                    "report will draw it.",
                    self.env["ir.model"]._get(model_name).name
                    if model_name
                    else _("record"),
                ),
            }
        qweb = self.env["ir.qweb"].with_context(inherit_branding=True)
        # The same names a printed report gets (`ir.actions.report
        # ._render_template`): the internal layout stamps the time with
        # `context_timestamp`, the external one reads `res_company`.
        user = self.env["res.users"].browse(self.env.uid)
        html = qweb._render(
            view.id,
            {
                "docs": record,
                "doc_ids": record.ids,
                "doc_model": model_name,
                "env": self.env,
                "time": time,
                "context_timestamp": lambda t: fields.Datetime.context_timestamp(
                    self.with_context(tz=user.tz), t
                ),
                "user": user,
                "res_company": self.env.company,
                "web_base_url": self.env["ir.config_parameter"]
                .sudo()
                .get_param("web.base.url", default=""),
            },
        )
        return {
            "html": str(html),
            "reason": False,
            "res_id": record.id,
            # The client needs this and cannot read it off the view: a report
            # template leaves `model` empty on purpose, or every
            # `<template inherit_id=...>` written against it is silently dropped.
            "model": model_name,
        }

    @api.model
    def printable_fields(self, model_name):
        """What a report can print, split by how it prints it.

        `values` are placed as a `t-field` span; `lists` become a table. The
        split is the same one `add_report_field` refuses on, said before the
        refusal rather than after it.
        """
        self._assert_studio_user()
        if model_name not in self.env:
            return {"values": [], "lists": []}
        values, lists = [], []
        for name, field in sorted(self.env[model_name]._fields.items()):
            if not field.store and not field.related:
                continue
            entry = {"name": name, "string": field.string or name, "type": field.type}
            if field.type in ("one2many", "many2many"):
                entry["columns"] = [
                    {"name": sub, "string": sf.string or sub}
                    for sub, sf in sorted(self.env[field.comodel_name]._fields.items())
                    if sf.store and sf.type not in ("one2many", "many2many", "binary")
                ]
                lists.append(entry)
            elif field.type != "binary":
                values.append(entry)
        return {"values": values, "lists": lists}

    @api.model
    def locate_expression(self, view_id, expression):
        """The arch node printing ``expression``, as a locator.

        The click carries `data-oe-expression` -- `doc.x_budget` -- and the arch
        carries the same string in a `t-field`. Resolution stays server-side for
        the same reason every other locator does: the rendered document a
        reader sees is theirs, shaped by their language, their company's layout
        and what they are allowed to read.
        """
        self._assert_studio_user()
        view = self.env["ir.ui.view"].browse(view_id).exists()
        if not view:
            raise UserError(_("The report template no longer exists."))
        root = etree.fromstring(view.get_combined_arch().encode())
        matches = [n for n in root.iter() if n.get("t-field") == expression]
        if not matches:
            return {
                "found": False,
                "reason": _(
                    "%s is printed by something the builder cannot point at — "
                    "a sub-template, or an expression built at render time.",
                    expression,
                ),
            }
        editor = self.env["studio.view.editor"]
        return {
            "found": True,
            "xpath": editor._locator_for(matches[0], editor._occurrences(root)),
            "expression": expression,
            "tag": matches[0].tag,
        }

    @api.model
    def body_anchor(self, view_id):
        """Where a new element goes when nothing was clicked.

        Every layout this builder scaffolds puts the document body in
        ``div.page``, and so does every core report -- it is the convention
        `l10n_*` modules anchor on. Falling back to the loop keeps a
        hand-written template addressable.
        """
        self._assert_studio_user()
        view = self.env["ir.ui.view"].browse(view_id).exists()
        if not view:
            raise UserError(_("The report template no longer exists."))
        root = etree.fromstring(view.get_combined_arch().encode())
        for expr in (
            "//div[hasclass('page')]",
            "//t[@t-foreach='docs']",
            "//t[@t-call='web.html_container']",
        ):
            if root.xpath(expr.replace("hasclass('page')", "contains(@class,'page')")):
                return {"found": True, "xpath": expr, "position": "inside"}
        return {
            "found": False,
            "reason": _(
                "This template has no recognisable body to add to. Edit it as "
                "source, or start from a layout the builder generated."
            ),
        }
