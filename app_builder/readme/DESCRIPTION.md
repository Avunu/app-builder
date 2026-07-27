An open-source alternative to Odoo Studio whose output is **ordinary source code
from the first keystroke**.

Odoo Studio keeps everything in the database and offers a one-time, irreversible
"export to module". Once a developer touches the exported code, they can never go
back to the visual tool. App Builder inverts that: every visual change writes both
the database record and the corresponding file in a real addon directory, in the
same transaction. The builder and the codebase are two views of one artifact.

That means you can review a studio change as a normal `git diff`, hand-edit the
generated files and reload them back into the builder, ship customizations
through your existing branch/CI/deploy pipeline, and run production from a
read-only checkout where the builder disables itself.

Installing this module pulls in the whole suite:

- `app_builder_base` — the engine
- `app_builder_model` — model and field builder
- `app_builder_view` — view editor
- `app_builder_ui` — menus, actions, access rules and automations
