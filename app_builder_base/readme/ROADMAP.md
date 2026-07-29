## Next

- **The composer client.** A client action with a resizable sidebar and a live
  preview of the model being built: a pending-changes tray, and a field editor
  modelled on core's `properties` field popover. The server side it sits on —
  the edit buffer, the field-type catalogue, apply and diff preview — is in
  place; what is missing is the OWL.
- **Relationships.** A one2many that creates its own inverse many2one and places
  itself on the parent form. Nothing does this today, and every real app needs it
  within the first five minutes.
- **Drag-and-drop.** Deliberately *after* the composer rather than instead of it.
  It is one gesture in a vocabulary, not the vocabulary.

## Known limits

- **A new column needs the class re-imported**, so edits batch behind an explicit
  Apply — one reload per changeset rather than one per field. This is not a
  preference: a `state='manual'` field cannot have a clean name (a Postgres CHECK
  constraint, plus `BaseModel._add_field`), so a clean-named field has to be a
  class attribute. Adding a field to a *core* model stays instant, because there
  the `x_` prefix is expected anyway.
- **Multi-worker deployments cannot reload in place** and are told so rather than
  served badly: the other workers rebuild their registry from Python they still
  hold in `sys.modules`, so they would rebuild against a stale class. Studio
  editing is a single-process development activity; production runs read-only.
- **Adopting two custom models that reference each other** in the same operation
  is untested; adopt them one at a time.
- **`many2one_reference` cannot be serialized portably** — its value is a raw
  database id — and is refused rather than silently corrupted. `properties` and
  `json` are refused too, each with the reason shown in the field picker.
- **The view editor picks nodes from a server-computed tree.** Locators are minted
  server-side against the combined arch, never in the browser: the arch a client
  receives is a per-user projection, with nodes removed by group rights and whole
  subviews grafted in, so a path derived from it can be wrong for somebody else.
