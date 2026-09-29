# App Builder — design notes

## Context

Odoo Studio (enterprise) is a visual builder for models, fields, views, menus, actions and automations. Its fatal architectural limit is that **everything lives in the database**: the `studio_customization` module is a DB artifact, and the only escape hatch is a one-time, irreversible "export to module" that produces code nobody can round-trip back into the builder. A developer who touches the exported code can never return to the visual tool.

We want an open-source replacement whose output is **source code on disk from the first keystroke**, in the spirit of Frappe: the visual builder and the codebase are two views of one artifact, and a developer can move between them freely, with git as the system of record.

Three findings from the survey shape everything below:

1.  **There is nothing to fork.** `module_prototyper`, `base_module_record` and `web_view_editor` are gone from OCA entirely (not merely unported). The best component precedents are `bi_sql_editor` (materializes model+fields+views+action+menu from one record) and `attribute_set` (`_inherits = {"ir.model.fields": "field_id"}` for real dynamic fields).
2.  **Odoo core has no record→XML serializer.** The import direction is complete and excellent (`odoo/tools/convert.py`, `base_import_module`); the export direction does not exist anywhere in community 18.0. That emitter is the load-bearing novel work.
3.  **Live reload already works — for data-only modules.** `ir.model` creation rebuilds the registry synchronously; `--dev=xml` re-reads view arch from disk with zero DB writes. Python code is the only thing that needs a process restart.

Decisions taken: **Odoo 18.0 primary, 19.0 kept clean** (18.0 still has full OCA availability; several dependencies we want are not ported to 19.0 yet); **files are the source of truth, the database is a projection**.

## Architecture

### The central bet: DB and file written in the same transaction

"Files are truth" must not mean "run a module upgrade on every drag-drop" (1–3s per edit, unusable). It doesn't have to. Every studio operation does both writes atomically:

```
operation ──┬─> DB records   (live + validated by Odoo's own _check_xml / _validate_view)
            └─> source files (the durable artifact, byte-identical to what a load would produce)
```

This works because core already makes the DB side free:

-   `IrModel.create` → `setup_models` → `init_models` (\[ir\_model.py:404-416\]) gives a real table and a real ORM model **in the same transaction**. No upgrade needed.
-   For views, we write the row _and_ set `arch_fs`, leaving `arch_updated = False`. Under `--dev=xml`, `_compute_arch` (\[ir\_ui\_view.py:226-227\]) then reads from disk on next access. The file is authoritative on the very next request.

A full `update_list()` + `button_immediate_upgrade()` becomes the **verification and repair** path — run explicitly, on drift, or in CI — not the edit path.

**The invariant that makes this legitimate**, and the single most important test in the project:

> for every package: `load_from_files(serialize(db_state))` reproduces `db_state` exactly.

If that property holds, the DB write is an optimization, not a divergent source of truth.

_Amended 2026-07-28._ This still holds for everything emitted as XML/CSV, and it is still what makes the DB write legitimate there. It is **false by construction for a Python-backed model**, where the database is produced by class loading rather than by the file being compared — so it splits into three properties. See _Status → The three invariants_. The other half of the bet changes with it: a new _column_ no longer arrives in the caller's transaction, so edits batch behind an explicit Apply and pay one reload per changeset.

### Module layout

Five addons under `custom/`. **Do not name anything `studio_customization`** — it is hardcoded into `graph.py:16` `_ignored_modules` and skipped by `ir_module.button_upgrade`.

| Module | Responsibility |
| --- | --- |
| app_builder_base | studio.package, serializer framework, file writer, drift detection, reload orchestration, git integration |
| app_builder_model | model & field builder (ir.model, ir.model.fields, selections) |
| app_builder_view | view editor — backend operations + OWL client |
| app_builder_ui | menus, actions, ACLs, record rules, automations |
| app_builder | meta/umbrella + the app entry point |

License AGPL-3 (OCA default for apps; depending on LGPL-3 `base_view_inheritance_extension` is fine).

### `studio.package` — an addon directory as a record

Maps 1:1 to a real directory under an addons\_path entry (default `custom/<name>/`).

-   `name`, `path`, manifest fields (version, depends, category, license)
-   `writable` — computed `os.access(path, W_OK)`. **The entire editor is gated on this.** In production (nix store, read-only) the studio goes read-only by design: you edit in dev, ship via git, deploy immutably. This aligns exactly with the nix setup rather than fighting it. `upgrade_analysis._write_file` is the precedent for handling the not-writable case honestly.
-   `state` — `synced` / `dirty` / `drifted` / `conflict`
-   `file_ids` (`studio.package.file`: `path`, `disk_checksum`, `generated_checksum`) — drift is `disk_checksum != generated_checksum`, i.e. a human edited generated output.

### The serializer — the novel core

`studio.serializer`, an abstract model with one concrete subclass per serialized model:

```python
_serialize(record)   -> etree.Element   # the <record> node
_target_file(record) -> str             # 'views/x_foo_views.xml'
_xmlid(record)       -> str
_depends(record)     -> set[str]        # xmlids referenced, for ordering
```

Coverage: `ir.model`, `ir.model.fields`, `ir.model.fields.selection`, `ir.ui.view`, `ir.actions.act_window` (+`.view`), `ir.actions.server`, `ir.actions.report`, `ir.ui.menu`, `ir.rule`, `base.automation`, `ir.filters`, `ir.sequence`, `ir.default`, and `ir.model.access` → **CSV**, not XML (`security/ir.model.access.csv`).

**Determinism is the whole product.** This is precisely what Studio's one-shot export gets wrong, and what makes output reviewable in git:

