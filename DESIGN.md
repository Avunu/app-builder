# App Builder — design notes

## Context

Odoo Studio (enterprise) is a visual builder for models, fields, views, menus, actions and
automations. Its fatal architectural limit is that **everything lives in the database**: the
`studio_customization` module is a DB artifact, and the only escape hatch is a one-time,
irreversible "export to module" that produces code nobody can round-trip back into the builder.
A developer who touches the exported code can never return to the visual tool.

We want an open-source replacement whose output is **source code on disk from the first
keystroke**, in the spirit of Frappe: the visual builder and the codebase are two views of one
artifact, and a developer can move between them freely, with git as the system of record.

Three findings from the survey shape everything below:

1. **There is nothing to fork.** `module_prototyper`, `base_module_record` and `web_view_editor`
   are gone from OCA entirely (not merely unported). The best component precedents are
   `bi_sql_editor` (materializes model+fields+views+action+menu from one record) and
   `attribute_set` (`_inherits = {"ir.model.fields": "field_id"}` for real dynamic fields).
2. **Odoo core has no record→XML serializer.** The import direction is complete and excellent
   (`odoo/tools/convert.py`, `base_import_module`); the export direction does not exist anywhere
   in community 18.0. That emitter is the load-bearing novel work.
3. **Live reload already works — for data-only modules.** `ir.model` creation rebuilds the
   registry synchronously; `--dev=xml` re-reads view arch from disk with zero DB writes. Python
   code is the only thing that needs a process restart.

Decisions taken: **Odoo 18.0 primary, 19.0 kept clean** (18.0 still has full OCA
availability; several dependencies we want are not ported to 19.0 yet); **files are the
source of truth, the database is a projection**.

## Architecture

### The central bet: DB and file written in the same transaction

"Files are truth" must not mean "run a module upgrade on every drag-drop" (1–3s per edit, unusable).
It doesn't have to. Every studio operation does both writes atomically:

```
operation ──┬─> DB records   (live + validated by Odoo's own _check_xml / _validate_view)
            └─> source files (the durable artifact, byte-identical to what a load would produce)
```

This works because core already makes the DB side free:

- `IrModel.create` → `setup_models` → `init_models` ([ir_model.py:404-416]) gives a real table
  and a real ORM model **in the same transaction**. No upgrade needed.
- For views, we write the row *and* set `arch_fs`, leaving `arch_updated = False`. Under
  `--dev=xml`, `_compute_arch` ([ir_ui_view.py:226-227]) then reads from disk on next access.
  The file is authoritative on the very next request.

A full `update_list()` + `button_immediate_upgrade()` becomes the **verification and repair**
path — run explicitly, on drift, or in CI — not the edit path.

**The invariant that makes this legitimate**, and the single most important test in the project:

> for every package: `load_from_files(serialize(db_state))` reproduces `db_state` exactly.

If that property holds, the DB write is an optimization, not a divergent source of truth.

### Module layout

Five addons under `custom/`. **Do not name anything `studio_customization`** — it is hardcoded
into `graph.py:16` `_ignored_modules` and skipped by `ir_module.button_upgrade`.

| Module | Responsibility |
|---|---|
| `app_builder_base` | `studio.package`, serializer framework, file writer, drift detection, reload orchestration, git integration |
| `app_builder_model` | model & field builder (`ir.model`, `ir.model.fields`, selections) |
| `app_builder_view` | view editor — backend operations + OWL client |
| `app_builder_ui` | menus, actions, ACLs, record rules, automations |
| `app_builder` | meta/umbrella + the app entry point |

License AGPL-3 (OCA default for apps; depending on LGPL-3 `base_view_inheritance_extension` is fine).

### `studio.package` — an addon directory as a record

Maps 1:1 to a real directory under an addons_path entry (default `custom/<name>/`).

- `name`, `path`, manifest fields (version, depends, category, license)
- `writable` — computed `os.access(path, W_OK)`. **The entire editor is gated on this.** In
  production (nix store, read-only) the studio goes read-only by design: you edit in dev, ship
  via git, deploy immutably. This aligns exactly with the nix setup rather than fighting it.
  `upgrade_analysis._write_file` is the precedent for handling the not-writable case honestly.
- `state` — `synced` / `dirty` / `drifted` / `conflict`
- `file_ids` (`studio.package.file`: `path`, `disk_checksum`, `generated_checksum`) — drift is
  `disk_checksum != generated_checksum`, i.e. a human edited generated output.

