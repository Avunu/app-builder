# App Builder

[![License: AGPL-3](https://img.shields.io/badge/license-AGPL--3-blue.png)](http://www.gnu.org/licenses/agpl-3.0-standalone.html)

An open-source alternative to Odoo Studio whose output is **ordinary source code
from the first keystroke**.

Odoo Studio keeps everything in the database and offers a one-time, irreversible
"export to module". Once a developer touches the exported code, they can never go
back to the visual tool. App Builder inverts that: every visual change writes both
the database record and the corresponding file in a real addon directory, in the
same transaction. The builder and the codebase are two views of one artifact.

```
                    ┌──────────────────────────────┐
   visual edit ────▶│  DB record   +   source file │────▶ git diff / review / CI
                    └──────────────────────────────┘
                                   ▲
   hand-edited file ───────────────┘   (drift detected, one-click reload)
```

## The core idea

"Files are the source of truth" naively means a module upgrade on every
drag-drop — 1–3s per edit, unusable. It doesn't have to, because Odoo already
makes the database side free:

- `IrModel.create` rebuilds the registry synchronously, so a new model and its
  table are live **in the same transaction** (`ir_model.py:404-416`).
- With `--dev=xml`, `ir.ui.view._compute_arch` reads arch from disk whenever
  `arch_updated` is False, so a file-authored view goes live with no DB write.

So each operation writes the record *and* the file atomically, and a full
`update_list()` + `button_immediate_upgrade()` becomes the verification and repair
path rather than the edit path.

That is only legitimate if loading the files reproduces the database exactly,
which is the invariant the suite asserts:

```
load_from_files(serialize(db_state)) == db_state
```

`test_roundtrip.py` proves it by serializing, wiping every record, reloading
through Odoo's own `convert_xml_import`, and asserting byte-identical output.
Every record id changes across that wipe, so passing also proves no raw ids leak
into generated files.

## Why the output is reviewable

Studio's export is unreadable in review because ordering follows dict iteration
and record ids. Everything here follows a *declared* rule, so an unchanged package
re-serializes byte-identically and yields an empty `git diff`:

- attributes in a declared priority order, then alphabetically;
- records ordered by serializer sequence then xmlid — never by id;
- relations always as `ref="xmlid"`; a referenced record with no xmlid is a hard
  error, not a silently emitted integer;
- fields equal to their declared default omitted — defaults are *evaluated*,
  since Odoo wraps every scalar default in a lambda (`fields.py:511`);
- mixed content (QWeb bodies, HTML) never reflowed; only structural elements are
  re-indented;
- rendering pins `lang=None`, so output never depends on who clicked save.

Edits to existing views become **inheriting views** at `priority=99` — core's own
convention (`ir_ui_view.py:658`) — never rewrites. Manifest `depends` are derived
from the refs actually emitted, and data files are ordered so every ref resolves
when its file loads.

## Packages are data-only until you say otherwise

Computed fields and server actions are already *data* in Odoo:
`ir.model.fields.compute` is a sandboxed string turned into a real compute by
`make_compute` (`ir_model.py:48-52`). Generated packages are therefore data-only
and never trip `load_openerp_module`'s `sys.modules` guard — models, fields, views
and automations go live without restarting the server.

## Graduate to code

The thing Odoo Studio cannot do. **Studio → Graduate to Code** converts a
visually-built model into an ordinary `models.Model` subclass you own outright:

```python
class XGradTask(models.Model):
    _name = "x_grad_task"
    _description = "Grad Task"
    _rec_name = "x_name"

    x_hours = fields.Float(string="Hours")
    x_name = fields.Char(string="Name", required=True)
    x_summary = fields.Char(string="Summary", compute="_compute_x_summary", store=True)

    @api.depends("x_name", "x_hours")
    def _compute_x_summary(self):
        for r in self:
            r['x_summary'] = '%s (%sh)' % (r.x_name or '', r.x_hours)
```

Three things make it lossless rather than a rewrite:

- the xmlids Odoo's reflection assigns to a code-defined model are *identical* to
  the ones the studio emitted (`model_xmlid` / `field_xmlid` / `selection_xmlid`),
  so nothing is orphaned and `_process_end` reaps nothing;
- the sandboxed `compute` string is promoted to a real method with a real
  `@api.depends`;
- the metadata rows are *reclassified* (`state` manual → base), never deleted.
  Deleting would be doubly catastrophic: `ir.model.fields.unlink` calls
  `_drop_column` and would destroy user data, and every `model_id` in Odoo is
  `ondelete='cascade'`, so dropping the `ir.model` row silently takes the access
  rules and automations with it.

Graduation is a **one-way handoff**: the file is generated once and never
overwritten. It takes effect at the next restart, which `--dev=reload` triggers
automatically when the `.py` lands.

## Read-only in production is a feature

The editor gates on `os.access(root_path, W_OK)`. Against a Nix-store build or any
read-only deployment it disables itself with an explanatory banner instead of
failing. You build in development, ship through git, and deploy immutably.

## Available addons

<!-- prettier-ignore-start -->
[//]: # (addons)

Available addons
----------------
addon | version | maintainers | summary
--- | --- | --- | ---
[app_builder](app_builder/) | 18.0.1.0.0 |  | Open-source visual builder whose output is real source code
[app_builder_base](app_builder_base/) | 18.0.1.0.0 |  | Engine for visually built Odoo modules that live in source control
[app_builder_model](app_builder_model/) | 18.0.1.0.0 |  | Visually build models and fields that are written to source
[app_builder_ui](app_builder_ui/) | 18.0.1.0.0 |  | Build menus, actions, access rules and automations into source
[app_builder_view](app_builder_view/) | 18.0.1.0.0 |  | Edit views visually; every change becomes an inheriting view in source

[//]: # (end addons)
<!-- prettier-ignore-end -->

## Development

The addons are developed against [OCB](https://github.com/OCA/OCB) 18.0 in a
[odoo-nix](https://github.com/Avunu/odoo-nix) workspace, which pins OCB and every
OCA dependency as submodules and synthesizes `addons_path` from them.

```sh
python odoo/odoo-bin -c odoo.conf -d studio_test -i app_builder \
  --test-enable \
  --test-tags /app_builder_base,/app_builder_model,/app_builder_view,/app_builder_ui \
  --stop-after-init
```

See [DESIGN.md](DESIGN.md) for the full architecture, the core machinery it
drives, and the traps it works around — three Odoo caches that are never
invalidated, two reserved module names, the `ir_cron` lock
`button_immediate_upgrade` takes, and the findings from an adversarial review.

## Licence

AGPL-3. See [LICENSE](LICENSE).

## Credits

**Authors:** Avunu LLC

**Contributors:** Kevin Shenk \<kevin@avu.nu\>

This project follows [OCA](https://odoo-community.org) conventions — AGPL-3,
`readme/` fragments, whool packaging, the OCA pre-commit set — but is **not an
official OCA project** and is not endorsed by the OCA.
