## Known limits

- **Inline sub-views are shown but not droppable.** A one2many's embedded list
  or kanban is rendered on the canvas, but a click inside it selects the field
  that holds it: its nodes belong to another model and are edited in that
  model's own view.
- **A kanban card written with `t-esc` has no parts to aim at.** Only a
  `<field>` puts anything addressable in the DOM; a click on such a part
  selects the nearest node that is one -- the card itself, as a rule -- and
  the parts are edited as source.
- **Models that patch their arch at read time are shown as written.** An
  analytic line's plan columns are inserted by the model in `_get_view()` —
  which Odoo's own studio also opts out of — and the canvas shows the view as
  it is defined, not as that model decorates it.
- **Master's `card` view type is not handled yet.** From the next Odoo, a
  kanban may point at a card that lives in a separate view; the node table
  reserves `view_id` for it (see `FORWARD_COMPAT.md` at the repository root).
- **Two consoles on one package** are serialised only by the database
  transaction and the arch-version check: the second drop on a view the first
  just changed is refused and the canvas refreshed, never written twice.
- **The 19.0 port has been read, not run.** Every version difference the
  console knows is in one file (`static/src/console/compat.js`), each with the
  core lines that decide it, and the checklist for the Owl 3 branch is in
  `FORWARD_COMPAT.md`; a run against a 19 server is still to do.
