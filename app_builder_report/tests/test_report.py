# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Reports: making one, and patching one somebody else wrote.

The second is the differentiator. Odoo Studio's documentation tells you to
duplicate the standard report and edit the copy, which is why a Studio database
fights every upgrade. A report template is a qweb view, so it inherits like any
other — and core does exactly this: `sale_product_matrix` patches
`sale.report_saleorder_document` with an xpath.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.base.models.ir_actions_report import IrActionsReport
from odoo.addons.base.models.ir_ui_view import View
from odoo.addons.app_builder_base.tests.common import StudioCase, raises
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.app_builder_view.models.studio_view_editor import StudioViewEditor

from ..models.studio_report import StudioReport

if TYPE_CHECKING:
    # Only for the `cast()` below; unlike `IrActionsReport`/`View`/
    # `StudioViewEditor` above, `IrActions` is never passed to `typed.model()`
    # at runtime, only named inside a `cast("IrActions", ...)` string.
    from odoo.addons.base.models.ir_actions import IrActions


@tagged("post_install", "-at_install")
class TestCreateReport(StudioCase):
    def _make(self, package, **kwargs):
        return typed.model(self.env, StudioReport).create_report(
            package.id, "x_studio_project", kwargs.pop("name", "Job Sheet"), **kwargs
        )

    def test_the_three_names_agree(self):
        """`report_name` is handed to qweb as a template reference, so it has to
        resolve through the view's xmlid-or-key lookup. Get one wrong and the
        action exists, the template exists, and printing renders nothing."""
        package = self.make_package()
        self.build_demo_content(package)
        made = self._make(package)
        report = typed.model(self.env, IrActionsReport).browse(made["report_id"])
        view = typed.model(self.env, View).browse(made["view_id"])
        self.assertEqual(report.report_name, view.key)
        self.assertEqual(report.report_name, made["report_name"])
        self.assertTrue(
            cast("str", report.report_name).startswith(cast("str", package.name) + ".")
        )

    def test_the_template_resolves_the_way_odoo_will_resolve_it(self):
        package = self.make_package()
        self.build_demo_content(package)
        made = self._make(package)
        report = typed.model(self.env, IrActionsReport).browse(made["report_id"])
        found = typed.model(self.env, StudioReport)._template_of(report)
        self.assertEqual(found.id, made["view_id"])

    def test_each_layout_produces_a_renderable_wrapper(self):
        package = self.make_package()
        self.build_demo_content(package)
        for layout, marker in (
            ("external", "web.external_layout"),
            ("internal", "web.internal_layout"),
        ):
            made = self._make(package, name="Sheet %s" % layout, layout=layout)
            arch = cast("str", typed.model(self.env, View).browse(made["view_id"]).arch)
            self.assertIn("web.html_container", arch)
            self.assertIn(marker, arch)
        made = self._make(package, name="Sheet blank", layout="blank")
        arch = cast("str", typed.model(self.env, View).browse(made["view_id"]).arch)
        self.assertIn("web.html_container", arch)
        self.assertNotIn("_layout", arch)

    def test_the_report_is_written_to_source(self):
        package = self.make_package()
        self.build_demo_content(package)
        self._make(package)
        emitted = "".join(package._render_files().values())
        self.assertIn("qweb", emitted, "a qweb view must carry its type")
        self.assertIn("Job Sheet", emitted)

    def test_two_reports_on_a_model_cannot_share_a_name(self):
        """The technical name deduplicates; the one on the Print menu cannot."""
        package = self.make_package()
        self.build_demo_content(package)
        self._make(package)
        with raises(self, UserError) as caught:
            self._make(package)
        self.assertIn("Job Sheet", str(caught.exception))

    def test_the_xmlid_is_the_template_name(self):
        """Not two strings that happen to agree -- one, derived from the other,
        so a collision resolved by `_assign` cannot leave them apart."""
        package = self.make_package()
        self.build_demo_content(package)
        made = self._make(package)
        view = typed.model(self.env, View).browse(made["view_id"])
        self.assertEqual(view.get_external_id()[view.id], made["report_name"])
        self.assertEqual(view.key, made["report_name"])

    def test_the_generated_report_actually_renders(self):
        """The failure this whole naming dance exists to prevent.

        Every other test here compares strings. This one hands the report to
        Odoo's own pipeline, which is the only thing that proves the three
        names resolve: if any of them were wrong the action would still exist,
        the template would still exist, and printing would produce nothing.

        HTML rather than PDF on purpose -- the PDF step is wkhtmltopdf's, and
        what is under test is the template lookup, not the renderer.
        """
        package = self.make_package()
        self.build_demo_content(package)
        made = self._make(package)
        record_vals: dict[str, object] = {"x_name": "Bridge survey"}
        record = self.env["x_studio_project"].create(record_vals)  # pyright: ignore[reportArgumentType]
        report = typed.model(self.env, IrActionsReport).browse(made["report_id"])
        html, kind = report._render_qweb_html(report.report_name, record.ids)
        self.assertEqual(kind, "html")
        body = html.decode() if isinstance(html, bytes) else html
        self.assertIn("Job Sheet", body, "the heading the scaffold wrote")
        self.assertIn(
            record.display_name, body, "the record the report was asked to print"
        )

    def test_a_generated_report_can_be_extended_by_a_template(self):
        """The silent failure: a `<template inherit_id=...>` that never applies.

        `_tag_template` never emits a model field (`convert.py:488`), so every
        extension written the ordinary XML way arrives with model NULL. If our
        template carries a model, `_get_inheriting_views` drops the extension on
        `coalesce(model,'') = coalesce(parent.model,'')` (`ir_ui_view.py:645`)
        -- no exception, no warning, the patch simply is not there. A report
        nobody but this studio can extend is not source code.
        """
        package = self.make_package()
        self.build_demo_content(package)
        made = self._make(package)
        template = typed.model(self.env, View).browse(made["view_id"])
        self.assertFalse(template.model, "a report template must leave `model` empty")
        extension_vals: dict[str, object] = {
            "name": "somebody else's patch",
            "type": "qweb",
            "inherit_id": template.id,
            "mode": "extension",
            "arch": """
                    <data>
                      <xpath expr="//div[hasclass('page')]" position="inside">
                        <p>added from another addon</p>
                      </xpath>
                    </data>
                """,
        }
        self.env["ir.ui.view"].create(extension_vals)  # pyright: ignore[reportArgumentType]
        combined = template._get_combined_arch()
        self.assertIn(
            "added from another addon",
            etree.tostring(combined, encoding="unicode"),
            "an extension written the ordinary way must actually apply",
        )

    def test_every_layout_splits_one_body_per_record(self):
        """`div.article` is what maps a PDF body back to a record.

        `_prepare_html` splits on it and reads data-oe-model / data-oe-id off it
        (`ir_actions_report.py:411-427`). Without one, any number of records
        prints as a single undivided body -- and a report with `attachment` set
        refuses outright. External and Internal inherit theirs from the layout
        they call; Blank has to draw its own, because `web.basic_layout` calls
        `web.html_container` itself and cannot go inside the loop.
        """
        package = self.make_package()
        self.build_demo_content(package)
        records = self.env["x_studio_project"].create(
            [{"x_name": "First"}, {"x_name": "Second"}]
        )
        for layout in ("external", "internal", "blank"):
            made = self._make(package, name="Sheet %s" % layout, layout=layout)
            report = typed.model(self.env, IrActionsReport).browse(made["report_id"])
            html = report._render_qweb_html(report.report_name, records.ids)[0]
            # `_prepare_html`'s own `report_model=False` default (core,
            # unannotated) narrows the inferred parameter type to `bool` --
            # the real function takes the model name string.
            bodies, res_ids = report._prepare_html(
                html,
                report_model=report.model,  # pyright: ignore[reportArgumentType]
            )[:2]
            self.assertEqual(
                len(bodies),
                2,
                "%s produced %d bodies for 2 records" % (layout, len(bodies)),
            )
            self.assertEqual(
                sorted(res_ids),
                sorted(records.ids),
                "%s lost the mapping from body back to record" % layout,
            )

    def test_a_new_report_appears_in_the_print_menu(self):
        package = self.make_package()
        self.build_demo_content(package)
        made = self._make(package)
        report = typed.model(self.env, IrActionsReport).browse(made["report_id"])
        self.assertEqual(report.binding_type, "report")
        self.assertTrue(cast("IrActions", report).binding_model_id)