-   fields emitted in a fixed **declared** order per serializer, never dict order
-   records ordered within a file by dependency then xmlid, never by `id`
-   relations always emitted as `ref="xmlid"`, never raw ids; a referenced record with no xmlid is a hard error surfaced in the UI, not a silently-emitted integer
-   a declared "significant fields" list per serializer rather than dynamic default-comparison (defaults are context-dependent and would make output unstable)
-   `arch` canonicalised through one shared pretty-printer: fixed attribute order, fixed indent, no trailing whitespace — so a semantic no-op produces an empty diff

**Constraint discovered in core:** generated XML must never put the key `studio` in a `context` attribute. `base_import_module._is_studio_custom` (`ir_module.py:545`) walks every XML file looking for exactly that and refuses the module with _"Studio customizations require the Odoo Studio app."_

### ~~MVP generates zero Python — deliberately~~ → **Python, with a machine-owned block**

_Superseded 2026-07-28. The original text is kept below the line because the reasoning was sound and the reason it stopped applying is worth knowing._

New models are generated as real `models.Model` classes. **Only a marker-delimited block inside the class is machine-owned**; the rest of the file is never read, never parsed and never rewritten:

```python
class WorkshopJob(models.Model):
    # begin: studio-generated schema
    _name = "workshop.job"
    _inherit = ["mail.thread"]
    name = fields.Char(string="Name", required=True)
    # end: studio-generated schema

    @api.constrains("name")          # anything at all out here
    def _check_name(self): ...
```

This is Frappe's `TypeExporter` convention (`frappe/types/exporter.py`), and it is adopted for the same reason: writing is a pure string splice between the markers, so a developer may use a metaclass, a `@property`, a decorator we have never heard of, and the builder keeps working. **An earlier revision parsed the whole file and froze a model on any construct it did not model — which is the same one-way handoff this project exists to avoid, in new clothes.**

What Frappe does that Odoo _cannot_: keep the schema in JSON and the behaviour in a separate controller class. Frappe resolves the controller by name at runtime (`get_controller`), so the two never contend. An Odoo model **is** a composed class, and `_add_manual_models` (\[ir\_model.py:502-511\]) deletes every `_custom` model from the pool and rebuilds it from `ir_model` rows alone on every `setup_models` — so a Python class that `_inherit`s a record-defined model survives install and then evaporates. Verified empirically, not inferred. Whatever declares the fields must therefore be the same class that carries the behaviour.

The rest of what forced Python-first, all verified against 18.0:

-   **A live `state='manual'` field cannot have a clean name.** PostgreSQL CHECK `name_manual_field` (`CHECK (state != 'manual' OR name LIKE 'x\_%')`) plus `BaseModel._add_field` (\[models.py:667-680\]). So "no `x_`" ⇒ fields are class attributes ⇒ a new column needs the class re-imported. Edits therefore batch behind an explicit Apply.
-   **Data-defined fields are one bad regeneration from data loss.** `_process_end` deletes records absent from reloaded data, and `IrModelFields.unlink` → `_drop_column` issues `ALTER TABLE … DROP COLUMN … CASCADE`.
-   **Manual models hit a hard ceiling**: no `_sql_constraints`, `@api.constrains`, `@api.onchange`, `_inherits`, `_parent_store`; `_order` restricted to stored fields; and `properties` / `many2one_reference` / `json` silently unusable because `_add_manual_fields` swallows every per-field exception (\[ir\_model.py:1379-1384\]).
-   **Field order is non-deterministic** for manual fields — `_all_manual_field_data` reads unordered SQL — which is a direct threat to byte-identical output. Class order is not.

Chatter was _not_ a reason: `ir.model.is_mail_thread` and mail's `_instanciate` override are the one mixin exception for manual models. It is irreversible there, and an ordinary `_inherit` in a class.

`graduate-to-code` inverts into **adopt**: bringing an existing `x_` manual model under Python management. Editing a _core_ model keeps both modes, labelled — `_inherit` + Python (clean names, real constraints) as the default, and `x_` + manual + XML as the instant escape hatch.

Original reasoning (no longer in force)

This is what buys restart-free live editing, and it costs almost nothing:

-   computed fields are **data**: `ir.model.fields.compute` is a safe\_eval'd string turned into a real compute by `make_compute` (\[ir\_model.py:48-52\]), with `depends` validated by `_check_depends`
-   server actions are **data**: `ir.actions.server.code`
-   only `__init__.py` / `__manifest__.py` are emitted, and neither changes per edit

So the MVP is genuinely data-only → `load_openerp_module`'s `sys.modules` guard never bites.

### View edits never rewrite another module's view