### The serializer — the novel core

`studio.serializer`, an abstract model with one concrete subclass per serialized model:

```python
_serialize(record)   -> etree.Element   # the <record> node
_target_file(record) -> str             # 'views/x_foo_views.xml'
_xmlid(record)       -> str
_depends(record)     -> set[str]        # xmlids referenced, for ordering
```

Coverage: `ir.model`, `ir.model.fields`, `ir.model.fields.selection`, `ir.ui.view`,
`ir.actions.act_window` (+`.view`), `ir.actions.server`, `ir.actions.report`, `ir.ui.menu`,
`ir.rule`, `base.automation`, `ir.filters`, `ir.sequence`, `ir.default`, and
`ir.model.access` → **CSV**, not XML (`security/ir.model.access.csv`).

**Determinism is the whole product.** This is precisely what Studio's one-shot export gets
wrong, and what makes output reviewable in git:

- fields emitted in a fixed **declared** order per serializer, never dict order
- records ordered within a file by dependency then xmlid, never by `id`
- relations always emitted as `ref="xmlid"`, never raw ids; a referenced record with no xmlid
  is a hard error surfaced in the UI, not a silently-emitted integer
- a declared "significant fields" list per serializer rather than dynamic default-comparison
  (defaults are context-dependent and would make output unstable)
- `arch` canonicalised through one shared pretty-printer: fixed attribute order, fixed indent,
  no trailing whitespace — so a semantic no-op produces an empty diff

**Constraint discovered in core:** generated XML must never put the key `studio` in a `context`
attribute. `base_import_module._is_studio_custom` (`ir_module.py:545`) walks every XML file
looking for exactly that and refuses the module with *"Studio customizations require the Odoo
Studio app."*

### MVP generates zero Python — deliberately

This is what buys restart-free live editing, and it costs almost nothing:

- computed fields are **data**: `ir.model.fields.compute` is a safe_eval'd string turned into a
  real compute by `make_compute` ([ir_model.py:48-52]), with `depends` validated by `_check_depends`
- server actions are **data**: `ir.actions.server.code`
- only `__init__.py` / `__manifest__.py` are emitted, and neither changes per edit

So the MVP is genuinely data-only → `load_openerp_module`'s `sys.modules` guard never bites.

**Phase 5 "graduate to code"** is then the feature that actually beats Studio: convert an `x_`
manual model into a real `models.Model` Python class, rewriting `state='manual'` records to
`state='base'`. That needs a restart, which `--dev=reload` already provides.

### View edits emit inheriting views, never replacements

A studio edit to `sale.view_order_form` produces a new `ir.ui.view` with `inherit_id` +
`<xpath position=...>`, at `priority = 99` (core's own convention, commented at
[ir_ui_view.py:658]). Survives upstream changes, reads as a normal patch in review.

Mapping a clicked DOM node back to an xpath is **already solved in core**: the
`inherit_branding` / `distribute_branding` / `data-oe-xpath` machinery
([ir_ui_view.py:775-789, 2136, 2203]) used by the website editor. Reuse it rather than writing
an arch-locator. `base_view_inheritance_extension` adds AST-level dict merging so `context` and
`options` attributes can be patched without replacing the whole string.

### Reload orchestration — three known core traps

`studio.package._reload()` must, in order:

1. `odoo.modules.module._get_manifest_cached.cache_clear()` — an `lru_cache` at `module.py:365`
   that **is never invalidated anywhere in the codebase**. An edited manifest is otherwise
   invisible for the process lifetime.
2. `importlib.invalidate_caches()` — likewise never called by Odoo.
3. `update_list()` then `button_immediate_upgrade()`.

Also: `_button_immediate_function` ([ir_module.py:601-644]) raises if the registry is
initialising or in test mode, and takes `SELECT * FROM ir_cron FOR UPDATE NOWAIT` — it fails
outright while cron runs, so this needs a retry/queue. And a **new addons directory** cannot be
registered at runtime; packages must live under an existing addons_path entry (`custom/`).

### Reverse direction: developer edits the file

- view arch → free via `--dev=xml`
- anything else → a checksum watcher (the `module_auto_update` approach) flags the package
  `drifted` and offers one-click reload; `.py` changes additionally trip the core FSWatcher,
  which only ever watches `.py` ([server.py:278-292])

### Git integration

