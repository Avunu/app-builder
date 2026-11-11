# App Builder for Odoo — forward compatibility notes

What the console's port to the next Odoo branches will have to do, with the core lines
that say so. Written on 18.0 against three checkouts and kept factual: every claim
carries a `file:line`, and the ones a test run can check are pinned by
`app_builder_view/static/tests/compat.test.js` and `identity.test.js`. Paths under
`18:`, `19:` and `master:` are relative to the 18.0 checkout (`odoo/`), the 19.0
checkout and the master checkout the audit read; everything else is relative to this
repository.

## The three checkouts, and where the lines are drawn

| Line   | `version_info`                                       | Owl                                                | What changes for us                                             |
| ------ | ---------------------------------------------------- | -------------------------------------------------- | --------------------------------------------------------------- |
| 18     | `(18, 0, …)`                                         | 2.8.4 (`addons/web/static/lib/owl/owl.js` 18:5869) | the branch this is written on                                   |
| 19     | `(19, 0, 0, FINAL)` (`odoo/release.py` 19:15)        | 2.8.4 (19:5869, same build)                        | props and DOM renames; a server rename (`group_ids`)            |
| master | `(19, 5, 0, ALPHA, 1)` (`odoo/release.py` master:15) | 3.0.0-alpha.49 (master:1776)                       | Owl 3 port; callable refs; `force_delete`; the `card` view type |

**master is not `20` yet.** Owl 3 and the callable-ref change both shipped while
`release.py` still says `19.5`; `session.server_version_info` reports that on a master
server. `compat.js` therefore draws the master line at `versionAtLeast(19, 5)` and the
19 line at `versionAtLeast(19)`. Nothing else in the console reads the version
(`grep server_version_info` under `app_builder_view/static` finds `compat.js` and
`compat.test.js` alone). The number is where master stood when it was audited; a saas
release between 19.0 and 19.5 has not been read and is not a target.

**A saas major is a string.** `odoo/release.py` 19:14: "during release, the MAJOR
version can become an arbitrary string ('saas~xx')", and that string is what
`session.server_version_info[0]` carries on every saas build. Core reads it by replacing
the `~` (`views/widgets/documentation_link/documentation_link.js` 18:23-27);
`compat.serverVersion()` reads the digits, so `saas~19.2` is `[19, 2]` and takes the 19
line rather than falling back to 18 -- the one direction that would be wrong on a
19-line server. Only a value with no digits at all falls back, and then to `[18, 0]` as
a whole.

## The one seam: `app_builder_view/static/src/console/compat.js`

| Export                               | 18                                   | 19                  | master                      | Core lines                                                                                                                                                                                                                                                                                                                                                                                               |
| ------------------------------------ | ------------------------------------ | ------------------- | --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `dragRef(ref)`                       | `{el}`                               | `{el}`              | `() => el`                  | `web/static/src/core/utils/draggable_hook_builder.js` 18:91 `ref: [Object]`, :897 `ctx.ref.el`; 19:92, :920; master:142 `ref: [Function]`, :1004 `ctx.ref()`. `html_editor/static/src/utils/drag_and_drop.js` 18:70, 19:70 `initialParams.ref.el`; master:70 `initialParams.ref()`. The check is `typeof` (18:935-948), so one value cannot satisfy both.                                                |
| `dragExtraParams()`                  | `{allowDisconnected: true}`, ignored | honoured            | honoured                    | 19:89, :104, :584, :810; master:139, :155, :643, :884. 18's validator iterates the params it _accepts_ (18:935-948) and never refuses an unknown key, so there is no branch. Needed because a tab switch re-renders the page the source field sits on.                                                                                                                                                   |
| `readonlyViewProps()`                | `{mode: "readonly"}`                 | `{readonly: true}`  | `{readonly: true}`          | `views/form/form_controller.js` 18:143-145 (`mode`), 19:140, master:133; `form_renderer.js` 19:52, master:40. The wrong key is an "unknown prop" error in dev mode.                                                                                                                                                                                                                                      |
| `rowRect(el)` / `labelWidget(label)` | same                                 | same                | same                        | `views/form/form_group/form_group.xml` 18:43-50, 19:46-54, master:44-52 (booleans 18:54-60, 19:58-64, master:56-62): a generated label's `.o_cell.o_wrap_label` is immediately followed by the widget's `.o_cell.o_wrap_input`, so the row is the sibling pair in all three and neither export branches. See "`.o_wrap_field` removed in 19" for the wrapper that does differ, and why it is never read. |
| `TAB_SELECTOR`                       | `<a class="nav-link">`               | `<a>`               | `<button class="nav-link">` | `core/notebook/notebook.xml` 18:9, 19:9, master:10. Class-only selector; `name` is on the element in all three.                                                                                                                                                                                                                                                                                          |
| `isStaleError` / `isConfirmError`    | same                                 | same                | same                        | `data.name` is `f"{module}.{name}"` and `data.context` is `getattr(exception, 'context', {})`: `odoo/http.py` 18:432-441, 19:469-478; `odoo/http/dispatcher.py` master:78-91.                                                                                                                                                                                                                            |
| `clearViewCaches(env)`               | `env.bus`                            | `rpcBus` + key      | `rpcBus` + key              | `views/view_service.js` 18:56 listens on `env.bus`; 19:51 and master:55 trigger `rpcBus "CLEAR-CACHES", "get_views"`; `core/network/rpc.js` 19:85, master:85 invalidate. Neither bus listens to the other's event, so both are triggered and there is no branch.                                                                                                                                         |
| `fieldSelectorFollow(follow)`        | `{followRelations}`                  | `{followRelations}` | `{followRelation}`          | `core/model_field_selector/model_field_selector.js` 18:21, :68 `followRelations`; master:24, :73 `followRelation` (a boolean or a function). The wrong key is an "unknown prop" error in dev mode. Used by the record panes' `RowEditor` for `field_path` rows.                                                                                                                                          |

