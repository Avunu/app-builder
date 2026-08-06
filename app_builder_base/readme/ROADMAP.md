## Next

- **The report editor is server-complete and has no client.** Placing a value
  and printing a table of child rows are operations — `add_report_field` and
  `add_report_table` — and no JS in the tree names either. The pane they would
  live in cannot draw a report: `_preview_for` returns the view's own type, the
  client mounts `<View type="qweb">`, and qweb is not a client-side view type.
  A report is a template, so the preview has to be its rendered *output*, and
  clicking it resolves through `data-oe-expression` rather than a node path:
  `inherit_branding` brands `t-field` and nothing else in community
  (`ir_qweb_fields.py:101`), node branding of rendered output is a `website`
  feature, and `ir.actions.report._render_template` forces branding off outright
  (`ir_actions_report.py:765`) — so the template is rendered through `ir.qweb`
  directly.
  The server half of that is built: `preview_html` renders the report's own
  output, `locate_expression` turns a clicked field back into a locator, and
  `body_anchor` answers "where does this go" when nothing was clicked. What is
  left is the client — showing that HTML in the preview pane, and offering the
  two operations. The document half — a `/` powerbox, dragging a
  field into running text, editing the surrounding prose — comes after that,
  not before it.
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
- **Record rules have no builder.** `studio.access.wizard` covers
  `ir.model.access` only; an `ir.rule` is captured into source once it exists
  and is never authored here. Automations are further along and deliberately
  stop short: the wizard creates the pair, and `studio.automation.action_open`
  opens Odoo's own form scoped to the model in front of you with a package in
  context, because a second copy of that form would drift from it on the first
  release. A domain on a rule is the same problem as a domain on a filter,
  which is why the two are one piece of work.
- **Richer filters.** Search filters are generated from a field and a condition
  (is set, is not set, is true, is false). A domain with several terms still
  belongs in the source; a domain *builder* would be the way to change that.

## Known limits

- **A PO entry for a term this package emits is the database's to state.**
  `_render_translations` reads the existing `i18n/<lang>.po` and keeps every
  entry it does not emit — a `.pot`-derived string from code, a term another
  workflow put there — but a msgid it does emit is rewritten from the record on
  the next save. Translate those in Odoo; editing them in the file is work the
  next gesture discards.
- **The generated PO files apply on install, not on upgrade.**
  `_update_translations` runs with `overwrite=config["overwrite_existing_translations"]`
  (`loading.py:236`), which is False unless the server was started with
  `--i18n-overwrite`, and the importer then lets an existing database value win.
  So a fresh install of the package picks the translations up — there is nothing
  to lose to — and editing `i18n/fr_FR.po` in an existing database changes
  nothing until you say so. This is how Odoo treats every addon's translations,
  not something this emitter chose, but it means the file is authoritative in
  exactly one direction.
- **A record id inside a string is written literally.** The emitter treats a
  domain, a context and a JSON default as opaque text, because they are Char
  columns — so `[('partner_id', '=', 7)]` on an `ir.rule`, a
  `{'default_partner_id': 7}` context on an action, or an `ir.default` whose
  `json_value` is a bare many2one id all leave as that number. `_ref_of` refuses
  to emit a raw id where a *field* points at a record, and none of that
  machinery reaches inside a string. In the next database the number means a
  different record or none, and the package reports clean.
- **Read-only is a filesystem fact, not a production check.** `writable` is
  decided by creating and removing a file in the package directory rather than
  by `os.access`, which answers True for root against a `0500` directory — the
  container default, and this project's own CI. Every write path asserts it
  first. But nothing detects a *production* deployment: an addons volume that
  happens to be writable reports `writable = True` and is not stopped. Building
  in development and shipping through git is a convention the studio supports,
  not one it enforces.
- **Tags and Lines are decided when the app is created.** Both are offered by
  the New Model wizard only, because a companion is a second model and
  `create_app` is the only thing that builds one — so adding Lines to an app
  that already exists means building a second app. Removing them is not offered
  either: taking `line_ids` off the parent would leave the line model, its
  table, its access rule and its file in place.
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
