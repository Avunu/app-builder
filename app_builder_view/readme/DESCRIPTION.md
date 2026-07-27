Edit views visually. Every change becomes an **inheriting view**, never a
rewrite.

Odoo Studio mutates view arch in place, which is why a Studio-customised database
fights every upstream upgrade. Here each edit is emitted as an `<xpath>` inside a
single extension view per (base view, package) at `priority=99` — core's own
convention for last-loaded views. The result reads like a patch a developer would
have written, survives upstream changes to the base view, and is reviewable in
git.

The editor never asks you to type an xpath: the target is picked from a tree of
the view's nodes computed on the server, preferring identifying predicates
(`//field[@name='x']`) over positional ones (`//div[3]`) so a picked target
survives another module extending the same view.

Invalid edits are rejected by Odoo's own view validator before anything is
written, and its message is shown verbatim.
