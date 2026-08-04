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

Fields, buttons, tabs and groups can be added and removed, not only configured —
and because every edit becomes a patch, that works on core screens as readily as
on your own. Where a new node lands is decided from what you have selected: a
container takes a child, anything else takes a sibling, and the panel says which
before you click.

The editor never asks you to type an xpath: the target is picked from a tree of
the view's nodes computed on the server, preferring identifying predicates
(`//field[@name='x']`) over positional ones (`//div[3]`) so a picked target
survives another module extending the same view.

Invalid edits are rejected by Odoo's own view validator before anything is
written, and its message is shown verbatim.
