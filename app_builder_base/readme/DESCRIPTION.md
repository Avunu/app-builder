The engine behind App Builder: it turns records into source files, keeps the two
in agreement, and is honest when they diverge.

A **studio package** is one Odoo addon directory managed as a record. Everything
the builder creates is assigned to a package and written into it as ordinary
`.xml`, `.csv` and `.py` files you can review, diff and commit.

Odoo community has a complete XML *import* path and no export path at all, so
the serializer here is the novel part. Its output is deterministic by declared
rule — attributes in a fixed order, records ordered by serializer then xmlid
rather than by database id, relations always emitted as `ref="xmlid"` — so an
unchanged package re-serializes byte-identically and produces an empty diff.

This module on its own gives you packages, serialization, drift detection,
module reload and graduate-to-code. The builder UIs live in `app_builder_model`,
`app_builder_view` and `app_builder_ui`.
