# App Builder for Odoo

[![License: AGPL-3](https://img.shields.io/badge/license-AGPL--3-blue.png)](http://www.gnu.org/licenses/agpl-3.0-standalone.html)

An open-source alternative to Odoo Studio whose output is **ordinary source code from the first keystroke**.

> **Status: beta, Odoo 18.0 only.** Seven addons declare `development_status: Beta` and the two approval addons `Alpha`; none claims Production/Stable. The only supported and tested series is **18.0** (OCB). Odoo 19.0 and later are not supported: [FORWARD_COMPAT.md](FORWARD_COMPAT.md) records a port that was read against the 19 sources but never run on a 19 server. The builder is a **development-time tool** for a single-process development database, not something to switch on in production. Read [Scope and limits](#scope-and-limits) before installing it, and [CHANGELOG.md](CHANGELOG.md) before upgrading.

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
-   With `--dev=xml`, `ir.ui.view._compute_arch` reads arch from disk whenever `arch_updated` is False, so a file-authored view goes live with no DB write. `--dev=xml` is Odoo's development flag; it is one more reason the builder belongs on a development server (see [Scope and limits](#scope-and-limits)).

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

The editor writes only where it is allowed to and able to, and says so when it is not. Against a Nix-store build or any read-only deployment it disables itself with an explanatory banner instead of failing. You build in development, ship through git, and deploy immutably.

"Able to" is tested by doing it: the builder creates and removes a temporary file in the package directory. `os.access` is not asked, because it answers for the real uid, cannot see an ACL or an immutable flag, and says yes to everything when Odoo runs as root, which is how most containers run it.

## Security

**A Builder Administrator can run arbitrary code as the Odoo process.** The builder writes Python into the addons path and imports it, which stock Odoo never lets a database administrator do. Treat the role as shell access to the server. Every `Settings` administrator has it.

For that reason writing code is **off by default** and is switched on outside the database, where no administrator account, stolen session or RPC call can reach it:

```sh
APP_BUILDER_ENABLE_WRITE=1        # in the server's environment, or
app_builder_enable_write = True   # in odoo.conf, under [options]
```

With the switch off every package is read-only, every change is refused with a sentence naming the switch, and the console still opens as a viewer. The development shell of this repository sets the variable, so `devenv up` and the test gate build packages as before.

Turn it on only where every `Settings` administrator is trusted with a shell: a developer's machine or a build environment. Leave it off in production, and mount the addons path read-only as well.

The supported deployment is one Odoo process (`workers = 0`) serving one database, used by administrators only. [SECURITY.md](SECURITY.md) has the threat model, what each role can see, the hardening checklist, and how to report a vulnerability.

## Scope and limits

What the builder is for, and the envelope it is tested in. Outside it the builder either refuses with a message or is unsupported.

-   **Odoo 18.0 only.** OCB 18.0 is what the suite runs on. No other series is supported yet.
-   **A development database, not production.** The builder writes Python and XML into the server's addons path and reloads modules in the running process. Use it on a development or staging copy, commit the result, and deploy the generated addon like any other. Back up (or be able to recreate) the database you build on.
-   **Writing switched on, on a writable addons path.** A package is editable only when the server-side switch described under [Security](#security) is on and its directory passes the write probe described above. With the switch off, or on a read-only checkout, a Nix-store build or a read-only container mount, the console opens read-only.
-   **Trusted administrators only.** A Builder Administrator, and so every `Settings` administrator, can write code that the server then imports and runs. Treat that access as equivalent to shell access on the server and grant it accordingly. See [Security](#security) above and [SECURITY.md](SECURITY.md) for the security model and how to report a vulnerability.
-   **A single process: `workers = 0`.** Applying a change re-imports Python in the running process. Other workers would rebuild their registry against the stale classes they still hold, so under `workers > 0` (or with a package's reload mode set to manual) an Apply writes the files and stops at _Restart needed_; it finishes after the server restarts. Nothing is half-applied, but it is not the interactive loop the builder is designed for.
-   **One database per source tree.** Files are the source of truth and are shared by every database served from the same addons path; the builder's records are per database. Editing the same package from two databases (or two servers on one checkout) is not coordinated: the second one sees drift and has to reload from files. Build in one database.
-   **Model changes are staged behind Apply.** Views, menus, actions and the like are written as you edit. A new field or model on a package-owned Python model needs its class re-imported, so those edits collect in a pending tray and land together on **Apply** — one reload per changeset. A failed apply rolls the files back.
-   **Compiled JavaScript is not in git.** The console is TypeScript; a clone has no `.js` until it is built. The Nix dev shell and Nix builds do that for you (see [TypeScript](#typescript)).

What it deliberately does not do:

-   It is not a hosted or multi-tenant service, and has no per-user sandbox: output is real, unrestricted Python.
-   It does not rewrite code outside its marked block, and does not edit core or third-party views in place — every change to an existing view is an inheriting view in your package.
-   It does not deploy, commit or push. Git, review and release stay with your own tooling.
-   It does not migrate data. Renaming or removing a field changes the source; the data migration is yours to write.
-   It does not replicate Odoo Studio feature for feature. [PLAN.md](PLAN.md) lists what is covered, what is left and what will not be built.
-   It ships no upgrade path from the pre-2.0 `studio.*` addons; see [CHANGELOG.md](CHANGELOG.md).

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

### Tests

`odoo-nix gate test` is what CI runs: every addon's Python tests, tours and hoot tests on a fresh database, with coverage. For one addon while working, `odoo test app_builder_view` (comma-separate several). [DESIGN.md](DESIGN.md#verification) has the end-to-end probes for the paths a `TransactionCase` cannot reach.

### Translations

Each addon with translatable terms ships `i18n/<addon>.pot`, exported by Odoo itself. The export reads the compiled `.js`, which is how the console's TypeScript `_t()` strings get in, so build before exporting. [Contributing](.github/CONTRIBUTING.md#translations) has the command.

### Contributing and releases

[.github/CONTRIBUTING.md](.github/CONTRIBUTING.md) covers the workflow, commit convention and checks. Work lands on `develop`; the release workflow bumps each changed addon's version from its conventional commits and fast-forwards the series branch `18.0`. Notable changes and upgrade notes are in [CHANGELOG.md](CHANGELOG.md).

### Further reading

See [DESIGN.md](DESIGN.md) for the full architecture, the core machinery it drives, and the traps it works around — three Odoo caches that are never invalidated, two reserved module names, the `ir_cron` lock `button_immediate_upgrade` takes, and the findings from an adversarial review. See [TYPING.md](TYPING.md) for how the Python and TypeScript are typed, checked, built and loaded today, and the traps that cost time; the plan it came out of and the log of carrying it out are in [TYPING_HISTORY.md](TYPING_HISTORY.md). [PLAN.md](PLAN.md) is the roadmap against Odoo Studio, and [FORWARD_COMPAT.md](FORWARD_COMPAT.md) the unverified notes for a 19.0 port.

## Licence

AGPL-3. See [LICENSE](LICENSE).

## Credits

**Copyright:** Avunu LLC

**Contributors:** Kevin Shenk <[kevin@avu.nu](mailto:kevin@avu.nu)\>

App Builder for Odoo is an independent project, not affiliated with or endorsed by Odoo S.A. Odoo is a trademark of Odoo S.A.
