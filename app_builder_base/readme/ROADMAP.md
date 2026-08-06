## Next

- **The report editor has the gestures, not the rich text.** Placing a value
  and printing a table of child rows are operations now, and both emit
  `<xpath>` into an inheriting view like every other edit. What is missing is
  the document half: a `/` powerbox, dragging a field into running text, and
  editing the surrounding prose in place. Odoo's `html_editor` is in community
  18.0, so the parts exist; what does not is the mapping from a rich-text edit
  back to an xpath, and that mapping is the whole reason the edit stays
  reviewable — a locator derived from rendered output points at whatever that
  reader's language, company layout and access rights produced.
- **Conditional blocks in reports** — `t-if` / `t-elif` / `t-else` are editable
  as source but have no gesture and no preview switch, which is the same limit
  Odoo documents for its own editor.
- **Drag-to-reorder beyond list columns** — form fields between groups, kanban
  card contents. The move operation and the gesture both exist now; what each
  case needs is a sensible answer to "what did you drop it *into*". Adding works
  by clicking, anchored on the selection, for the same reason.
- **A new field from inside the view editor.** Adding an *existing* field is
  there; creating one still means the composer, or the New Field wizard for a
  core model.
- **A feature that asks for a view still only gets the ones the builder can
  scaffold.** `Feature.views` records the intent — Date & Calendar wants a
  calendar, Pipeline stages wants a kanban — and the app builder activates what
  it has scaffolds for.
- **Record rules and automations**, in the composer rather than in the technical
  menus, where they would have the context that makes them answerable.
- **Richer filters.** Search filters are generated from a field and a condition
  (is set, is not set, is true, is false). A domain with several terms still
  belongs in the source; a domain *builder* would be the way to change that.

## Known limits

- **A value that needs a module is only recorded where a bridge says so.**
  `_value_depends` maps a field value to the module that contributes it, so a
  rule using `review_type="expression"` pulls `base_tier_validation_formula`
  into the manifest. Only the values a bridge declares are covered; a selection
  value from an unbridged module still produces a file that loads elsewhere as
  an invalid value.
- **A module with no bridge loses its fields from generated source.** The static
  coverage test warns, naming each one — `website` alone adds about a dozen to
  `ir.ui.view` — and fails only for the modules the studio itself depends on,
  which are the ones it is answerable for. The runtime guard still refuses to
  write a record that actually sets one, so the data is protected either way;
  what is missing is the bridge, and the warning is the to-do list for writing
  it.
- **Serializing under `--dev=xml` can read the arch off disk.** `_compute_arch`
  prefers the file whenever `arch_updated` is False, so a view whose file and
  database have diverged serializes the file's version. The reload path is what
  makes that divergence detectable; drift detection is the answer to it, not the
  emitter.
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
- **`many2one_reference` cannot be built here**, because the field needs a
  `model_field` companion naming the model its id belongs to and the picker has
  no way to declare one. An existing one serializes fine — the companion is
  read, and the id leaves as an xmlid rather than a raw number. `properties` and
  `json` are refused outright, each with the reason shown in the field picker.
- **The view editor picks nodes from a server-computed tree.** Locators are minted
  server-side against the combined arch, never in the browser: the arch a client
  receives is a per-user projection, with nodes removed by group rights and whole
  subviews grafted in, so a path derived from it can be wrong for somebody else.
- **Placement only edits views the package owns.** A field added to a model whose
  form belongs to another module is created but not placed automatically — the
  view editor is where it goes onto somebody else's screen, as an inheriting
  view, on purpose.
- **View edits are live and shared.** A view is data, so there is no reload to
  batch behind and no Apply — an edit is visible to everyone immediately. Undo
  is the counterweight, and it walks back one edit at a time; undoing something
  older would silently discard everything done since, so it is refused.
- **A kanban card written with `t-esc` cannot be selected part by part.** Only a
  `<field>` puts its name in the DOM. Cards the builder generates use real
  fields for exactly this reason; existing ones are edited as source, and the
  editor says so rather than absorbing the click.
- **A search view is edited as three lists, not by clicking.** It has no
  rendering of its own — it furnishes another view's control panel — so it is
  edited as searchable fields, filters and group-bys, and previewed inside a
  real list so the menus on screen are the ones being edited.
- **A calendar is edited as settings, not by clicking.** It draws events rather
  than fields, so there is no per-node DOM to aim at. What a calendar *is* lives
  in its root attributes, which is what the panel edits.
