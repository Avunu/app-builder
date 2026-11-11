# App Builder for Odoo

[![License: AGPL-3](https://img.shields.io/badge/license-AGPL--3-blue.png)](http://www.gnu.org/licenses/agpl-3.0-standalone.html)

An open-source alternative to Odoo Studio whose output is **ordinary source code from the first keystroke**.

Odoo Studio keeps everything in the database and offers a one-time, irreversible "export to module". Once a developer touches the exported code, they can never go back to the visual tool. App Builder inverts that: every visual change writes both the database record and the corresponding file in a real addon directory, in the same transaction. The builder and the codebase are two views of one artifact.

```
                    ┌──────────────────────────────┐
   visual edit ────▶│  DB record   +   source file │────▶ git diff / review / CI
                    └──────────────────────────────┘
                                   ▲
   hand-edited file ───────────────┘   (drift detected, one-click reload)
```

## The core idea

"Files are the source of truth" naively means a module upgrade on every drag-drop — 1–3s per edit, unusable. It doesn't have to, because Odoo already makes the database side free:

-   `IrModel.create` rebuilds the registry synchronously, so a new model and its table are live **in the same transaction** (`ir_model.py:404-416`).
-   With `--dev=xml`, `ir.ui.view._compute_arch` reads arch from disk whenever `arch_updated` is False, so a file-authored view goes live with no DB write.

So each operation writes the record _and_ the file atomically, and a full `update_list()` + `button_immediate_upgrade()` becomes the verification and repair path rather than the edit path.

That is only legitimate if loading the files reproduces the database exactly, which is the invariant the suite asserts:

```
load_from_files(serialize(db_state)) == db_state
```

`test_roundtrip.py` proves it by serializing, wiping every record, reloading through Odoo's own `convert_xml_import`, and asserting byte-identical output. Every record id changes across that wipe, so passing also proves no raw ids leak into generated files.

## Why the output is reviewable

Studio's export is unreadable in review because ordering follows dict iteration and record ids. Everything here follows a _declared_ rule, so an unchanged package re-serializes byte-identically and yields an empty `git diff`:

-   attributes in a declared priority order, then alphabetically;
-   records ordered by serializer sequence then xmlid — never by id;
-   relations always as `ref="xmlid"`; a referenced record with no xmlid is a hard error, not a silently emitted integer;
-   fields equal to their declared default omitted — defaults are _evaluated_, since Odoo wraps every scalar default in a lambda (`fields.py:511`);
-   mixed content (QWeb bodies, HTML) never reflowed; only structural elements are re-indented;
-   rendering pins `lang=None`, so output never depends on who clicked save.

Edits to existing views become **inheriting views** at `priority=99` — core's own convention (`ir_ui_view.py:658`) — never rewrites. Manifest `depends` are derived from the refs actually emitted, and data files are ordered so every ref resolves when its file loads.

## Python from the first save, but only a block of it is ours

A new model is a real `models.Model` class immediately — no `x_` prefix, no later conversion step. What the builder owns is a marker-delimited block inside the class; everything else in that file is yours from the moment it exists:

```python
class WorkshopJob(models.Model):
    # begin: builder-generated schema
    _name = "workshop.job"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "sequence, id"

    name = fields.Char(string="Name", required=True, tracking=1)
    partner_id = fields.Many2one("res.partner", string="Customer")
    # end: builder-generated schema

    @api.constrains("name")           # anything at all out here
    def _check_name(self):
        ...
```

Writing is a pure string splice between the markers — the same approach [Frappe's `TypeExporter`](https://github.com/frappe/frappe/blob/develop/frappe/types/exporter.py) uses — so the builder never parses, reads or rewrites the rest of the file. Add a metaclass, a `@property`, a decorator nobody has heard of: the builder keeps working. Reading parses only the block, which is text the builder generated, so a failure there is a loud error about our own region rather than a model that quietly locks itself out.

**This is what makes it not an export.** Odoo Studio's "export to module" is one-way: touch the code and you can never go back to the visual tool. Here there is no door to close.

Three things make the generated class lossless rather than a rewrite:

-   the xmlids Odoo's reflection assigns to a code-defined model are _identical_ to the ones the builder emitted (`model_xmlid` / `field_xmlid` / `selection_xmlid`), so nothing is orphaned and `_process_end` reaps nothing;
-   a sandboxed `compute` string is promoted to a real method with a real `@api.depends`;
-   metadata rows are _reclassified_ (`state` manual → base), never deleted. Deleting would be doubly catastrophic: `ir.model.fields.unlink` calls `_drop_column` and would destroy user data, and every `model_id` in Odoo is `ondelete='cascade'`, so dropping the `ir.model` row silently takes the access rules and automations with it.

Adding a field means re-importing the class, so edits batch behind an explicit **Apply** — one reload per changeset rather than one per field. **Home → Adopt a model** brings an older `x_` model under the same management; it is a migration for what came before, not a milestone.

## Read-only in production is a feature

The editor gates on `os.access(root_path, W_OK)`. Against a Nix-store build or any read-only deployment it disables itself with an explanatory banner instead of failing. You build in development, ship through git, and deploy immutably.

## Available addons

| addon | summary |
| --- | --- |
| [app_builder](app_builder) | Open-source visual builder whose output is real source code |
| [app_builder_base](app_builder_base) | Engine for visually built Odoo modules that live in source control |
| [app_builder_model](app_builder_model) | Visually build models and fields that are written to source |
| [app_builder_view](app_builder_view) | Edit views visually; every change becomes an inheriting view in source |
| [app_builder_ui](app_builder_ui) | Build menus, actions, access rules and automations into source |
| [app_builder_report](app_builder_report) | Create PDF reports, and edit existing ones as inheriting views |
| [app_builder_mail](app_builder_mail) | Write mail and SMS settings into source alongside the rest |
| [app_builder_approval](app_builder_approval) | Turn on tier validation in the builder, and write the rules to source |
| [app_builder_approval_formula](app_builder_approval_formula) | Write Python-conditioned approval rules to source |

## Development

This is an [odoo-nix](https://github.com/Avunu/odoo-nix) repository of addons (addons mode) that follows [Avunu's Odoo standards profile](https://github.com/Avunu/odoo-standards-profile). OCB and OCA's `server-ux` are flake inputs, pinned in `flake.lock`.

```sh
direnv allow                 # or: nix develop --no-pure-eval
odoo db provision            # install this repository's addons
devenv up                    # PostgreSQL, Odoo, Mailpit and the TypeScript watcher
odoo-nix gate lint           # in `nix develop --no-pure-eval .#odoo-nix-lint`
odoo-nix gate test           # every addon's tests, with coverage
```

### TypeScript

The console is written in TypeScript, and the compiled `.js` is not committed. Each addon with TypeScript has a `package.json` whose `build` script runs esbuild over `static/**/*.ts`, writing each `.js` beside its source. That output stays under `static/src` and `static/tests` on purpose, not `static/dist`: esbuild only erases types, and Odoo's own transpiler still has to load the result as an `@odoo-module`.

- **Production:** `nix build .#default` runs those builds through [odoo-nix's addon frontends layer](https://github.com/Avunu/odoo-nix/blob/main/docs/development/frontend.md) and lays the output into the deployed tree and the addons' wheels.
- **The shell:** entering it installs and builds, so a fresh clone serves a working console; `devenv up` keeps rebuilding through each addon's `watch` script; `odoo module build` builds by hand.
- **Type checks:** esbuild checks nothing. `prek run -c .pre-commit-config.yaml --hook-stage manual -a` runs pyright, tsc and the type-aware eslint in the dev shell, as `typecheck.yml` does in CI.

See [DESIGN.md](DESIGN.md) for the full architecture, the core machinery it drives, and the traps it works around — three Odoo caches that are never invalidated, two reserved module names, the `ir_cron` lock `button_immediate_upgrade` takes, and the findings from an adversarial review. See [TYPING.md](TYPING.md) for how the Python and TypeScript are typed and checked, what was found doing it, and the traps that cost time. That file is a history: its build and CI details predate the move to odoo-nix, which the note at its top describes.

## Licence

AGPL-3. See [LICENSE](LICENSE).

## Credits

**Copyright:** Avunu LLC

**Contributors:** Kevin Shenk <[kevin@avu.nu](mailto:kevin@avu.nu)\>

App Builder for Odoo is an independent project, not affiliated with or endorsed by Odoo S.A. Odoo is a trademark of Odoo S.A.