Per-package `auto_commit` / `stage_only` / `off`, with `git status`/`git diff` surfaced in the
UI. Precedent: `odoo-module-migrator._commit_changes`. This is what makes "move seamlessly
between builder and codebase" concrete — the builder produces commits a human reviews.

## As built — what implementation changed

The design above survived contact with the code. Five things it did not
anticipate, all found by tests or the end-to-end run:

1. **Magic columns are not ownable.** A model's `field_id` includes the reflected
   base columns (`id`, `create_uid`, `create_date`, …) with `state='base'`.
   Assigning them xmlids produced records a reload cannot reproduce, and Odoo
   refuses to unlink them at all (*"This column contains module data and cannot
   be removed!"*, `_prepare_update`). Fixed with a `_ownable()` guard on the
   serializer, enforced in both `_assign` and `_owned_records`.

2. **Every scalar default is a callable.** Odoo wraps defaults as
   `lambda model: value` (`fields.py:511`), so a `callable(default)` check never
   fires and the first skip rule emitted `domain="[]"`, `store`, `selectable`
   and `on_delete` on every single field. Defaults must be *evaluated*.

3. **`info` is a reflection artifact.** `_reflect_model_params` fills it from the
   first docstring in the class MRO (`ir_model.py:433`), so an undocumented
   custom model comes back carrying `models.Model`'s own docstring.

4. **Manifest `depends` must be derived, not declared.** A menu parented under
   `app_builder_base.menu_studio_root` shipped with `depends=['base']` and failed
   to install into a fresh database. Serializers now record every foreign module
   they emit a ref to, and the manifest unions that with the declared list. This
   was invisible to unit tests and only surfaced in the real install path.

5. **`base_automation` leaks patches past Odoo's leak detector.** It monkeypatches
   `create`/`write` with its own patcher, which `TransactionCase.check_attrs`
   does not recognise the way it does `mock.patch`. Tests that create an
   automation must `addCleanup(env['base.automation']._unregister_hook)`.

Confirmed working as designed: `<record model="ir.model">` in a data file does
create a functioning custom model (no OCB or OCA precedent existed for this), and
`_load_records` sets `install_mode=True` so the automatic `x_name` default is
correctly skipped on reload.

### What graduate-to-code cost

Two further discoveries, both found only by running a real restart rather than a
test — worth recording because both were silent:

6. **Leaving `state='manual'` behind destroys the graduation.** With the rows
   still marked manual, `_add_manual_models` rebuilds a custom class competing
   with the Python one for the same `_name`, and `_process_end` then reaps the
   studio's xmlids outright — observed as
   `Deleting 411@ir.model (x_grad_demo.model_x_grad_task)`.

7. **...but deleting those rows is worse.** The first fix deleted them, which
   passed a naive check and quietly destroyed the ACL: every `model_id` in Odoo
   is `ondelete='cascade'`, so removing the `ir.model` row takes
   `ir.model.access`, `ir.rule`, `ir.actions.server` and `base.automation` with
   it — and `ir.model.fields.unlink` calls `_drop_column`, which would have taken
   the user's data too. The correct operation is to *reclassify*
   (`state` manual → base) and delete nothing. `test_demotion_does_not_cascade_into_dependent_records`
   pins this.

Also worth knowing: generated Python and manifests are emitted already-canonical
under `ruff format`. Otherwise the project's own pre-commit rewrites them on the
next commit and every package reports as drifted with nothing actually changed.

### What adversarial review found

A five-lens review (round-trip, determinism, graduation, security, Odoo idiom),
each finding then independently attacked by a verifier that ran the scenario
against a live database, raised 36 findings. After dedup, ~17 were real. The
ones that mattered, each now pinned by a test in `test_review_regressions.py`:

8. **A generated package containing an `ir.rule` could not be installed.** A
   hand-written addon loads `security/` first, and the code copied that
   convention — but everything the studio emits under `security/` carries a
   `model_id` ref to an `ir.model` record that `models/` has not defined yet.
   Security now loads *after* models. The same class of bug applied to menus,
   which is why they all now live in one `views/menus.xml` ranked after the view
   files that define their actions.

9. **Serialization read records in the acting user's language.** Many emitted
   fields are `translate=True`, and `ir.ui.view.arch_db` uses `xml_translate`,
   so a French admin's save emitted French strings — and because Odoo's importer
   pins `lang=None` (`convert.py:630`), the next load wrote them into the
   `en_US` slot, destroying the source term *and* the translation. Rendering now
   pins `lang=None`. Note this was invisible to the round-trip test: after the
   lossy reload the fr_FR key is gone, so the second render reproduces the same
   bytes — a byte-stable fixed point over a corrupted database.

10. **`many2one_reference` emitted a raw database id**, which cannot survive a
    fresh install. It now raises rather than silently corrupting.

11. **A field added to an already-graduated model was written to no file at
    all** — excluded from XML by a graduation flag and from Python by the
    write-once handoff. The flag is gone: graduation demotes the metadata to
    `state='base'` and `_ownable` excludes that, so the XML stops as a
    consequence of the data. A new manual field on a graduated model is now
    correctly emitted as XML, exactly as Studio adds fields to core models.

12. **Graduating a package Odoo had not installed orphaned the model** — the
    metadata was demoted while no module existed to load the replacement class.
    Now refused with an explanation.

13. **"Delete records" then "Write to disk" erased the source it promised to
    keep**, because the prune pass removes tracked files that no longer have
    records behind them.

14. **`indent()` deleted non-breaking spaces.** `str.strip()` treats U+00A0 as
    insignificant, so a `&nbsp;` separating two inline elements in a QWeb body
    vanished on every write. Only ASCII layout whitespace is stripped now.

Also fixed: `app_builder_ui` inherited a mixin from a module it did not depend on
(aborting the registry if installed alone — the mixin now lives in the engine);
`_assign` silently no-op'd for records another module owned; freshly written
files were all reported as drifted; and several codegen fidelity bugs where a
graduated computed field came back read-only, a stored related field came back
unstored, and a valueless `Selection` produced un-importable Python.

## Status

All five planned phases are done, with **126 tests** across the suite:

- `app_builder_base` — packages, serializer framework, canonical writer, drift,
  reload, teardown, graduate-to-code, and the round-trip invariant
- `app_builder_model` — model & field builder
- `app_builder_view` — view editor: operation API, node picker, OWL client
- `app_builder_ui` — menus, actions, ACLs, record rules, automations

CI runs ruff + pre-commit, and the test suite against both Odoo and OCB 18.0 in
the OCA CI containers.

Remaining:

- **Client depth** — true drag-and-drop using core's `data-oe-xpath` branding
  machinery (`ir_ui_view.py:775-789`); a domain builder via
  `web_widget_domain_editor_dialog`; browser tour tests.
- **19.0** — the code is kept 19.0-clean but is only tested on 18.0. Several
  OCA dependencies are not ported to 19.0 yet.
- **Graduating two custom models that reference each other** in one operation is
  untested; graduate them one at a time.
- **`many2one_reference`** cannot be serialized portably (its value is a raw
  database id) and is refused rather than silently corrupted.

## Reference reading

Odoo core (read, don't modify): `odoo/addons/base/models/ir_model.py`,
`ir_ui_view.py`, `ir_actions.py`, `ir_module.py`; `odoo/tools/convert.py`,
`odoo/tools/template_inheritance.py`; `odoo/modules/{module,loading,registry}.py`;
`addons/base_import_module/models/ir_module.py`;
`addons/web/static/src/views/{view_compiler,view_service,debug_items}.js`.

Pattern references in OCA: `reporting-engine/bi_sql_editor` (materialising a
model + views + action + menu from one record), `odoo-pim/attribute_set`
(dynamic fields via `_inherits` on ir.model.fields, and arch injection),
`server-tools/upgrade_analysis` (writing generated files into an addons path),
`maintainer-tools/tools/manifest.py` (manifest read/write).

## Verification

```sh
python odoo/odoo-bin -c odoo.conf -d studio_test -i app_builder \
  --test-enable \
  --test-tags /app_builder_base,/app_builder_model,/app_builder_view,/app_builder_ui \
  --stop-after-init
```

End-to-end acceptance, in order:

1. Create a package `x_demo` -> the addon directory appears with a manifest
2. Create a model with a char, a m2o and a **stored computed** field ->
   table exists, fields queryable, `models/` + `views/` XML on disk
3. Add it to a menu and grant access -> menu renders, ACL csv written
4. Edit a core view -> an *inheriting* view at `priority=99` is written
5. **Round-trip:** drop the DB, install the package from files alone,
   re-serialize -> **byte-identical output**
6. **Drift:** hand-edit a generated file -> package reports `drifted`,
   one-click reload adopts it
7. **Graduate:** convert the model to Python, restart -> class loads, data
   intact, compute still recomputes
8. **Read-only:** point at a read-only checkout -> editor disabled, no traceback
