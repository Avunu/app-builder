## Next

- **A report is edited by clicking a value, not by writing prose.** Placing a
  value and printing a table of child rows are gestures now, reachable from the
  Reports list through Edit Layout, and a tour drives the whole path. What a
  click can reach is what qweb branded, which in community is `t-field` and
  nothing else (`ir_qweb_fields.py:101`) — so a value is selectable and the
  prose around it is not, because that prose is not a node the builder put
  there. Editing the prose, a `/` powerbox and dragging a field into running
  text are the document half, and they need the mapping from a rich-text edit
  back to an xpath that nothing here has yet.
- **Conditional blocks in reports** — `t-if` / `t-elif` / `t-else` are editable
  as source but have no gesture and no preview switch, which is the same limit
  Odoo documents for its own editor.
- **Drag-and-drop reaches form, list and kanban; not yet an inline sub-view.**
  The console drops fields, components and moves in place on all three, with
  the server naming every node of the combined arch so "what did you drop it
  into" is answered by construction. What it does not do is drop into an
  embedded one2many list or form: those nodes belong to another model, and the
  palette would have to offer that model's fields. They are shown, and a click
  inside one selects the field that holds it.
- **Automations stop short of the composer on purpose.** The wizard creates the
  `ir.actions.server` / `base.automation` pair, and `studio.automation.action_open`
  opens Odoo's own form scoped to the model in front of you with a package in
  context — a second copy of that form would drift from it on the first release.
- **Group-bys and the search view's own three lists are still one field each.**
  A filter can now carry any condition the builder can express; a group-by is
  still a field and a context, which is all a group-by is. What has no gesture
  is a *second* level -- group by stage, then by salesperson -- and Odoo's own
  search view expresses that by the order the user clicks them rather than in
  the arch, so there may be nothing here to build.

## Known limits

- **A condition is a flat list or it is source.** `studio.domain` shows a domain
  as rows joined by all-of or any-of, and refuses anything that groups its terms
  or negates one — `['|', '&', a, b, c]` binds differently from a flat list, so
  there is no honest flat rendering of it. The refusal is the feature: a builder
  that flattened it would rewrite the rule the moment somebody touched an
  unrelated row, and the rewrite would look like an ordinary edit.
- **A field dropped on a core model is a live `x_` field; on a model this
  package defines in Python it is staged.** The first is created the moment it
  lands, with its widget, for every type the picker offers; a type that needs
  a conversation — a selection's values, a one2many's inverse, a related path —
  has it before anything is created. The second appears as a pending ghost
  exactly where it was dropped and becomes real on Apply, because a clean-named
  field is a class attribute and needs the class re-imported.
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
- **A pending field is a ghost, not a field.** The canvas cannot render a
  column the registry does not have, so a staged field is drawn as an in-flow
  placeholder at its anchor -- selectable, draggable, honest about being
  pending -- and the tray carries the rest of the difference until Apply.
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
  and redo are the counterweight, one edit at a time per view; undoing
  something older would silently discard everything done since, so it is
  refused, and a new edit discards the redo tail. The stack is per view, not
  per person, which is why every entry names its author.
- **A kanban card written with `t-esc` cannot be selected part by part.** Only a
  `<field>` puts its name in the DOM. Cards the builder generates use real
  fields for exactly this reason; existing ones are edited as source, and a
  click on such a part selects the card that holds it.
- **A search view is edited as three lists, not by clicking.** It has no
  rendering of its own — it furnishes another view's control panel — so it is
  edited as searchable fields, filters and group-bys, and previewed inside a
  real list so the menus on screen are the ones being edited.
- **A calendar is edited as settings, not by clicking.** It draws events rather
  than fields, so there is no per-node DOM to aim at. What a calendar *is* lives
  in its root attributes, which is what the panel edits.
