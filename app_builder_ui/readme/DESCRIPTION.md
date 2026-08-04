Build the rest of an addon visually: menus, window actions, access rules, record
rules and automations — all written to source.

**Automations** and **Webhooks** are reachable from the Studio menu and from the
cog menu of any screen, where they show the rules for *that* model rather than
the whole database's list under Settings → Technical. What opens is Odoo's own
automation form, not a copy of it: that form is trigger-aware in a way that took
years to get right, and a second copy would drift from it on the first release
and be wrong in ways nobody could see. What the studio adds is the part Odoo has
no opinion about — a rule created from here belongs to a package, so it lands in
source instead of only in this database.

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