A studio edit to `sale.view_order_form` produces a new `ir.ui.view` with `inherit_id` + `<xpath position=...>`, at `priority = 99` (core's own convention, commented at \[ir\_ui\_view.py:658\]). Survives upstream changes, reads as a normal patch in review.

A view the editing package **owns** is edited directly instead. Emitting a patch against your own primary view produces source no developer would write — a generated form plus a pile of xpaths against it in the same addon. Both modes run the same handlers over the same `<xpath>` spec; the owned path feeds that spec through core's `apply_inheritance_specs` instead of storing it, so the two cannot drift apart.

**The branding plan below was wrong and is struck.** Mapping a clicked DOM node back to an xpath is _not_ solved by `inherit_branding` for backend views:

-   `distribute_branding` — the half that computes per-node xpaths — is only reached from `_read_template`, i.e. the QWeb render path. Backend form/list views never go through it.
-   `inherit_branding` is absent from `_get_view_cache_key` (\[ir\_ui\_view.py:2740-2758\]), so requesting it through `get_view` either returns the cached unbranded arch or poisons a shared cache. `loadViews` filters the client context down to `lang` + `*_view_ref` anyway.
-   `data-oe-xpath` is relative to the **owning view's own arch**, not the combined arch that `apply_inheritance_specs` matches. Core's own `test_branding_inherit` shows a node that is `item[2]` in the combined tree carrying `/root[1]/item[1]`.

Node identity does not survive `view_compiler.js` either: `copyAttributes` forwards only `class` and `style`, `Group` has a closed prop list, and `<page>` compiles to a slot with no element. Carry identity as a **class token** if it is ever needed on the canvas. (It is: the console below stamps one per node, server-side, on the combined arch.)

What actually works is what the code does: mint locators **server-side** from `get_combined_arch()`, preferring `//tag[@name='x']` while exactly one node answers it and falling back to `getroottree().getpath()`, which is absolute and unique by construction — the same call `distribute_branding` itself uses.

### Reload orchestration — and the ordering that makes it work

Two caches Odoo never invalidates itself: `_get_manifest_cached` (an `lru_cache` at `module.py:365`, an edited manifest is otherwise invisible for the process lifetime) and `importlib.invalidate_caches()`. Both are handled by `_invalidate_module_caches`.

Once the studio generates Python, that is not enough. **`button_immediate_upgrade` does not reload Python.** `load_openerp_module` (\[module.py:370-382\]) early-returns when `odoo.addons.<name>` is already in `sys.modules`, so an upgrade in a live process re-runs the data files against the _old_ classes and reports success.

`_reload_now()` therefore does, and the order is the whole trick:

1.  purge `sys.modules` for the package **and** `MetaModel.module_to_models[pkg]` — the latter is append-only (\[models.py:265\]), so skipping it registers every class a second time;
2.  **then** `button_immediate_upgrade()`, so `init_models` runs and the schema follows.

Each half is justified by a measured failure, not by reading the source (`tests/e2e/probe_reimport.py`):

-   purge without upgrading → the field is in the ORM and the column is _not_ in Postgres, because `Registry.new` only runs `init_models` for modules marked `to upgrade`;
-   upgrade without purging → nothing changes at all, and it looks like it worked.

Two reload modes, chosen from config. `manual` (multiple workers) is **refused**, not degraded: `setup_models` makes every other worker rebuild its registry, but their `sys.modules` still holds the old Python, so they would rebuild against a stale class. That is wrong rather than merely slow. Studio editing is a single-process development activity; production runs read-only from the nix store.

There used to be a third, `restart`, for `--dev=reload`: let the dev server's own file watcher restart the process when the generated `.py` lands. It never worked, and the reason is worth keeping. The watcher restarts on the *first* `.py` written and gives requests in flight one second before it closes every database connection (`ThreadedServer.stop`) -- so the request still writing, or the in-process upgrade that follows it, died with a closed cursor inside `update_list`, and the rollback died the same way. Nor could the restart finish the job on its own: a plain boot upgrades a module marked `to upgrade` but does not install one marked `to install`. So under `--dev=reload` the studio reloads in process like everywhere else and **mutes the watcher for its own writes** for a few seconds around them (`_mute_dev_watcher`, wrapping `FSWatcherBase.handle_file` once); a developer's own edit under the same directory, outside that window, restarts the server exactly as before.

Also: `_button_immediate_function` (\[ir\_module.py:601-644\]) raises if the registry is initialising or in test mode, and takes `SELECT * FROM ir_cron FOR UPDATE NOWAIT` — it fails outright while cron runs, so this needs a retry/queue. And a **new addons directory** cannot be registered at runtime; packages must live under an existing addons\_path entry (`custom/`).

### Apply is a state machine, because module operations commit

`_button_immediate_function` commits before rebuilding the registry and again after, so a failure halfway is not something the ORM rolls back. Worse, if the new Python does not import, the _next_ request re-imports the same file and the database will not boot — for everybody.

So `action_apply` is fixed: render to memory → `compile()` every `.py` → re-parse every `.py` → snapshot the old bytes (a `studio.package.apply` record, `.studio/backup/<stamp>/`, and a git commit) → write → commit → reload → on failure restore, reload again, record why.

The compile gate is what keeps a bad apply survivable, because it runs before anything reaches disk. The snapshot covers what compiling cannot catch. Both copies of the old bytes matter: the on-disk one is all that is left when the process dies mid-reload, and recovery is then `git checkout` from a shell. An apply row still `pending` after a restart is exactly that signal.

**Removing a field drops its column and its data** — measured, not assumed (`_process_end` → `IrModelFields.unlink` → `_drop_column` → `DROP COLUMN CASCADE`). An apply that would do that refuses unless asked explicitly, then emits `migrations/<version>/pre-studio-<stamp>.py` renaming the column aside. `migrate_module(pkg, 'pre')` runs long before `_process_end`, so there is nothing left under the old name and `_drop_column` drops nothing.

### Reverse direction: developer edits the file

-   view arch → free via `--dev=xml`
-   anything else → a checksum watcher (the `module_auto_update` approach) flags the package `drifted` and offers one-click reload; `.py` changes additionally trip the core FSWatcher, which only ever watches `.py` (\[server.py:278-292\])

### Git integration

Per-package `auto_commit` / `stage_only` / `off`, with `git status`/`git diff` surfaced in the UI. Precedent: `odoo-module-migrator._commit_changes`. This is what makes "move seamlessly between builder and codebase" concrete — the builder produces commits a human reviews.

## As built — what implementation changed

The design above survived contact with the code. Five things it did not anticipate, all found by tests or the end-to-end run:

1.  **Magic columns are not ownable.** A model's `field_id` includes the reflected base columns (`id`, `create_uid`, `create_date`, …) with `state='base'`. Assigning them xmlids produced records a reload cannot reproduce, and Odoo refuses to unlink them at all (_"This column contains module data and cannot be removed!"_, `_prepare_update`). Fixed with a `_ownable()` guard on the serializer, enforced in both `_assign` and `_owned_records`.

2.  **Every scalar default is a callable.** Odoo wraps defaults as `lambda model: value` (`fields.py:511`), so a `callable(default)` check never fires and the first skip rule emitted `domain="[]"`, `store`, `selectable` and `on_delete` on every single field. Defaults must be _evaluated_.

3.  **`info` is a reflection artifact.** `_reflect_model_params` fills it from the first docstring in the class MRO (`ir_model.py:433`), so an undocumented custom model comes back carrying `models.Model`'s own docstring.

4.  **Manifest `depends` must be derived, not declared.** A menu parented under `app_builder_base.menu_studio_root` shipped with `depends=['base']` and failed to install into a fresh database. Serializers now record every foreign module they emit a ref to, and the manifest unions that with the declared list. This was invisible to unit tests and only surfaced in the real install path.

5.  **`base_automation` leaks patches past Odoo's leak detector.** It monkeypatches `create`/`write` with its own patcher, which `TransactionCase.check_attrs` does not recognise the way it does `mock.patch`. Tests that create an automation must `addCleanup(env['base.automation']._unregister_hook)`.


Confirmed working as designed: `<record model="ir.model">` in a data file does create a functioning custom model (no OCB or OCA precedent existed for this), and `_load_records` sets `install_mode=True` so the automatic `x_name` default is correctly skipped on reload.

### What graduate-to-code cost

Two further discoveries, both found only by running a real restart rather than a test — worth recording because both were silent:

6.  **Leaving `state='manual'` behind destroys the graduation.** With the rows still marked manual, `_add_manual_models` rebuilds a custom class competing with the Python one for the same `_name`, and `_process_end` then reaps the studio's xmlids outright — observed as `Deleting 411@ir.model (x_grad_demo.model_x_grad_task)`.

7.  **...but deleting those rows is worse.** The first fix deleted them, which passed a naive check and quietly destroyed the ACL: every `model_id` in Odoo is `ondelete='cascade'`, so removing the `ir.model` row takes `ir.model.access`, `ir.rule`, `ir.actions.server` and `base.automation` with it — and `ir.model.fields.unlink` calls `_drop_column`, which would have taken the user's data too. The correct operation is to _reclassify_ (`state` manual → base) and delete nothing. `test_demotion_does_not_cascade_into_dependent_records` pins this.


Also worth knowing: generated Python and manifests are emitted already-canonical under `ruff format`. Otherwise the project's own pre-commit rewrites them on the next commit and every package reports as drifted with nothing actually changed.

### What adversarial review found

A five-lens review (round-trip, determinism, graduation, security, Odoo idiom), each finding then independently attacked by a verifier that ran the scenario against a live database, raised 36 findings. After dedup, ~17 were real. The ones that mattered, each now pinned by a test in `test_review_regressions.py`:

8.  **A generated package containing an `ir.rule` could not be installed.** A hand-written addon loads `security/` first, and the code copied that convention — but everything the studio emits under `security/` carries a `model_id` ref to an `ir.model` record that `models/` has not defined yet. Security now loads _after_ models. The same class of bug applied to menus, which is why they all now live in one `views/menus.xml` ranked after the view files that define their actions.

9.  **Serialization read records in the acting user's language.** Many emitted fields are `translate=True`, and `ir.ui.view.arch_db` uses `xml_translate`, so a French admin's save emitted French strings — and because Odoo's importer pins `lang=None` (`convert.py:630`), the next load wrote them into the `en_US` slot, destroying the source term _and_ the translation. Rendering now pins `lang=None`. Note this was invisible to the round-trip test: after the lossy reload the fr\_FR key is gone, so the second render reproduces the same bytes — a byte-stable fixed point over a corrupted database.

10.  **`many2one_reference` emitted a raw database id**, which cannot survive a fresh install. It raised instead of corrupting — and later turned out to be recoverable after all: the field declares a `model_field` companion naming the model its id belongs to, so the record can be found and emitted as `eval="ref('xmlid')"`. `fields.Reference` needed even less, because core's own importer resolves a plain `ref=` into `"model,id"` (`convert.py:405-407`). What still raises is the case with no companion to resolve through, which is the one that genuinely has nothing to point at.

11.  **A field added to an already-graduated model was written to no file at all** — excluded from XML by a graduation flag and from Python by the write-once handoff. The flag is gone: graduation demotes the metadata to `state='base'` and `_ownable` excludes that, so the XML stops as a consequence of the data. A new manual field on a graduated model is now correctly emitted as XML, exactly as Studio adds fields to core models.

12.  **Graduating a package Odoo had not installed orphaned the model** — the metadata was demoted while no module existed to load the replacement class. Now refused with an explanation.

13.  **"Delete records" then "Write to disk" erased the source it promised to keep**, because the prune pass removes tracked files that no longer have records behind them.

14.  **`indent()` deleted non-breaking spaces.** `str.strip()` treats U+00A0 as insignificant, so a `&nbsp;` separating two inline elements in a QWeb body vanished on every write. Only ASCII layout whitespace is stripped now.


Also fixed: `app_builder_ui` inherited a mixin from a module it did not depend on (aborting the registry if installed alone — the mixin now lives in the engine); `_assign` silently no-op'd for records another module owned; freshly written files were all reported as drifted; and several codegen fidelity bugs where a graduated computed field came back read-only, a stored related field came back unstored, and a valueless `Selection` produced un-importable Python.

### What running beside the rest of OCA found

15.  **A built app icon takes `web_responsive` down.** The app builder gave its root menu `web_icon = "fa fa-cube,#FFFFFF,#875A7B"` — the `icon_class,color,background` form core documents and its own apps menu renders. But that form carries no `web_icon_data`, and the apps menu `web_responsive` installs in its place assumes every app has some: its `getWebIconData` calls `.startsWith` on `false`, `AppMenuItem.setup` throws, and Owl destroys the root component — a white screen for the whole client, from one menu. Upstream `18.0` has the same code. The builder now seeds a real `static/description/icon.png` into the package (a copy of core's placeholder tile, written once and never regenerated, so a replacement survives) and points `web_icon` at it in the two-part `module,path` form every consumer reads. It is also simply what a hand-written app looks like.

### The console — what the drag-and-drop client turned out to be

The composer client the first draft of this document left for last was built as a **studio console** (`app_builder_view/static/src/console/`): full-screen, a sidebar of Add | View | Properties, a canvas that renders the *real* view, and top-bar tabs the other addons register into (`app_builder.console_tabs`). Five decisions carry it:

-   **Identity is minted by the server, on the tree it edits.** `studio.view.editor.canvas()` (`models/studio_view_canvas.py`) takes `get_combined_arch()` — the same tree `apply_at` and `move_node` read — and `tools/canvas_stamp.py` appends one class token per node, `o_studio_n_<ordinal>`, before the arch is postprocessed. The browser hands the token back as a descriptor `{kind: "node", token, arch_version}`, and the server re-stamps the current arch to find the node; a token is never an xpath and never survives an arch change. The `arch_version` is `sha1(view_id + combined arch)`, checked once in `apply_operation`, and a mismatch is `StudioStaleView` — reload silently, ask again.
-   **The canvas is the real view, rendered under a controller that cannot save.** `<View>` is given `arch`, `fields` and `relatedModels` so it makes no `get_views` call and nothing is cached; `canvas_views.js` derives `app_builder_canvas__<type>` classes whose controllers no-op `beforeVisibilityChange`, `beforeUnload` and `beforeLeave` — a stock form autosaves on a hidden tab — and whose renderers cannot resequence.
-   **Dragging is the website builder's own hook.** `useDragAndDrop` from `@html_editor/utils/drag_and_drop` (present in 18, 19 and master) matches a helper against zones by geometry; `zones.js` lays the zones out from the node table the moment a drag starts, as bars between children of every container whose `accepts` takes the payload's tag, and `drag.js` turns the drop into exactly one `drop_at` RPC.
-   **A field a Python-owned model cannot have yet is a ghost.** The drop stages it on the model draft with an *anchor* — the view, a locator minted now, the position, the arch version — and `canvas()` splices a `<widget name="app_builder_pending">` at every anchor that still resolves, so the pending field sits in the form where it will land. Apply places it through the same operation path, history and files included; a `<widget>` was chosen because it renders in a form group, as a list column and in a kanban card, where a `<div>` would not.
-   **Undo and redo are per base view, whole-arch snapshots** (`studio.view.edit` gained `arch_after`, `superseded`, `action_redo` and `stack_for`), and the extension view is recreated on redo rather than cascading the history away with it.

What the console work discovered, in the same spirit as the list above:

16.  **A generated label carries no token.** The form compiler gives a `<field>` in a group its label, and that label takes the *group's* classes, never the field's; its `for` names an input that only exists in edit mode. So a click on a label is resolved through the layout — the label's cell is followed by the widget's cell in 18, 19 and master (`compat.labelWidget`) — and a field's outline is its label cell and its input cell together (`compat.rowRect`). That pair is the same DOM in 18, 19 and master; what differs is the wrapper around it -- 18's `.o_wrap_field` wraps a whole grid *row*, so in a `<group col="4">` it holds two fields -- which is why the rect is built from the cells and never from the wrapper.

17.  **The smart-button box renders in the control panel.** `form_controller.xml` puts the button box in a control-panel slot, not in the sheet, so a canvas that dropped the control panel to look clean lost every smart button. The panel stays mounted; the pager and the breadcrumb are hidden by stylesheet.

18.  **Models that patch their own arch at read time are not shown.** `account.analytic.line` inserts plan columns in `_get_view()` unless `context.studio` is set — the same opt-out Enterprise takes — and stamping *that* tree would shift every ordinal against the one `apply_at` edits. The canvas stamps the combined arch and states the limit instead of working around it.

19.  **`arch_version` is language-independent.** `arch_db` is a translated field, so two builders in two languages would have hashed two different trees of one view and refused each other's edits as stale. The version is taken from the combined arch read at `lang=None`.

20.  **The owned path needs a locator guard.** A locator is minted on the combined arch but a view the package owns is edited by applying the spec to its *primary* arch, which has no foreign extensions in it — so a positional locator next to another module's insertion lands on the wrong node, or on none, with a raw `ValueError` from core. Every owned-path locator now has to select exactly one node in the primary arch, and one that matches what the minting step expected; anything else is refused with "that element comes from another module's extension of this view". Every container the studio creates is named (`studio_<kind>_<hex>`) so its locator is `//tag[@name]` and never positional.

21.  **A draft is transient, and the default window is an hour.** `studio.model.draft` is a `TransientModel`; the server's `transient_age_limit` is one hour of idle time and the daily vacuum deletes what has aged out — with the anchors of every ghost on the canvas. `_transient_max_hours = 168`, and the console re-opens a vanished draft from its package model rather than crashing.

22.  **A form labels a field only in a group.** The form compiler draws a label for a `<field>` exactly when it is a direct child of an inner group (`compileGroup`, `!isOuterGroup`); on the sheet, in a tab, in columns or in a row div it renders bare, whatever its `string` says — so a field dropped between a group and a notebook, then relabelled from the panel, changed the arch and nothing on screen. Core's own answer is a `<label for="name"/>` before the field, which the compiler pairs with it wherever it stands and renders with the field's label. The rule is now *a field's label follows the field*: the node table says where each form field's label comes from (`label: {shown, by: "group"|"label"|null, token, in_group}`); a field dropped, placed on Apply or moved to where none would be drawn is given one in the same edit (`_label_wanted`, `_op_add_field`, `_op_move_node`); one carried into a group drops it, because the group draws its own; removing a field removes its label; and the panel's **Show label** switch does the same by hand — `<label for>` off a group, `nolabel` in one. A `<label for>` is a node of its own, located by `for` (`IDENTIFYING_ATTRS`), captioned for its field, and never *named* for it, or the first node called `x` would be the label rather than the field.


**The composer is retired.** Once the console could stage, edit, remove and reorder a Python model's fields (the View tab's *Model* list, and *Edit definition* / *Remove from model* on any field of an owned model), the field-list-beside-a-preview it grew out of was a second UI for the same draft, guaranteed to fall behind the first. `Compose` on a model now opens the console on whichever view the model has; the composer's field popover survives as the console's field editor (`app_builder.field_editor`), and `studio.model.draft` is the same buffer underneath.

### The console is the studio — the shell, the panes and what they found

The second iteration made the console's chrome the whole product (PLAN.md §X6). Its shape: a `StudioShell` (`console/shell/shell_model.js`, Owl-free) holding the three scopes — package, model, view — and a pane registry (`app_builder.panes`) with three entry shapes: a custom pane (a component), a **record pane** (a server surface's name and a few strings; the console's `RecordPane` / `RecordSidebar` / `RowEditor` do the rest), and a **flow** (a stepper hosted in the content slot). The server side is one contract, `studio.record.surface` (`app_builder_base/models/studio_record_surface.py`): `catalogue` (sections of typed `catalogue.Row`s, templates), `rows`, `describe`, `write_record`, `create_record`, `remove_record`, `duplicate_record`, `run`; each surface is an AbstractModel over one Odoo model, with hooks for the sentence a card says, who owns a record, why a foreign one is not edited here, and what a record's children are. What it found:

**The outline** (`console/sidebar/outline.js`) is the view as a tree above the sidebar's tabs — Figma's layers, Xcode's navigator — and it cost the server nothing: the canvas payload's node table already carries `parent`, `children` in document order, `accepts`, `movable` and `hidden`, so the tree is the same table the drop zones are laid out from, and a row is selected, hovered, moved and removed through the same `select`, `hoverAt`, `drop_at` and `remove_at` as the canvas. Two pure modules do the thinking: `outline_tree.js` flattens the table into rows (a `<label for>` a field owns is not a row; a node the table marks unselectable is not either), keys what a person did to the tree by *path* rather than token, and turns a key press — Alt with an arrow — into the one `{target, position}` a drag would send, checked against `accepts` and the moving subtree before the server checks again; `outline_zones.js` lays drop zones over the rows so the tree is a second layer of the one drag (`drag.js` reads a provider the outline leaves on the model), with a gap that closes several containers cut into bands by indent so "after the last field, in the group" and "after the group, in the sheet" are both there to aim at. A row click *reveals*: the canvas switches to the node's page and scrolls to it, and the properties open as for a click on the canvas — the tree stays above them, which is the whole point of the split. Hidden nodes are listed dimmed, a staged field with its clock; the panel's height, whether it is open and what is folded per view are this browser's to remember.

23.  **A client action's URL is its `params`.** `updateActionState(patch)` writes every non-`PATH_KEYS` key of the patch to the query string and hands them back as `action.params` on reload; `static path = "studio"` gives `/odoo/studio`. The model key has to be `res_model` — `model` is one of the router's own keys and would be swallowed. Browser Back and Forward *remount* the client action (`loadState → doAction`); accepted, since the URL carries everything, and the alternative is the website builder's `skipRouteChange` hack.

24.  **A loop variable that shares a name with a getter of its component is silently not assigned.** Owl's loop context is `Object.create(component)`; assigning `ctx["row"] = ...` where the prototype has a getter-only `row` fails without an error in sloppy mode, and every iteration sees the getter's value — two rows, one key, "duplicate key in t-foreach: undefined". `t-as="row"` beside `get row()`, `t-as="step"` beside `get step()`: renamed, and worth a grep whenever a template gains a loop.

25.  **`env.config.resModel` is not always there.** The cog item read the model from the view's env config, which carries the view id and type but not the model on every view; a fresh manual model with no stored list view opened the console with nothing to show. The controller's action always names it.

26.  **A reference the file cannot carry is refused before the write.** The serializer emits a many2one as `ref="module.name"` and raises, from deep inside `studio_capture`, for a record with no external id — a mail template made by hand, a user. The surfaces check the ids of every many2one and many2many value first and say it in the person's words: *"is only in this database: it has no external id, so the package's file could not point at it."*

27.  **The draft wrote the new source before the snapshot.** `studio.model.draft.action_apply` used to write the rewritten `.py` and *then* call the package apply, whose snapshot recorded the new bytes as `content_before` — a rollback restored the wrong file. The draft's sources now go through `action_apply(overlay=...)`, into the same sequence as everything else, and the snapshot holds what the file had.

28.  **A server that cannot reload in place still applies.** Under workers, or when `reload_mode` is manual, `action_apply` writes the files, commits and stops with the apply in `awaiting_restart`; the pill says *Restart needed* until the process boot id changes, and `place_pending` finishes after the restart. Applies a dead process left `pending` are reaped by the workspace on the next read — other boot id *and* older than two minutes, the second condition because a live apply is `pending` for the length of one reload.

29.  **The internal report layout needs the printing context.** `web.internal_layout` stamps the time with `context_timestamp`, which `ir.actions.report._render_template` supplies and a bare `ir.qweb._render` does not; the preview passes the same names a printed report gets.

30.  **`ir.ui.menu.search` hides a folder with no children.** A menu with no action is shown only if something visible sits under it, so the surface that lists a package's menus reads them with `ir.ui.menu.full_list`, or a submenu made a moment ago has no parent to sit under.

31.  **The leak detector's snapshot can be incomplete.** `TransactionCase.check_attrs` compares class attributes after each test with a snapshot from `setUpClass`; `setup_models` (any test that creates a manual model) puts `_onchange_methods` and two siblings on *every* class, and after a preceding `HttpCase` some classes have been seen without them — every test of the next class then fails for nothing. `StudioCase` primes the three attributes before the snapshot.

32.  **A tree keyed on ordinals forgets itself after every edit.** The node table is minted anew — every token an ordinal — on every edit, so a folded group or the row the keyboard is on cannot be remembered by token: the outline keys both by a *path* of tags and names (`form:#0/sheet:#0/group:left/field:city`) that the next table answers to, and a keyboard move follows its node to the path it will have, not the token the server selects — `_findAgain`'s first rule can land on a neighbour for an unnamed node moved one slot. Two more things the tree knows that the canvas need not. A drop "before a field" whose own `<label for>` stands just before it lands *between* the label and the field (the server follows the label of what is moved, not of what is dropped beside), and the label is not a row, so the tree anchors on it. And the drag hook prevents the default of a press on anything it could pick up — every movable row — so a click gives a row no focus of its own; the row takes it by hand, or the arrows that follow would go to the body. Zones drawn over rows the list has scrolled away still have a box as far as `getBoundingClientRect` can tell, sitting over whatever is below the list: the outline's zones are clipped to the list's own box and laid out again on its scroll, which the canvas never needs.

## Status

**886 unit tests** across `app_builder_base`, `app_builder_model`, `app_builder_view`, `app_builder_ui`, `app_builder_report` and `app_builder_approval` — the console's tours among them (the canvas, every record pane, the flows to their review step) — 104 hoot tests run from the `app_builder_view` suite, and five end-to-end probes. CI runs ruff + pre-commit and the suite against both Odoo and OCB 18.0 in the OCA CI containers.

-   `app_builder_base` — packages, serializer framework, canonical writer, drift, the spec layer (`modelspec` / `pycodegen` / `pyparse`), apply + snapshot + rollback, reload modes, pre-migration generation, scaffold
-   `app_builder_model` — model & field builder, app builder, adopt
-   `app_builder_view` — view editor: operation API, server-minted canvas identity, the console (the shell, Home, Changes, the record-pane framework, the flows, drag-and-drop, properties, undo/redo, staged fields)
-   `app_builder_ui` — menus, actions, ACLs, record rules, automations, as surfaces the console's panes render

### The three invariants

The original one — `load_from_files(serialize(db)) == db`, byte-identical — is **false by construction** for a Python-backed model, because the database is produced by class loading rather than by the files being compared. It splits:

-   **I1, the codegen fixed point** (`tests/test_modelspec.py`, no database): `parse(render(spec)) == spec` and `render(parse(src)) == src`, over every ttype, every attribute toggle and every pair of them. This is the primary determinism guard now, and it is strictly stronger than byte-identity on a fixture — it is what makes the _parser_ safe. One that dropped a `help=` string would satisfy the second property forever, on a file that had quietly lost the developer's text.
-   **I2, reflection agreement** (`tests/e2e/probe_reflection.py`): after a real install in a fresh process, the metadata matches a _prediction_ of what `_reflect_model_params` / `_reflect_field_params` will write. Only the keys reflection maintains may be compared, and the comparison runs at `lang=None` because `upsert_en` writes only the `en_US` slot.
-   **I3, the data-file round trip** — unchanged, narrowed to what is still XML/CSV: views, actions, menus, ACLs, rules, automations, sequences, and `x_` manual fields on core models.

### Why some tests cannot be `TransactionCase`s

`ir.module.module._button_immediate_function` raises outright when `threading.current_thread().testing` is set, so every path that installs, upgrades or reloads a module is unreachable from the normal suite. Those live in `tests/e2e/` and drive real registries in real processes: `probe_reimport` (is in-process re-import sound?), `probe_reflection` (I2), and `probe_scaffold` (can a plain user actually use what we built?).

Remaining:

-   **The canvas** — inline x2many subviews are visible but not droppable, a kanban card written with `t-esc` has no addressable parts, master's `card` view type (a kanban whose card lives in another view) is reserved for by `nodes[].view_id` and not handled, two consoles on one package are serialised only by the transaction and the arch-version check.
-   **The panes** — what §X6 deferred and says so in the UI: sequences, crons and defaults have no pane (Changes lists their files), a foreign access line or rule is not copied, a foreign automation is not switched off from source, the approval mixin is not removed, there are no bulk actions, the menu tree is reordered with buttons rather than by drag, and the legacy `action_open` list openers are still on the models though nothing calls them.
-   **Relationships** — one2many with automatic inverse creation and notebook placement; then sub-models.
-   **19.0** — the code is kept 19.0-clean but is only tested on 18.0. Several OCA dependencies are not ported to 19.0 yet.
-   **Adopting two custom models that reference each other** in one operation is untested; adopt them one at a time.
-   **`many2one_reference`** cannot be _built_ by the field editor, because the field needs a `model_field` companion naming the model its id belongs to and there is no way to declare one from the picker. Serializing an existing one is fine: the companion is read and the id leaves as an xmlid.

## Reference reading

Odoo core (read, don't modify): `odoo/addons/base/models/ir_model.py`, `ir_ui_view.py`, `ir_actions.py`, `ir_module.py`; `odoo/tools/convert.py`, `odoo/tools/template_inheritance.py`; `odoo/modules/{module,loading,registry}.py`; `addons/base_import_module/models/ir_module.py`; `addons/web/static/src/views/{view_compiler,view_service,debug_items}.js`.

Pattern references in OCA: `reporting-engine/bi_sql_editor` (materialising a model + views + action + menu from one record), `odoo-pim/attribute_set` (dynamic fields via `_inherits` on ir.model.fields, and arch injection), `server-tools/upgrade_analysis` (writing generated files into an addons path), `maintainer-tools/tools/manifest.py` (manifest read/write).

## Verification

```sh
# unit suite
python odoo/odoo-bin -c odoo.conf -d studio_test -i app_builder \
  --test-enable \
  --test-tags /app_builder_base,/app_builder_model,/app_builder_view,/app_builder_ui,/app_builder_report \
  --stop-after-init
# hoot unit tests, in a browser: /web/tests?filter=%22%40app_builder_view%2F%22

# the paths a TransactionCase cannot reach: install, upgrade, reload
app_builder_base/tests/e2e/run_probes.sh -c odoo.conf -t studio_test
```

Static and runtime type checks (what each one is for, and the traps behind them, are in [TYPING.md](TYPING.md)):

```sh
npx pyright                            # Python, standard mode; app_builder_*/tools also strict
node scripts/typecheck.mjs            # tsc, TypeScript, our sources only (vendored diagnostics filtered)
npx eslint '**/*.ts'                   # type-aware: an `any` leaking in from untyped Odoo JS
node scripts/build_ts.mjs              # the committed .js must equal what esbuild emits from the .ts
npx prettier --check '**/*.ts'
APP_BUILDER_TYPEGUARD=1 <the unit suite above>   # tools/ under typeguard; needs `typeguard` installed
```

The `.js` beside every `.ts` is generated and is what Odoo ships -- edit the `.ts`. All of the above run in CI (`test.yml`'s `typecheck` job and the OCB `test` leg) and, where they can, in pre-commit; none of it has been run inside the OCA container yet.

End-to-end acceptance, in order:

1.  Create a package -> the addon directory appears with a manifest
2.  **Build an app** from a label -> a real Python class on disk with no `x_` anywhere, plus list/form/search views, an action, an app menu, ACL rows, chatter, activities and a sequence
3.  **Log in as a plain internal user** -> the menu is visible, records can be created, the reference numbers itself. _This is the one that matters_: the previous wizard failed it silently, because `env.su` bypasses every ACL check and the app looked perfect to whoever built it
4.  Edit a core view -> an _inheriting_ view at `priority=99` is written
5.  Edit a view the package owns -> its arch changes in place, no xpath patch against itself
6.  **Fixed point:** save again with nothing changed -> zero diff
7.  **Reflection:** re-read the metadata -> it matches what the source predicts, every field `state='base'`
8.  **Drift:** hand-edit a generated file -> an edit the parser understands is adopted; one it cannot read freezes the model and the file is kept verbatim
9.  **Destructive:** remove a stored field -> refused, then applied with a pre-migration that renames the column aside instead of dropping it
10.  **Read-only:** point at a read-only checkout -> editor disabled, no traceback

Steps 2, 3, 6 and 7 are automated in `tests/e2e/`.

And for the console, on a dev DB, in order:

1.  Open a core contact form -> cog -> the console opens full-screen with Add / View / Properties; the real form renders with its smart buttons; no `get_views` request is made for the canvas; no record is created or saved while switching browser tabs away and back
2.  Click a field -> Properties opens with the option rows; change Label -> "Saving…" then "Saved"; the written file is an inheriting `.studio` view at priority 99; Ctrl+Z / Ctrl+Shift+Z round-trip it
3.  Drag "Email" from Existing Fields between two fields of a group -> it lands exactly there; drag it into an empty group -> appended; drag it to another tab (resting on the tab switches it) -> moved; drag "Columns" into the sheet -> one history entry
4.  Drag "Text" onto the contact form -> an `x_` field exists, is placed, the Label input is focused; undo removes it from the view and it appears under Existing Fields; the package XML contains no `o_studio_` token
5.  Build an app, open its form -> drag "Decimal" between two fields -> a pending ghost in place and "1 pending · Apply"; drag "Priority" -> a second ghost; Apply -> one reload, both fields real and exactly where they were dropped, files written, `git status` shows the model and the view
6.  Open the kanban -> drop "Email" into the card's `main` -> every card shows it; the arch has one new `<field>` in the card template
7.  Two browser sessions: A adds a field, B drops -> B sees "refreshed — try again" and nothing is written twice
8.  Save again with nothing changed -> zero diff; `test_canvas_is_pure` holds against the same views
9.  Point at a read-only checkout -> the console opens read-only, no traceback
10.  Repeat 1–4 against the 19.0 checkout with only `compat.js` differences (see `FORWARD_COMPAT.md`; not yet run on a 19 server)

Steps 1–6 are driven by the tours in `app_builder_view/tests/test_console_tour.py` and the hoot tests under `app_builder_view/static/tests/` (the staging half of 5 by tour, the reload half by `app_builder_base/tests/e2e/probe_console_apply.py`); step 7's refusal by `tests/test_drop_at.py` (a stale version writes nothing) and step 8 by `tests/test_canvas.py::test_canvas_is_pure`.
