Build PDF reports, and edit the ones that came with Odoo.

**New reports.** Name it, pick what it prints and pick a layout — External for
something a customer receives, Internal for something used in the building,
Blank for a label or a preprinted form. You get an action, a qweb template and
a *Print* menu entry, written into your studio package as source.

**Existing reports, patched rather than copied.** This is the half Odoo Studio
cannot do. Its own documentation tells you to duplicate the standard report and
edit the duplicate — which is why the copy stops receiving Odoo's fixes the day
it is made, and why the database then fights every upgrade.

A report template is an `ir.ui.view` of type qweb, so it inherits like any other
view. Editing a standard report here leaves it untouched and puts your change in
an inheriting view of your own, as an `<xpath>`. That is what Odoo's own addons
do to each other: `sale_product_matrix` patches `sale.report_saleorder_document`
exactly this way. Your change is a reviewable patch, and the report underneath
keeps getting fixed.

The editor is the same one used for forms and lists, because a report template
is the same kind of record.
