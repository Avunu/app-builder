Edit views visually. Every change becomes an **inheriting view**, never a
rewrite.

Odoo Studio mutates view arch in place, which is why a Studio-customised database
fights every upstream upgrade. Here each edit is emitted as an `<xpath>` inside a
single extension view per (base view, package) at `priority=99` — core's own
convention for last-loaded views. The result reads like a patch a developer would
have written, survives upstream changes to the base view, and is reviewable in
git.

Which view types you can add is not a list this addon keeps. It comes from
`ir.ui.view.get_view_info()`, the registry every module extends when it
contributes one — so a site that installs `web_timeline` sees Timeline, and one
running enterprise sees Gantt and Cohort, without this addon depending on any of
them. A type the builder has no scaffold for is listed and disabled with that as
the reason, because "we cannot make one yet" is true and different from "no such
thing".

Editing happens in the **studio console**, which is the whole studio: Home for
the package, the Views pane for this — full-screen, the real view rendered on a
canvas with a real record in it, and a sidebar of Add, View and Properties.
Fields, buttons, tabs, groups and columns are dragged from the sidebar onto the
view and land exactly where they are dropped; what is already there is dragged
to move it, between groups, across tabs, into a kanban card. Because every edit
becomes a patch, that works on core screens as readily as on your own. Undo
and redo walk the edits back and forward, and every change is on disk before
the status pill says so.

The console never asks you for an xpath and never computes one in the browser.
The server names every node of the view before it is rendered and edits the
node you pointed at, preferring identifying locators (`//field[@name='x']`)
over positional ones (`//div[3]`) so an edit survives another module
extending the same view — and if the view changed under you, the drop is
refused, the canvas refreshed, and you are asked to try again rather than have
it land somewhere else.

Invalid edits are rejected by Odoo's own view validator before anything is
written, and its message is shown verbatim.