@tagged("post_install", "-at_install")
class TestPatchAnExistingReport(StudioCase):
    """The half Odoo Studio cannot do."""

    def _core_report(self):
        report = typed.model(self.env, IrActionsReport).search(
            [("report_type", "=", "qweb-pdf")], limit=1
        )
        if not report:
            self.skipTest("no qweb report installed here")
        view = typed.model(self.env, StudioReport)._template_of(report)
        if not view:
            self.skipTest("that report's template is not a view")
        return report, view

    def test_a_core_report_is_patched_not_rewritten(self):
        package = self.make_package()
        self.build_demo_content(package)
        _report, view = self._core_report()
        before = view.arch
        typed.model(self.env, StudioViewEditor).apply_operation(
            cast("int", view.id),
            cast("int", package.id),
            {
                "type": "set_attributes",
                "xpath": "//t[@t-call='web.html_container']",
                "position": "attributes",
                "attrs": {"data-studio": "1"},
            },
        )
        self.assertEqual(
            typed.model(self.env, View).browse(cast("int", view.id)).arch,
            before,
            "a report somebody else owns must never be rewritten in place",
        )
        extension = typed.model(self.env, View).search(
            [("inherit_id", "=", view.id), ("studio_package_id", "=", package.id)]
        )
        self.assertTrue(extension, "the edit must land in an inheriting view")
        self.assertEqual(extension.type, "qweb", "an extension inherits the type")

    def test_the_editor_opens_on_a_reports_template(self):
        package = self.make_package()
        self.build_demo_content(package)
        report, view = self._core_report()
        action = typed.model(self.env, StudioReport).edit_action(cast("int", report.id))
        self.assertEqual(action["tag"], "app_builder_console")
        self.assertEqual(action["params"]["pane"], "views")
        self.assertEqual(action["params"]["view_id"], view.id)
        self.assertEqual(action["params"]["view_type"], "qweb")

    def test_a_report_with_no_template_says_so(self):
        package = self.make_package()
        self.build_demo_content(package)
        report_vals: dict[str, object] = {
            "name": "Built in Python",
            "model": "x_studio_project",
            "report_type": "qweb-pdf",
            "report_name": "nothing.resolves_to_this",
        }
        report = self.env["ir.actions.report"].create(report_vals)  # pyright: ignore[reportArgumentType]
        package._assign(report)
        with raises(self, UserError) as caught:
            typed.model(self.env, StudioReport).edit_action(cast("int", report.id))
        self.assertIn("nothing to edit", str(caught.exception))
