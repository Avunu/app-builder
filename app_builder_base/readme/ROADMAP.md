## Next

- **Drag-to-reorder**, starting with list columns. The operation API supports
  `position="move"` already, and the selection layer knows what was grabbed —
  what is missing is only the gesture. Deliberately after click-to-edit rather
  than instead of it: dragging is one gesture in a vocabulary, not the
  vocabulary.
- **Search views.** The only view type the editor does not cover, because a
  search view has no standalone rendering to click — it lives in another view's
  control panel. It needs a list-shaped editor (fields, filters, group-bys)
  rather than the click-to-select spine.
- **Record rules and automations**, in the composer rather than in the technical
  menus, where they would have the context that makes them answerable.
- **Retire the old view editor.** `studio_editor.js` — a node list beside a
  free-text xpath box — is now redundant for list, form, kanban and calendar. It
  stays until search views are covered, then goes.

## Known limits

- **A new column needs the class re-imported**, so edits batch behind an explicit
  Apply — one reload per changeset rather than one per field. This is not a
  preference: a `state='manual'` field cannot have a clean name (a Postgres CHECK
  constraint, plus `BaseModel._add_field`), so a clean-named field has to be a
  class attribute. Adding a field to a *core* model stays instant, because there
  the `x_` prefix is expected anyway.
- **The preview shows the applied state, not the pending one.** A form cannot
  render a field the registry does not have, so the tray carries the difference
  rather than the preview pretending to.
- **Multi-worker deployments cannot reload in place** and are told so rather than
  served badly: the other workers rebuild their registry from Python they still
  hold in `sys.modules`, so they would rebuild against a stale class. Studio
  editing is a single-process development activity; production runs read-only.
- **The inverse of a related list can only be created on a model this package
  defines in Python.** Pointing at anything else needs a many2one that already
  aims back; the picker lists the candidates and says so when there are none.
- **Adopting two custom models that reference each other** in the same operation
  is untested; adopt them one at a time.
- **`many2one_reference` cannot be serialized portably** — its value is a raw
  database id — and is refused rather than silently corrupted. `properties` and
  `json` are refused too, each with the reason shown in the field picker.
- **The view editor picks nodes from a server-computed tree.** Locators are minted
  server-side against the combined arch, never in the browser: the arch a client
  receives is a per-user projection, with nodes removed by group rights and whole
  subviews grafted in, so a path derived from it can be wrong for somebody else.
- **Placement only edits views the package owns.** A field added to a model whose
  form belongs to another module is created but not placed; use the view editor,
  which emits an inheriting view for that case on purpose.
- **View edits are live and shared.** A view is data, so there is no reload to
  batch behind and no Apply — an edit is visible to everyone immediately. Undo
  is the counterweight, and it walks back one edit at a time; undoing something
  older would silently discard everything done since, so it is refused.
- **A kanban card written with `t-esc` cannot be selected part by part.** Only a
  `<field>` puts its name in the DOM. Cards the builder generates use real
  fields for exactly this reason; existing ones are edited as source, and the
  editor says so rather than absorbing the click.
- **A calendar is edited as settings, not by clicking.** It draws events rather
  than fields, so there is no per-node DOM to aim at. What a calendar *is* lives
  in its root attributes, which is what the panel edits.