What the shell relies on for its URL, identical in all three unless said:

- A client action receives `updateActionState(patch)`
  (`webclient/actions/ action_service.js` 18:92, :588; master:99, :653); every key of
  the patch that is not one of the router's own goes to the query string and comes back
  as `action.params` on reload. The router's own keys are
  `PATH_KEYS = ["resId", "action", "active_id", "model"]` (`core/browser/router.js`
  18:10, master:10), which is why the console's model key is `res_model` and never
  `model`.
- `static path = "builder"` on the client action gives it `/odoo/builder` (18 and master
  alike); Back and Forward remount it (`loadState → doAction`), which the shell accepts:
  the URL carries the pane, the package, the model, the view and the selected record.

What `drag.js` relies on beyond the seam, identical in all three unless said:

- `useDragAndDrop` is exported from `@html_editor/utils/drag_and_drop` (18:207-209; same
  path in 19 and master) and is Owl-free (`useNativeDraggable`, 18:53-92): created in
  `onMounted`, destroyed by hand.
- `scrollingElement` must be a function: 18 accepts `[Object, Function]` (18:102), 19
  and master only `[Function]` (19:102, master:107). The console always passes a
  function.
- `element` in `onDrag`/`onDragEnd` is the _helper_ in 18 (18:120-121 overwrite
  `ctx.current.element`) and the source in 19 (19:120) and master (master:125).
  `drag.js` captures the source in the `helper` callback and never reads `element`
  (`drag.js:290-292`).
- `dropzones()` is matched by geometry against the helper's box (`drag_and_drop.js`
  18:149-156; `core/utils/ui.js` 18:100-111 `touching`, :12-24 `closest`), and
  `document.body` is `pe-none` for the whole drag (`draggable_hook_builder.js` 18:537,
  19:542, master:604) — which is why the tab dwell is a timer over rectangles
  (`drag.js:534-562`).
- Any non-modifier key, a `pointercancel` or a fresh `pointerdown` ends the drag with
  the last zone still set (18:657-668, :674-676, :689). `drag.js` flags the cancel
  first, in the capture phase (`drag.js:152-174`).

## DOM contracts the overlay stands on (pinned by `identity.test.js`)

Identical in 18, 19 and master; read, and in 18 also run:

| Contract                                                                                        | 18                                                     | 19       | master                            |
| ----------------------------------------------------------------------------------------------- | ------------------------------------------------------ | -------- | --------------------------------- |
| `copyAttributes` forwards `class` (and `style`) from an arch node to its compiled element       | `views/view_compiler.js:97-116`                        | :97-116  | :99-118                           |
| `.o_field_widget[name]` is the widget's root                                                    | `views/fields/field.xml:5`                             | :5       | :5                                |
| `div.o_form_sheet_bg > div.o_form_sheet`                                                        | `views/form/form_compiler.js:690-693`                  | :660-663 | :664-667                          |
| `div.o_inner_group.grid`, `div.o_group.row`                                                     | `form_group.xml:15`, `:5`                              | :15, :5  | :15, :5                           |
| a list heading is `th[data-name]`; the class never reaches it                                   | `views/list/list_renderer.xml:22`                      | :22      | :26                               |
| a widget-less kanban `<field>` is a bare `<span t-out>` without `name`, and its class is copied | `views/kanban/kanban_compiler.js:111`                  | :107     | `views/card/card_compiler.js:120` |
| the smart-button box renders in the control panel, not the sheet                                | `views/form/form_controller.xml:29` (`layout-actions`) | :27      | :22 (`control-panel-actions`)     |
| `static target = "fullscreen"` on a client action hides the navbar                              | `webclient/actions/action_service.js:612-629`          | :664-665 | :688-689                          |

## The Owl 3 port (master line)

master runs Owl `3.0.0-alpha.49`. Its exports (`owl.js` master:20-88) drop `useState`,
`useRef`, `reactive`, `useEnv`, `useSubEnv`, `useComponent`, `useExternalListener` and
`onWillRender`, and add `signal`, `proxy`, `useProps`, `t`, `useListener`,
`useOnChange`, `computed`, `untrack`, `usePlugin`. master ships a bridge,
`web/static/src/owl2/owl3_compatibility_layer.js`, whose header (master:1-33) lists the
rewrites it still requires; it also throws on `static defaultProps` (master:44-52) and
re-exports `useEnv`, `useSubEnv`, `useLayoutEffect`, `onWillRender` from
`@web/owl2/utils` (`utils.js` master:13-16). The console was written so that the port is
mechanical; the checklist, with the files it touches:

