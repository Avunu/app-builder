Build the rest of an addon visually: menus, window actions, access rules, record
rules and automations — all written to source.

Each is a pane of the studio console, scoped to the model in front of you:

- **Automations** and **Webhooks** — the model's rules as cards, each with its
  sentence: when, only if, then what. New starts from a template (when a record
  is saved, set a field, after a delay, notify a URL, a webhook in); the
  sidebar edits the trigger, the condition — with how many records it matches
  today — and the steps, added by kind, reordered, removed. A rule another
  module defines is shown, not edited; a copy into your package starts
  switched off. A webhook's URL is shown with a *Rotate secret* action.
- **Access Control** — one line per group, read / write / create / delete as
  toggles, written to `security/ir.model.access.csv` in the conventional
  column order. Lines add up, so a line Odoo ships is shown and never edited.
- **Filter Rules** — record rules, with a template for the usual ones (only
  their own records, their company) and a condition builder that says what it
  matches; written to `security/<model>_security.xml`.
- **Menu** — the package's menus as a tree under the apps they hang from, an
  app or a submenu made with the list+form action it opens, moved among its
  siblings, written to `views/menus.xml`.

Odoo's own form for any of them is one button, *Advanced…*; what it saves is
written to the package too.

**Promote to source.** An automation's Python lives in a text column evaluated
by `safe_eval`. That is the right trade for getting started and the wrong place
for it to stay: nothing imports it, so no linter reads it, no test covers it and
no reviewer sees it in a diff — and `safe_eval` forbids enough of Python that
what survives there is written around the sandbox rather than for the problem.

One button moves the body into a real method on a class in your package and
leaves the action calling it. The sandboxed string that remains is one line
long. Odoo Studio's answer is that this is simply how automations are.

Secrets are never committed: an automation's `webhook_uuid` differs per database
and is deliberately excluded from the generated files.
