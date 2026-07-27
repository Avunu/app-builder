Build the rest of an addon visually: menus, window actions, access rules, record
rules and automations — all written to source.

Adds guided wizards for:

- **New Menu** — creates a window action and its menu item together.
- **New Access Rule** — an `ir.model.access` line, written into the addon's
  `security/ir.model.access.csv` in the conventional column order.
- **New Automation** — a `base.automation` and its server action. The Python runs
  in Odoo's sandbox and is stored as data, so an automation you add here works
  without a code file or a restart.

Record rules (`ir.rule`) assigned to a package are written to
`security/<model>_security.xml`.

Secrets are never committed: an automation's `webhook_uuid` differs per database
and is deliberately excluded from the generated files.