| Rewrite                                                                                                                                  | Why                                                                                                                                                                                                                                                                                                                                                                                                                  | Console files                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ---------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `useState(x)` → `proxy(x)` (or `signal` for a scalar)                                                                                    | not exported by Owl 3 (`owl.js` master:20-88); core does it (`form_controller.js` master:222 `proxy(...)`)                                                                                                                                                                                                                                                                                                           | `shell/shell.js`, `top_bar.js`, `canvas.js`, `apply_dialog.js`, `systray_item.js`, `sidebar/add_tab.js`, `sidebar/view_tab.js`, `sidebar/properties_tab.js`, `sidebar/field_editor_fallback.js`, `sidebar/outline.js`, `canvases/search_lists_canvas.js`, `panes/{views_pane,home_pane,changes_pane}.js`, `record_pane/{record_pane,row_editor}.js`, `flows/{flow,create_package_flow}.js`; `app_builder_report/static/src/console/report_canvas.js`; `app_builder_model/static/src/{console_items,field_popover}.js`, `app_builder_model/static/src/flows/{build_app_flow,adopt_model_flow}.js` (the models — `shell_model.js`, `draft_model.js`, `console_model.js`, `record_pane_model.js`, `FlowModel`, `HomeModel`, `ChangesModel` — are plain classes wrapped by their component)                                                                      |
| `useRef("x")` + `t-ref="x"` → `x = signal.ref()` + `t-ref="this.x"`, read as `this.x()`                                                  | `form_renderer.js` master:62, :86; `form_compiler.js` master:69                                                                                                                                                                                                                                                                                                                                                      | `canvas.js` (`scroll`, `ground`), `sidebar/add_tab.js` (`root`), `sidebar/outline.js` (`root`, `list`, `divider`, `filter`), `sidebar/field_editor_fallback.js` (`label`), `canvases/search_lists_canvas.js` (`host`); `report_canvas.js` (`preview`); `field_popover.js` (`label`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `useEffect` → `useLayoutEffect`                                                                                                          | the bridge's own instruction (`owl3_compatibility_layer.js` master:17-20; the shim at :99-125)                                                                                                                                                                                                                                                                                                                       | `console.js`, `canvas.js`, `sidebar/add_tab.js`, `sidebar/view_tab.js`, `sidebar/properties_tab.js`, `sidebar/outline.js`, `canvases/search_lists_canvas.js`; `report_canvas.js`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `this.` prefix on every bare identifier in a template -- `props.`, `state.`, `env.`, methods, getters, `.bind` targets and `t-ref` names | the template context is `{this: component, __owl__}` (`owl.js` master:3715) and a bare name compiles to a context lookup that yields `undefined`, silently; core has 160 `t-if="this.props.` and none bare, prefixes getters too (`form_controller.xml` master:10 `this.footerArchInfo`), binds as `.bind="this.onX"` (95 sites under `web/static/src`, none bare) and refs as `t-ref="this.rootRef"` (98 templates) | the templates written before the shell: `canvas.xml` (`hasCanvas`, `showsSampleData`, `viewKey`, `viewProps`; `t-ref="scroll"`, `"ground"`), `systray_item.xml` (`target`, `tooltip`, `label`), `cog_menu_item.xml` (`onSelected.bind="onEdit"`), `top_bar.xml`, `apply_dialog.xml`, `pending_widget.xml`, `sidebar/add_tab.xml`, `sidebar/view_tab.xml`, `sidebar/properties_tab.xml`, `sidebar/field_editor_fallback.xml`, `canvases/search_lists_canvas.xml`; plus `app_builder_report/.../report_canvas.xml` and `app_builder_model/.../field_popover.xml`, `console_items.xml`. The templates written with the shell (`shell/shell.xml`, `panes/*.xml`, `record_pane/*.xml`, `flows/*.xml`, `app_builder_model/static/src/flows/*.xml`) already spell `this.` everywhere. Nothing is exempt: a template with no `props.` still names a getter or a ref. |
| `t-slot` → `t-call-slot`                                                                                                                 | `owl.js` master:4821, :4834                                                                                                                                                                                                                                                                                                                                                                                          | no `t-slot` in the console (`apply_dialog.xml:85` uses `t-set-slot`, which master keeps — 85 files under `web/static/src`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `static props = {...}` → `props = useProps({... t.string() ...})`                                                                        | the bridge installs `useProps()` itself (master:51) and tolerates the old schema, but core has moved (309 `useProps(` against 2 `static props = {` in `web/static/src`)                                                                                                                                                                                                                                              | 17 `static props` declarations across the console addons                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| no `static defaultProps`                                                                                                                 | throws (`owl3_compatibility_layer.js` master:44-52)                                                                                                                                                                                                                                                                                                                                                                  | none in the console — kept that way on purpose                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `t-esc` → `t-out`                                                                                                                        | deprecated with a warning (`owl.js` master:5495)                                                                                                                                                                                                                                                                                                                                                                     | most console templates still use `t-esc` for plain strings; a warning, not a break                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `t-portal` / `t-model` → `t-custom-portal` / `t-custom-model`                                                                            | bridge header master:13-15                                                                                                                                                                                                                                                                                                                                                                                           | none in the console                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `markRaw`                                                                                                                                | still exported (`owl.js` master:20-88)                                                                                                                                                                                                                                                                                                                                                                               | throughout `console_model.js` (sixteen sites) — no change                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |

Everything with logic in it — `geometry.js`, `zones.js`, `outline_zones.js`,
`outline_tree.js`, `split.js`, `drag.js`, `identity.js`, `overlay.js`, `options.js`,
`console_model.js` (`markRaw` aside) — is Owl-free by design, so the rewrite stays in
the components and their templates.

## Server-side renames

| What                                                                                                            | 18                                                             | 19                                                                                         | master                                       | Where the builder stands                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| --------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------ | -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `res.users.groups_id` (and `ir.ui.view`, `ir.ui.menu`, `ir.actions.act_window`, `ir.rule`, `ir.actions.report`) | `groups_id` (`odoo/addons/base/models/ir_ui_view.py` 18:179)   | `group_ids` (19:175; `ir_ui_menu.py` 19:29; `ir_actions.py` 19:329; `res_users.py` 19:257) | `group_ids`                                  | Nothing written for the console spells either: `app_builder_base/tools/compat.py` `groups_field(env, model)` answers per model at runtime, and the surfaces (`builder.rule.surface`, `builder.menu`, `builder.report`) read and write through it as a virtual `groups` row. The serializers written before this project still spell `groups_id` (`app_builder_base/models/serializers/{ir_ui_view,ir_ui_menu,ir_actions}.py`) and are the 19 port's first server task. |
| module-uninstall flag on `ir.model` / `ir.model.fields`                                                         | `'_force_unlink'` (`ir_model.py` 18:37)                        | `'_force_unlink'` (19:36)                                                                  | `'force_delete'` (master:41-42, :368, :1019) | The console adds no use. The two pre-existing sites spell the string (`app_builder_base/models/builder_package.py:1179`, `app_builder_base/tests/common.py` `wipe_package_records`); the version-free spelling is `MODULE_UNINSTALL_FLAG` from `odoo.addons.base.models.ir_model`, present in all three.                                                                                                                                                               |
| `@http.route(type='json')`                                                                                      | `'json'` (`addons/web/controllers/dataset.py` 18:32)           | `'jsonrpc'` (19:28)                                                                        | `'jsonrpc'`                                  | No controller in this repository; the console speaks to the server through `orm.call` on `builder.view.editor` only.                                                                                                                                                                                                                                                                                                                                                   |
| `apply_inheritance_specs(..., pre_locate=)` default                                                             | `lambda s: True` (`odoo/tools/template_inheritance.py` 18:109) | `None`, normalised at 19:128                                                               | `None`                                       | `builder_view_editor.py:337` calls it without `pre_locate`; both defaults mean "locate everything", so nothing to pass.                                                                                                                                                                                                                                                                                                                                                |
| `ir.ui.view._postprocess_debug`                                                                                 | absent                                                         | present (19:1420-1428): hides `base.group_no_one` nodes                                    | present                                      | called through `hasattr` (`builder_view_canvas.py:161-162`).                                                                                                                                                                                                                                                                                                                                                                                                           |
| `Model._get_view_fields()` / `_get_view_field_attributes()`                                                     | present                                                        | present                                                                                    | present                                      | called rather than hard-coded (`builder_view_canvas.py:131, :158`).                                                                                                                                                                                                                                                                                                                                                                                                    |

## master's `card` view type and `<kanban card_id>`

master adds `card` to `ir.ui.view.type` (`ir_ui_view.py` master:164) and lets a kanban
point at one: `_postprocess_tag_kanban` inlines the card view's arch under the
`<kanban>` node at postprocess time when `card_id` is set (master:1765-1768), and the
card's `<main>`/`<footer>`/`<aside>` compile through `card_compiler.js` (master:30,
:97-107). 19 already removed the legacy `kanban-box` template (`kanban_arch_parser.js`
19:141 throws without a `card` template).

What that means for the console: a kanban's editable card may live in a _different_
`ir.ui.view`. Today every node of a canvas belongs to the view whose combined arch was
stamped, and `nodes[].view_id` is served as `None` for all of them
(`app_builder_view/tools/canvas_stamp.py:365`). The field is reserved for this: on the
master line the stamp will carry the card view's id on the nodes that came from it,
`drop_at`/`apply_at` will route those edits to the card view's own extension, and the
arch version will fold both views in. Until then a `card_id` kanban is one the console
has not been taught, and the honest answer is the same as for `t-esc` cards: edit as
source.

## `invalid_locators` (19 and master) as a future health check

19 adds `ir.ui.view.invalid_locators`, a computed Json (`ir_ui_view.py` 19:205,
`_compute_invalid_locators` 19:323-395) that locates every spec of an inheriting view
against its parent's combined arch and reports the ones that no longer resolve —
`{tag, attrib, sourceline}` per spec, or `[{broken_hierarchy: True}]`. It is
display-only (consumed by `web/static/src/core/ir_ui_view_code_editor/code_editor.js`),
never raises, and assesses `position="move"` sub-specs too (19:370-381).

The builder's own extension views are exactly the ones worth asking that question of
after an upstream change: the View tab's "Recent changes" could show "3 of this view's
edits no longer locate" from that field, with no code of ours to keep. On 18 the same
check is a loop of `locate_node(parent_combined_arch, spec)` over the extension's specs
(`odoo/tools/template_inheritance.py` 18:70-93).

## `.o_wrap_field` removed in 19

18's inner group wraps each grid _row_ in `div.o_wrap_field` (`form_group.xml` 18:19
iterates `getRows()`) — `display: contents` above the small breakpoint, so the wrapper
has no box of its own, and a row is not a field: an inner `<group col="4">`, or two
`nolabel` fields, puts two label/input pairs in one wrapper (nine core 18 view files
carry a `col="4"` group, e.g. `addons/stock/views/product_strategy_views.xml:54`). 19
and master emit the label cell and the input cell directly into the grid (19:19-40,
master:19-37); only a boolean keeps a wrapper (`.o_wrap_field_boolean` 19:57,
`.o_wrap_field_inline` master:55). The console never reads any of those wrappers:
`compat.rowRect` walks from the widget's `.o_cell` to the `.o_cell.o_wrap_label` before
it, which is the same pair in all three, and the zones are laid out from the rects it
returns (`geometry.test.js` pins one field per row and two fields per row on the 18
layout, and the 19 layout).

