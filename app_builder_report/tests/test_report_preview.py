# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Rendering a report for the editor, and resolving a click back to the arch."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderCase, raises
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.app_builder_view.models.builder_view_editor import BuilderViewEditor
from odoo.addons.base.models.ir_ui_view import View

from ..models.builder_report import BuilderReport
from ..models.builder_report_preview import BuilderReportPreview

if TYPE_CHECKING:
    # Only for the casts below; with `from __future__ import annotations`
    # nothing here needs these at runtime, the same bargain every Phase 1c
    # file's own `TYPE_CHECKING` block makes. `View`/`BuilderViewEditor`/
    # `BuilderReport`/`BuilderReportPreview` are real, top-level imports
    # instead (`typed.model()` reads `cls._name` at runtime, the same
    # reason `common.py`'s own fixtures import their real classes that way)
    # -- only the `locate_expression()`/`body_anchor()` union's own narrower
    # branches are cast-only and need no runtime binding.
    from ..models.builder_report_preview import (
        _BodyAnchorFoundJSON,
        _LocateExpressionFoundJSON,
        _LocateExpressionNotFoundJSON,
    )


@tagged("post_install", "-at_install")
class TestReportPreview(BuilderCase):
    def _report(self, package):
        made = typed.model(self.env, BuilderReport).create_report(
            package.id, "x_builder_project", "Job Sheet"
        )
        return typed.model(self.env, View).browse(made["view_id"])

    def _placed(self, package, view, name="x_budget"):
        typed.model(self.env, BuilderViewEditor).apply_operation(
            view.id,
            package.id,
            {
                "type": "add_report_field",
                "xpath": "//div[hasclass('page')]",
                "position": "inside",
                "model": "x_builder_project",
                "name": name,
            },
        )

    def test_the_preview_renders_the_report(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        self.env["x_builder_project"].create({"x_name": "Bridge survey"})  # pyright: ignore[reportArgumentType]
        result = typed.model(self.env, BuilderReportPreview).preview_html(
            cast("int", view.id)
        )
        self.assertFalse(result["reason"])
        self.assertIn("Job Sheet", result["html"])
        self.assertIn("Bridge survey", result["html"])

    def test_the_preview_brands_its_fields(self):
        """Base brands `t-field` and nothing else, and the attribute is
        `data-oe-expression` -- node-level `data-oe-xpath` belongs to website."""
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        self.env["x_builder_project"].create({"x_name": "Bridge survey"})  # pyright: ignore[reportArgumentType]
        html = typed.model(self.env, BuilderReportPreview).preview_html(
            cast("int", view.id)
        )["html"]
        self.assertIn("data-oe-expression", html)
        self.assertIn("doc.display_name", html)

    def test_a_report_with_nothing_to_draw_says_so(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        self.env["x_builder_project"].search([]).unlink()
        result = typed.model(self.env, BuilderReportPreview).preview_html(
            cast("int", view.id)
        )
        self.assertEqual(result["html"], "")
        self.assertIn("preview this on", cast("str", result["reason"]))

    def test_a_click_resolves_to_a_locator(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        self._placed(package, view)
        found = typed.model(self.env, BuilderReportPreview).locate_expression(
            cast("int", view.id), "doc.x_budget"
        )
        self.assertTrue(found["found"])
        # Narrows the `found()`/`not found()` union after the runtime check
        # above has already proven which branch this is -- same shape as
        # `typed.py`'s own relational-field casts, aimed at a TypedDict
        # union instead of a `env[...]` lookup.
        found = cast("_LocateExpressionFoundJSON", found)
        self.assertIn("t-field='doc.x_budget'", found["xpath"])

    def test_the_locator_survives_a_second_field(self):
        """Two spans, and the one clicked has to be the one located."""
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        self._placed(package, view, "x_budget")
        self._placed(package, view, "x_name")
        for name in ("x_budget", "x_name"):
            found = typed.model(self.env, BuilderReportPreview).locate_expression(
                cast("int", view.id), "doc.%s" % name
            )
            self.assertTrue(found["found"])
            found = cast("_LocateExpressionFoundJSON", found)
            self.assertIn(name, found["xpath"])

    def test_an_expression_we_cannot_point_at_says_why(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        found = typed.model(self.env, BuilderReportPreview).locate_expression(
            cast("int", view.id), "doc.nope"
        )
        self.assertFalse(found["found"])
        found = cast("_LocateExpressionNotFoundJSON", found)
        self.assertIn("cannot point at", found["reason"])

    def test_the_body_anchor_is_the_page(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        anchor = typed.model(self.env, BuilderReportPreview).body_anchor(
            cast("int", view.id)
        )
        self.assertTrue(anchor["found"])
        anchor = cast("_BodyAnchorFoundJSON", anchor)
        self.assertIn("page", anchor["xpath"])

    def test_the_anchor_is_usable_as_an_operation_target(self):
        """The point of it: add something without having clicked anything."""
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        anchor = cast(
            "_BodyAnchorFoundJSON",
            typed.model(self.env, BuilderReportPreview).body_anchor(
                cast("int", view.id)
            ),
        )
        typed.model(self.env, BuilderViewEditor).apply_operation(
            cast("int", view.id),
            cast("int", package.id),
            {
                "type": "add_report_field",
                "xpath": anchor["xpath"],
                "position": anchor["position"],
                "model": "x_builder_project",
                "name": "x_budget",
            },
        )
        self.assertIn(
            't-field="doc.x_budget"',
            cast("str", typed.model(self.env, View).browse(cast("int", view.id)).arch),
        )

    def test_a_form_view_is_not_a_report(self):
        package = self.make_package()
        self.build_demo_content(package)
        form = self.env["ir.ui.view"].search(
            [("model", "=", "x_builder_project"), ("type", "=", "form")], limit=1
        )
        with raises(self, UserError):
            typed.model(self.env, BuilderReportPreview).preview_html(
                cast("int", form.id)
            )

    def test_a_qweb_view_no_report_prints_is_not_a_report(self):
        """A qweb view is not a report template for being qweb: a mail layout
        or a snippet expects values no report context has."""
        loose = typed.model(self.env, View).create(
            {  # pyright: ignore[reportArgumentType]
                "name": "loose",
                "type": "qweb",
                "key": "x_builder_demo.loose_template",
                "arch": "<t t-name='x_builder_demo.loose_template'><p>loose</p></t>",
            }
        )
        with raises(self, UserError):
            typed.model(self.env, BuilderReportPreview).preview_html(
                cast("int", loose.id)
            )

    def test_the_preview_draws_the_record_it_is_asked_for(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        Project = self.env["x_builder_project"]
        first = Project.create({"x_name": "Bridge survey"})  # pyright: ignore[reportArgumentType]
        newest = Project.create({"x_name": "Tunnel survey"})  # pyright: ignore[reportArgumentType]
        Preview = typed.model(self.env, BuilderReportPreview)

        chosen = Preview.preview_html(cast("int", view.id), cast("int", first.id))
        self.assertEqual(chosen.get("res_id"), first.id)
        self.assertIn("Bridge survey", chosen["html"])
        self.assertNotIn("Tunnel survey", chosen["html"])

        # No choice, or one that is gone: the newest, as before.
        for res_id in (None, cast("int", newest.id) + 1000):
            default = Preview.preview_html(cast("int", view.id), res_id)
            self.assertEqual(default.get("res_id"), newest.id)
            self.assertIn("Tunnel survey", default["html"])

    def test_the_preview_gets_the_values_a_print_gets(self):
        """`is_html_empty` and `report_type` come from the report's own
        `_get_rendering_context`, not from a list kept by hand here -- and a
        patch's id previews the template it patches, patch applied."""
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        self.env["x_builder_project"].create({"x_name": "Bridge survey"})  # pyright: ignore[reportArgumentType]
        patch_view = typed.model(self.env, View).create(
            {  # pyright: ignore[reportArgumentType]
                "name": "job sheet patch",
                "type": "qweb",
                "mode": "extension",
                "inherit_id": view.id,
                "arch": """<data>
                    <xpath expr="//div[hasclass('page')]" position="inside">
                        <p t-if="is_html_empty('') and report_type == 'html'"
                           >drawn-as-<t t-out="doc_model"/></p>
                    </xpath>
                </data>""",
            }
        )
        for view_id in (view.id, patch_view.id):
            result = typed.model(self.env, BuilderReportPreview).preview_html(
                cast("int", view_id)
            )
            self.assertFalse(result["reason"])
            self.assertIn("drawn-as-x_builder_project", result["html"])
            self.assertIn("Bridge survey", result["html"])
