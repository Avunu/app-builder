# App Builder: PDF reports

Create PDF reports, and edit existing ones as inheriting views.

Build PDF reports, and edit the ones that came with Odoo.

**New reports.** From the console's Reports pane: pick a layout — External for something
a customer receives, Internal for something used in the building, Blank for a label or a
preprinted form — and name it. You get an action, a qweb template and a _Print_ menu
entry, written into your builder package as source; the card's _Edit layout_ opens the
template on the canvas.

**Existing reports, patched rather than copied.** This is the half Odoo Studio cannot
do. Its own documentation tells you to duplicate the standard report and edit the
duplicate — which is why the copy stops receiving Odoo's fixes the day it is made, and
why the database then fights every upgrade.

A report template is an `ir.ui.view` of type qweb, so it inherits like any other view.
Editing a standard report here leaves it untouched and puts your change in an inheriting
view of your own, as an `<xpath>`. That is what Odoo's own addons do to each other:
`sale_product_matrix` patches `sale.report_saleorder_document` exactly this way. Your
change is a reviewable patch, and the report underneath keeps getting fixed.

The editor is the same one used for forms and lists, because a report template is the
same kind of record. A patched report says so on its card, and _Reset layout_ deletes
the patch; the original was never changed.

## Credits

**Author:** Avunu LLC

**Contributors:**

- Kevin Shenk \<kevin@avu.nu\> (https://avu.nu)

## Licence

AGPL-3. See the [repository licence](../LICENSE).