## Why `html_editor` is a dependency

`app_builder_view/__manifest__.py` names `html_editor` although it is `auto_install` on
top of `web` in all three branches (`addons/html_editor/__manifest__.py` 18:15-16): the
console imports `@html_editor/utils/drag_and_drop` (`console/drag.js:52`), and an import
resolves only if the module is _installed_ -- asset bundles are built from every
installed module (`odoo/addons/base/models/ir_asset.py` 18:305-312
`_get_installed_addons_list` reads `registry._init_modules`), not from an addon's
dependency closure. `auto_install` decides what a fresh database gets, not what stays:
`html_editor` can be uninstalled, and then `web.assets_backend` has no
`drag_and_drop.js` and the console fails at import. `depends` is what makes that
uninstall take `app_builder_view` with it. The hook's file is in `web.assets_backend` in
each branch — directly in 18 (`html_editor/__manifest__.py` 18:21-22
`html_editor/static/src/**/*`), and through `html_editor.assets_editor` →
`html_editor.assets_readonly` → `html_editor/static/src/utils/**/*` in 19 (19:34-35,
:46-49, :71-81) and master (master:35-36, :44-47, :73-83). `html_builder` itself (19+)
is an `html_editor` plugin stack bound to a contenteditable iframe and does not exist in
18; its conventions were mirrored, not imported.

