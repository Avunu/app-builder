# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Every stored field of every serialized model has to be accounted for.

``_studio_fields`` is an allowlist, and an allowlist is only honest if somebody
has looked at what it leaves out. Before this, a field omitted from the list was
dropped from the generated source silently and the package still reported clean
-- so I3 (``load_from_files(serialize(db)) == db``) broke in the one way no test
would notice. That is not hypothetical: ``ir.actions.server`` was missing every
field ``mail`` and ``sms`` contribute, so an automation that sent an email
serialized with its type and none of its configuration.

Two tests, doing different jobs:

* the static one below asks whether every stored field has a *decision* -- emit,
  ignore, or refuse. It fails when a newly installed module contributes a field
  nobody has classified, long before a user happens to set it.
* the runtime guard (``_assert_complete``) refuses to write a record that would
  actually lose a value. That is the one protecting data; this one is protecting
  the developer from having to notice.
"""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import StudioCase


@tagged("post_install", "-at_install")
class TestSerializerCoverage(StudioCase):
    def _serializers(self):
        Serializer = self.env["studio.serializer"]
        for model_name in Serializer._serializable_models():
            serializer = Serializer._for_model(model_name)
            if serializer is not None and model_name in self.env:
                yield model_name, serializer

    def test_every_stored_field_is_classified(self):
        """Emit it, ignore it, or refuse it -- but decide.

        Deliberately checked against the *live* registry rather than a fixture,
        because the fields that matter are exactly the ones another installed
        module contributed. Reading base/models/*.py cannot see those.
        """
        unclassified = {}
        for model_name, serializer in self._serializers():
            model = self.env[model_name]
            missing = sorted(
                name
                for name, field in model._fields.items()
                if field.store
                and not field.automatic
                and name not in serializer._classified_fields()
            )
            if missing:
                unclassified[model_name] = missing
        self.assertFalse(
            unclassified,
            "These stored fields have no decision recorded. Add each to the "
            "serializer's _studio_fields, or to _studio_ignored with the "
            "reason it cannot carry a user's intent:\n"
            + "\n".join(
                "  %s: %s" % (model, ", ".join(names))
                for model, names in sorted(unclassified.items())
            ),
        )

    def test_a_serializer_never_claims_a_field_twice(self):
        """Emitting *and* ignoring the same field means one of them is a lie."""
        for model_name, serializer in self._serializers():
            overlap = serializer._emitted_fields() & serializer._ignored_fields()
            self.assertFalse(
                overlap,
                "%s both emits and ignores %s" % (model_name, sorted(overlap)),
            )

    def test_classifications_name_real_fields(self):
        """A stale entry would silently stop covering anything.

        Optional-module fields are the exception: ``app_builder_mail`` lists the
        ``sms`` ones so they survive when that module is present, and they are
        simply absent when it is not.
        """
        optional = {"sms_template_id", "sms_method"}
        for model_name, serializer in self._serializers():
            model = self.env[model_name]
            for name in serializer._classified_fields() - optional:
                self.assertIn(
                    name,
                    model._fields,
                    "%s classifies '%s', which is not a field of %s"
                    % (serializer._name, name, model_name),
                )


@tagged("post_install", "-at_install")
class TestCompletenessGuard(StudioCase):
    """Both halves of the bargain.

    ``mock.patch`` rather than plain assignment: setting a class attribute on a
    registry model leaves it there, and Odoo's own leak detector fails the run
    with "Found unexpected attributes on ...". ``patch.object`` removes what it
    added, which is the difference between restoring a value and restoring the
    absence of one.
    """

    def _view_serializer(self, package):
        return self.env["studio.serializer.ir.ui.view"].with_context(
            studio_package=package.name
        )

    def _without_priority(self, serializer):
        kept = tuple(f for f in serializer._studio_fields if f != "priority")
        return patch.object(type(serializer), "_studio_fields", kept)

    def test_an_unclassified_value_refuses_to_serialize(self):
        """The guard is what turns silent data loss into a stopped write."""
        package = self.make_package()
        self.build_demo_content(package)
        view = self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project"), ("type", "=", "form")], limit=1
        )
        view.priority = 42
        serializer = self._view_serializer(package)
        with (
            self._without_priority(serializer),
            self.assertRaises(UserError) as caught,
        ):
            serializer._serialize(view, "%s.view_x" % package.name)
        self.assertIn("priority", str(caught.exception))

    def test_an_unclassified_default_is_not_an_error(self):
        """A gap in bookkeeping is not data loss, and must not block a write.

        Failing here would make every future Odoo release break the studio for
        everyone the moment it added a field, whether or not anybody used it.
        """
        package = self.make_package()
        self.build_demo_content(package)
        view = self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project"), ("type", "=", "form")], limit=1
        )
        serializer = self._view_serializer(package)
        with self._without_priority(serializer):
            # 'priority' is at its default, so nothing is lost by omitting it.
            node = serializer._serialize(view, "%s.view_x" % package.name)
        # `is not None`, not a truth test: an lxml element with no children is
        # falsy, and testing it warns about exactly that confusion.
        self.assertIsNotNone(node)

    def test_demo_content_still_renders(self):
        """The guard must not fire on anything the studio itself builds."""
        package = self.make_package()
        self.build_demo_content(package)
        rendered = package._render_files()
        self.assertIn("models/x_studio_project.xml", rendered)


@tagged("post_install", "-at_install")
class TestReferencePortability(StudioCase):
    """A raw id in a file is a bug waiting for the next database.

    Odoo has two shapes of it. ``fields.Reference`` stores ``"model,id"`` and
    core's importer resolves a plain ``ref=`` into exactly that
    (``convert.py:405``). ``fields.Many2oneReference`` stores a bare integer and
    names its model in a companion field, so it needs ``eval="ref(...)"`` -- but
    it *is* resolvable, which is why it is emitted rather than refused.
    """

    def test_a_reference_field_is_emitted_as_an_xmlid(self):
        package = self.make_package()
        self.build_demo_content(package)
        model = self.env["ir.model"]._get("x_studio_project")
        action = self.env["ir.actions.server"].create(
            {
                "name": "Point at a partner",
                "model_id": model.id,
                "state": "object_write",
                "update_path": "x_name",
                "resource_ref": "res.partner,%d" % self.env.ref("base.main_partner").id,
            }
        )
        package._assign(action)
        rendered = package._render_files()
        emitted = "".join(rendered.values())
        self.assertIn('name="resource_ref"', emitted)
        self.assertIn("base.main_partner", emitted)
        self.assertNotIn(
            'name="resource_ref" ref="%d"' % self.env.ref("base.main_partner").id,
            emitted,
            "a raw id would not survive a fresh install",
        )

    def test_a_many2one_reference_resolves_through_its_model_field(self):
        """base.automation.trg_field_ref used to fail the write outright.

        ``on_tag_set`` is the trigger that populates it, and its companion
        ``trg_field_ref_model_name`` only computes for that trigger and
        ``on_stage_set`` -- so the model name really does depend on the rest of
        the record, which is exactly what the helper has to read.
        """
        if "base.automation" not in self.env:
            self.skipTest("base_automation is not installed")
        package = self.make_package()
        self.build_demo_content(package)
        model = self.env["ir.model"]._get("res.partner")
        category = self.env["res.partner.category"].create({"name": "Studio Tag"})
        self.env["ir.model.data"].create(
            {
                "module": package.name,
                "name": "category_studio_tag",
                "model": "res.partner.category",
                "res_id": category.id,
            }
        )
        automation = self.env["base.automation"].create(
            {
                "name": "On tag",
                "model_id": model.id,
                "trigger": "on_tag_set",
                "trg_field_ref": category.id,
            }
        )
        self.addCleanup(self.env["base.automation"]._unregister_hook)
        if not automation.trg_field_ref_model_name:
            self.skipTest("res.partner exposes no tag field for this trigger")
        package._assign(automation)
        emitted = "".join(package._render_files().values())
        self.assertIn("ref('category_studio_tag')", emitted)

    def test_an_act_window_res_id_is_emitted_as_an_xmlid(self):
        """A raw primary key means a different record in the next database."""
        package = self.make_package()
        self.build_demo_content(package)
        partner = self.env.ref("base.main_partner")
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "One partner",
                "res_model": "res.partner",
                "view_mode": "form",
                "res_id": partner.id,
            }
        )
        package._assign(action)
        emitted = "".join(package._render_files().values())
        self.assertIn("ref('base.main_partner')", emitted)
        self.assertNotIn('name="res_id" eval="%d"' % partner.id, emitted)


@tagged("post_install", "-at_install")
class TestAccessCsvOptionalColumns(StudioCase):
    def test_the_active_column_appears_only_when_it_says_something(self):
        """An archived ACL must not come back granted, and an ordinary package
        must not carry a column of constant 1s in every diff."""
        package = self.make_package()
        self.build_demo_content(package)
        csv = package._render_files()["security/ir.model.access.csv"]
        self.assertNotIn("active", csv.splitlines()[0])

        access = self.env["ir.model.access"].search(
            [("model_id.model", "=", "x_studio_project")], limit=1
        )
        access.active = False
        csv = package._render_files()["security/ir.model.access.csv"]
        header, *rows = csv.splitlines()
        self.assertIn("active", header)
        self.assertTrue(any(row.endswith(",0") for row in rows))


@tagged("post_install", "-at_install")
class TestServerActionCoverage(StudioCase):
    def test_a_webhook_action_keeps_its_url(self):
        """Regression: state='webhook' serialized with no URL at all."""
        package = self.make_package()
        self.build_demo_content(package)
        model = self.env["ir.model"]._get("x_studio_project")
        action = self.env["ir.actions.server"].create(
            {
                "name": "Notify",
                "model_id": model.id,
                "state": "webhook",
                "webhook_url": "https://example.invalid/hook",
            }
        )
        package._assign(action)
        emitted = "".join(package._render_files().values())
        self.assertIn("https://example.invalid/hook", emitted)

    def test_a_rule_owned_action_keeps_its_usage(self):
        """usage is set from the form's context, never computed, so losing it
        turns an automation's action back into a standalone one."""
        package = self.make_package()
        self.build_demo_content(package)
        model = self.env["ir.model"]._get("x_studio_project")
        action = self.env["ir.actions.server"].create(
            {
                "name": "Owned by a rule",
                "model_id": model.id,
                "state": "code",
                "code": "pass",
                "usage": "base_automation",
            }
        )
        package._assign(action)
        emitted = "".join(package._render_files().values())
        self.assertIn("base_automation", emitted)


@tagged("post_install", "-at_install")
class TestSkipOverridesDoNotHideFields(StudioCase):
    """The blind spot the completeness guard cannot cover.

    A field in ``_studio_fields`` counts as accounted for, so
    ``_unclassified_fields`` says nothing about it -- even when a
    ``_should_skip`` override suppresses it unconditionally and it is never
    written at all. That is how ``ir.ui.view.type`` came to be dropped from
    every record: the comment said Odoo would infer it, and Odoo does, but only
    from ``inherit_id.type`` or the arch's root tag, raising outright when the
    tag is not a view type (``ir_ui_view.py:498-507``).
    """

    def test_a_qweb_view_keeps_its_type(self):
        """Root tag <t> is not a view type, so inference raises on load."""
        package = self.make_package()
        self.build_demo_content(package)
        view = self.env["ir.ui.view"].create(
            {
                "name": "studio.qweb.template",
                "type": "qweb",
                "key": "%s.some_template" % package.name,
                "arch": '<t t-name="something"><div>hello</div></t>',
            }
        )
        package._assign(view)
        serializer = self.env["studio.serializer.ir.ui.view"].with_context(
            studio_package=package.name
        )
        node = serializer._serialize(view, "%s.view_qweb" % package.name)
        emitted = {child.get("name") for child in node}
        self.assertIn(
            "type",
            emitted,
            "a qweb view whose type is omitted fails to load with "
            "\"Invalid view type: 't'\"",
        )

    def test_an_ordinary_view_still_omits_its_type(self):
        """<form> infers to 'form', so emitting it would be pure diff noise."""
        package = self.make_package()
        self.build_demo_content(package)
        view = self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project"), ("type", "=", "form")], limit=1
        )
        serializer = self.env["studio.serializer.ir.ui.view"].with_context(
            studio_package=package.name
        )
        node = serializer._serialize(view, "%s.view_form" % package.name)
        self.assertNotIn("type", {child.get("name") for child in node})

    def test_a_non_qweb_view_keeps_a_key_it_was_given(self):
        """website's copy-on-write assigns a key to whatever it edits, and the
        key is how a multi-website database resolves views."""
        package = self.make_package()
        self.build_demo_content(package)
        view = self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project"), ("type", "=", "form")], limit=1
        )
        view.key = "%s.carried_key" % package.name
        serializer = self.env["studio.serializer.ir.ui.view"].with_context(
            studio_package=package.name
        )
        node = serializer._serialize(view, "%s.view_form" % package.name)
        self.assertIn("key", {child.get("name") for child in node})