## Type-checking against a new branch

The types are checked against a _specific_ Odoo checkout, and these things in this repo
encode which one. Moving to 19.0 (or a saas/master line) is not only the runtime changes
above; each of these has to be pointed at the new tree and the checks re-run, because a
vendor change shows up as a type error long before it shows up as a broken console.

- **`tsconfig.json`.** `paths` maps `@web/*`, `@html_editor/*`, `@web_tour/*`, `@mail/*`
  to the checkout (`.odoo-nix/odoo/addons/...`), and `include` lists Odoo's ambient
  `@types/*.d.ts` files _by path_. Those files move and are renamed between series --
  `TYPING.md`, Known traps, says why each one is on the list. A 19.0 branch type-checks
  against 19.0's `@types`.
- **`pyrightconfig.json`.** `extraPaths` and the venv, both of which the dev shell
  makes.
- **The typed facades are transcriptions of vendor shapes**, not imports:
  `console/odoo.ts` (`useService`'s services, the dialog, `user.hasGroup`, the
  registries), `console/l10n.ts` (`_t`), `console/compat.ts` (the RPC bus). Each cites
  the vendor file it was read from. After an OCB bump, re-read those against the new
  source; nothing else will tell you one has gone stale, because the vendor JS is
  `checkJs: false` on purpose.
- **eslint is the tripwire for the above.** Untyped vendor JS can carry TypeScript's
  `error` type into our code without a `tsc` diagnostic (a JSDoc that names a type the
  file never declares -- `_t`'s did), and the `no-unsafe-*` rules are what report it. A
  bump that introduces one shows up there first. Also re-check the vendored files that
  opt themselves into checking with `//@ts-check` (`scripts/typecheck.mjs` filters their
  diagnostics out as not ours).

## What was checked how

- Run on 18: the whole suite, the tours and the hoot tests (`compat.test.js` pins the
  shapes each line gets from `compat.js` by patching `session.server_version_info`, and
  that the hook is importable, takes the console's params and refuses a wrong one).
- Read on 19 and master: every line cited above, and every `@web/...` and
  `@html_editor/...` module path the console addons import (20 of them) exists at the
  same path in both checkouts. No 19 or master database was run; the acceptance step
  "repeat 1–4 against the 19.0 checkout" in the plan remains to be done on a 19 server,
  where the expected diff outside `compat.js` is the `groups_id` serializers and nothing
  in `console/`.
