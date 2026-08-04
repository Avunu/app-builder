# App Builder — plan to feature completion

Companion to [DESIGN.md](DESIGN.md), which describes what exists and why. This describes what is missing against Odoo Studio (enterprise), what of it we deliberately will not build, and the order the rest should be built in.

## Where we stand

Measured against the seven upstream documentation pages (`content/applications/studio`, 3,112 lines), App Builder implements roughly a third of documented Studio functionality. The coverage is narrow but deep: what exists is more rigorous than Odoo's — deterministic source output, inheriting views rather than rewrites, real Python classes — while three of the six chapters are absent or near-absent.

| Chapter | Coverage | State |
| --- | --- | --- |
| Models, modules & apps | ~45% | Model builder and app scaffold solid; 7 of 14 suggested features missing |
| Fields and widgets | ~40% | All 15 ORM types; ~13 of ~40 widgets; no related or computed field in the composer |
| Views | ~35% | 5 of 11 types editable, 4 creatable; no buttons, tabs, or add/remove field in a view |
| Automation rules | ~55% | Inherits all of base_automation; the studio surface is one code-only wizard |
| Webhooks | ~60% | Functional through base_automation; no dedicated surface |
| PDF reports | ~5% | A serializer for ir.actions.report exists; nothing else |
| Approval rules | 0% | No equivalent of any kind |

The single most consequential gap is that **a field cannot be placed on a view the package does not own**. `_op_add_field` exists and `apply_operation` is public RPC (`studio_view_editor.py:147`); the client simply never calls either. Adding a field to a core Odoo form — the most common Studio gesture there is — has no path through the UI, despite the server being able to emit exactly the inheriting `<xpath>` it needs.

## What we will not build

Three categories, kept separate because they are different arguments.

**Made irrelevant by the approach.** Odoo Studio's export is a one-time, irreversible ZIP because the customization lives in a database. Ours is a directory under git from the first keystroke, so the ZIP has nothing to carry and the "export to module" milestone has already happened by the time the user sees anything.

| Odoo feature | Why it does not apply |
| --- | --- |
| Studio Export / Import ZIP | The addon directory is the artifact; git is the transport |
| "Export to module" | The default, not a milestone |
| "Reset report to standard version" | Delete the extension view, or git revert |
| Pricing-plan upsell warnings | n/a |

**Has no community implementation to build on.** After the OCA survey below this reduces to three: the **Cohort** view, the **Send WhatsApp** action, and **AI fields / Update with AI**. If a site runs the enterprise modules the underlying records are still serializable; only the builder affordance is out of reach, and §"Filling the gaps with OCA" makes even that recoverable.

**Superseded** — the need is real, only Odoo's shape of the answer was an artifact of its architecture. These stay in scope, redesigned:

| Odoo | Ours |
| --- | --- |
| "Include Data / Include Demo Data" in the export ZIP | Capture arbitrary-model records into the package's data/ (§X1). The need — shipping reference data with a module — is real; only the transport was ZIP-shaped |
| Rename a field by removing it from every view, then editing Settings → Technical | Rename with a generated migration (§X4) |
| Duplicate a standard report, then mutate the copy | Edit it as an inheriting qweb view (§P6). Odoo structurally cannot do this |
| Execute Code is a sandboxed string forever | Graduate it to a real method in the package (§X2) |

Everything else documented is in scope.

## Filling the gaps with OCA

Odoo Studio's feature list assumes the enterprise view renderers and the enterprise approval engine. Most of what that assumption buys has an OCA equivalent, already 18.0 and already in this workspace's pins.

| Enterprise feature | OCA answer | Version / status |
| --- | --- | --- |
| Gantt view | web_timeline (OCA/web) | 18.0.1.0.3, Production/Stable, depends web |
| Map view | web_view_leaflet_map (OCA/geospatial); base_geoengine adds geoengine | 18.0.1.1.2 |
| Approval rules | base_tier_validation + siblings (OCA/server-ux) | 18.0.3.4.1, Mature, depends mail |
| Sign field | none needed — the signature widget is in community web | — |
| Pivot measures | web_pivot_computed_measure (OCA/web) | 18.0.1.0.5 |
| Cohort view | nothing exists | — |
| Send WhatsApp | nothing exists | — |
| AI fields | OCA ai is connections and record→AI bridges (ai.bridge), not field-level generation | 18.0.2.0.1, Beta |

`base_tier_validation` lives in **server-ux for 18.0** and is being split into its own `OCA/tier-validation` repo for 19.0. The manifest dependency name is unchanged either way; only the repo pin moves, which matters because the code is kept 19.0-clean (DESIGN.md, "Status").

### Discover view types, do not hardcode them

The reflex — add `timeline` to `ADDABLE_VIEW_TYPES` — is the wrong move. Odoo already keeps a registry of installed view types: `ir.ui.view.get_view_info()` (`addons/web/models/ir_ui_view.py:22`) returns every type in the `type` selection that has view info, with its display name, icon and `multi_record` flag. Core seeds seven, `mail` adds `activity`, `web_timeline` adds `timeline`, `web_view_leaflet_map` adds `leaflet_map`, `base_geoengine` adds `geoengine` — each by extending `_get_view_info()` and the `type` selection together.

So `ADDABLE_VIEW_TYPES` (`studio_view_editor.py:738`) should be **derived from that registry**, gated on whether the studio has a scaffold and an option group for the type, and the picker should list the rest disabled with a reason — the "shown-but-disabled beats hidden" rule already stated in `available_field_types()` (`modelspec.py:229`).

Three things fall out. A site that installs an OCA view type we have never heard of gets it in the picker as soon as somebody contributes a scaffold. A site running enterprise gets `gantt` and `cohort` for free. And the engine acquires no dependency on any of them — the same discipline that keeps `base_automation` out of `app_builder_base` and its serializer in `app_builder_ui`.

### How well web\_timeline stands in for Gantt

It registers `timeline` in all three places a first-class view type must appear — `ir.ui.view.type`, `ir.actions.act_window.view.view_mode`, and `_get_view_info()` — so it participates in the view switcher and in `_offer_view_in_actions` with no special casing. It is interactive rather than a read-only chart: `timeline_renderer.esm.js:188` wires `editable.updateTime` (drag to reschedule), `updateGroup` (drag across rows), `add` and `remove`, gated on `canCreate` / `canDelete`.

Against the nine settings the Gantt documentation describes:

| Gantt setting | web_timeline |
| --- | --- |
| Can Create / Can Edit | ✓ create / edit / delete |
| Start / Stop date field | ✓ date_start / date_stop, plus date_delay |
| Default Group by | ✓ default_group_by — but required, unlike Gantt |
| Default Scale | ~ mode: day / week / month / fit; no year |
| Color | ~ colors is a list of JS expressions, not a field name |
| Display Unavailability | ✗ — and the docs say this cannot be added via Studio anyway |
| Display Total row | ✗ |
| Collapse First Level | ✗ |
| Day / Week / Month Precision | ✗ |
| — | ✓ dependency_arrow, which enterprise Gantt has and Studio does not expose |

Six of nine, plus one Studio cannot do. Three consequences to design for rather than discover:

1.  It is `timeline`, not `gantt` — a different tag, so an arch migrated from an enterprise database is not reusable.
2.  `default_group_by` is mandatory, so the scaffold must always choose one. Same shape as the calendar's mandatory `date_start`, which is already handled by asking rather than guessing (`studio_view_editor.py:832`).
3.  `colors` takes JS expressions (`white: user_ids == []; #ec7063: state == 'cancel'`), so the honest option row is an expression editor with a field-based generator over it — not a field picker pretending to be one.

### base\_tier\_validation as the approval engine

`tier.definition` maps onto Studio's approval rule almost field for field, and the siblings cover what it does not:

| Studio approval rule | OCA |
| --- | --- |
| Approvers | reviewer_id, plus reviewer_field_id for dynamic approvers Studio has no equivalent of |
| Approver Group | reviewer_group_id |
| Condition on the step | definition_domain, or definition_type='formula' with base_tier_validation_formula |
| Approval Order | sequence + approve_sequence |
| Exclusive Approval | exclude_requester, approve_sequence_bypass |
| Users to Notify | notify_on_create / _pending / _accepted / _rejected / _restarted — richer than Studio's single field |
| Delegate | base_tier_validation_forward |
| Run something on approval | base_tier_validation_server_action (server_action_id, rejected_server_action_id, plus domain-driven auto-validation) |
| — | has_comment, notify_reminder_delay, base_tier_validation_correction |

**The attachment mechanism is the part that fits our architecture.** `tier.validation` is an `AbstractModel` mixin a model opts into through `_inherit`, and `set_model_options` already accepts `inherit` (`studio_model_draft.py:449`) — it is how `mail.thread` is added today. So turning on approvals for a studio-built model is one mixin in the generated class, and for a _core_ model it is a generated `class SaleOrder(models.Model): _inherit = ["sale.order", "tier.validation"]`, which is exactly what the marker-block codegen exists to write. Enterprise Studio cannot produce that at all.

**The genuine mismatch**, and therefore the actual work in P7: Studio attaches an approval to a **button** and blocks that button's method. Tier validation attaches to the record and blocks **writes and state transitions** (`_tier_validation_check_state_on_write`, `_check_allow_write_under_validation`). The mixin already injects its review UI at a configurable `_tier_validation_buttons_xpath`, and `base_tier_validation_server_action` covers _after_ approval; a pre-approval gate on a named button or server action is the piece that does not exist.

## Progress

Six phases are in, each tested and committed. What follows describes the rest;
the sections for completed phases are kept because they record *why*, which the
commits alone do not.

| Phase | State |
| --- | --- |
| P0 correctness debt | done — plus five defects the audit had not predicted |
| P2m one catalogue | done — widgets, option rows and field types share one table |
| P1 view editor | done — adds and removes fields, buttons, tabs, groups |
| P2 fields & widgets | done — presets, related fields, computed fields |
| P4 feature packs | done — registry, six new features, two finished |
| P3 view types | done — discovery from `get_view_info`, plus pivot/graph/activity/timeline |
| P5 automations | surface done; code graduation (§X2) designed, not built |
| P6 PDF reports | after P5 |
| P7 approval rules | last |

Two things the work changed about the plan itself:

- **Raw ids turned out to be recoverable.** `fields.Reference` needed nothing at
  all (core's importer resolves a plain `ref=`), and `many2one_reference`
  declares a companion field naming its model, so the record can be found and
  emitted as an xmlid. What still raises is the case with nothing to resolve
  through. The composer still cannot *build* one, which is a different and much
  smaller limit than the one recorded here originally.
- **Tags and Lines need a second model.** They are listed under P4 as features,
  and both need a companion model — a tag model with its own access rule, a line
  model with a many2one back — where the app builder makes one. That is a
  capability rather than another registry entry, and it is the honest reason
  they are not done.

## Sequencing

```
P0 correctness debt ─┬─→ P1 view editor ─┬─→ P3 view types & settings
                     │                    └─→ P6 PDF reports
P2m catalogue ───────┴─→ P2 fields & widgets
                     └─→ P5 automations & webhooks

P4 feature packs, P7 approval rules — independent
```

P0 and P2m are machinery. Nothing downstream is safe or coherent without them, and both are small. P1 is the highest-value phase and the one P6 reuses wholesale. P4 and P7 have no dependencies and can run beside anything.

A single ordering to work down: **P0 → P2m → P1 → P2 → P4 → P5 → P3 → P6 → P7**, with X2 pulled forward into P5 and X3 slotted in once P5 lands and there are three surfaces to unify.

* * *

## P0 — Correctness debt

_Blocks every phase that serializes a new record type. Small._

`_serialize` iterates `self._studio_fields` and nothing else (`studio_serializer.py:248`). The allowlist is deliberate — it is what keeps the output minimal and reviewable — but there is no check that what it omits was actually omittable. A field left off the list with a non-default value is dropped from the generated source silently, and the package still reports clean.

This is not hypothetical. `ir.actions.server` is missing every field that `mail` and `sms` contribute plus the webhook pair, so today an automation that sends an email, creates an activity, adds followers or posts a webhook serializes with its `state` and none of its configuration. The I3 round trip is already broken for those, and every phase below adds more records to serialize.

**The guard comes first**, because it is what makes the rest of the plan safe. In `_serialize`, walk the fields _not_ in `_studio_fields`; if any differs from its evaluated default and is not in a declared `_studio_ignored` set (magic columns, non-stored computes, technical plumbing), raise. Note _evaluated_ — Odoo wraps every scalar default in a lambda (`fields.py:511`), which is the trap already documented in DESIGN.md §2 of "As built". Then a suite-wide test parameterised over every serializer against a fully-populated fixture, so a future omission is a failing test rather than a quiet data loss.

Then the known gaps:

-   **`ir.actions.server`**: `webhook_url`, `webhook_field_ids`, `evaluation_type`, `selection_value`, `resource_ref`, `value_field_to_show`, `update_related_model_id`, `usage`, `path`.
-   **`base.automation`**: `description` (the Notes tab the docs recommend using) and `trg_date_calendar_id`.
-   **Optional-dependency fields.** `mail` and `sms` add `template_id`, `mail_post_method`, `mail_post_autofollow`, `partner_ids`, `activity_*`, `sms_template_id` and `sms_method`. Follow the precedent already set by `base_automation_serializer.py` living in `app_builder_ui` rather than the engine: a new `app_builder_mail` addon, `auto_install` on `mail` + `app_builder_ui`, extending `_studio_fields` through `_inherit`. The engine must not acquire a hard dependency on `mail`.
-   **Reference-field portability.** `resource_ref` is a `fields.Reference` — a raw `model,id` pair, which is the same non-portability that made `many2one_reference` a refused type (`modelspec.py:206`). It needs the treatment relations already get: emit the model plus a `ref="xmlid"`, and refuse when the target has no xmlid. The helper is reused by _Update Record_ actions in P5, so build it here.

**Done when** every community `ir.actions.server` state round-trips byte-identically, and omitting a significant field is a test failure.

* * *

## P2m — One catalogue, server-declared

_Machinery. Blocks P1.7, P2 and P3. Small to medium._

Field types are declared in Python (`modelspec.py:159`); widgets and view options are declared in JavaScript (`options.js:31`). Today those are two small tables. After P1–P3 they are two large tables describing the same product, and they will drift — the composer will offer a widget the view editor cannot set, or the view editor will offer one the composer does not know produces a valid field. The comment at the top of `options.js` already names the field-type catalogue as its model; this makes that literal.

-   Move the widget and option catalogue server-side, beside `FIELD_TYPES`, as one declarative table keyed by `(ttype, widget)` carrying its label, its option rows, and whether each row writes a bare attribute or an `options` JSON key.
-   One `studio.catalogue` endpoint serves both clients. `viewOptions` stays in JS but is demoted to a **renderer registry**: it maps a row `type` to a component and does nothing else.
-   Add a row kind that merges into the `options="{...}"` JSON attribute rather than setting a bare attribute. Roughly fifteen documented widgets need it — image `size`, statusbar `clickable`, many2one `no_create` / `no_open` / `search_threshold`, and the whole Date & Time property block. Building it once here is the difference between P2 being table entries and P2 being fifteen special cases.
-   Add row kinds for the three core components community already ships, all verified present in 18.0: a groups multi-select emitting `groups="module.xmlid"`, a field picker over `web/core/model_field_selector`, and a condition builder over `web/core/domain_selector` and `web/core/tree_editor`.

**Done when** adding a widget is one Python tuple and adding an option row is one dict — no new component per feature.

* * *

## P1 — The view editor becomes a view editor

_The highest-value phase. Large. P6 reuses all of it._

The server side is largely built. `_op_add_field`, `_op_remove_node`, `_op_add_button` and `_op_add_group` all exist; the client issues only `set_attributes` and `move_node`. This phase is mostly client work against an API that is already there, plus one piece of server work that everything else depends on.

**1.1 Descriptor coverage — first.** Every newly selectable thing needs support in `DESCRIPTOR_TAGS` (`studio_view_editor.py:588`), `_find_descriptor` and `_locator_for`: `group`, `page`, `notebook`, `sheet`, `header`, `button_box`, `chatter`, and in P6 qweb nodes. Extend once, with tests, rather than a case per feature. The invariant to hold throughout: locators are minted **server-side against the combined arch**, never in the browser. The arch a client receives is a per-user projection with nodes removed by group rights and subviews grafted in, so a path derived from it can be wrong for somebody else. This is the thing Odoo Studio gets wrong and it must not erode as the surface grows.

**1.2 Add an existing field.** A palette fed by `get_addable_fields` (already written) plus a drop handler. The client reports _"dropped relative to this descriptor"_ and the server resolves the xpath — same division of labour as selection and `move_node`, for the same reason. Because the output is an inheriting view, this works on core views, which is the product thesis finally reachable from the UI.

**1.3 Remove from view.** Wire `remove_node` with a confirmation. Keep it visibly distinct from `invisible`, which already exists and is usually the better answer.

**1.4 New field from inside the view editor.** Two paths, because the asymmetry is real and documented (`readme/ROADMAP.md`, "Known limits"):

-   A model this package owns in Python — stage into `studio.model.draft`, surface the pending tray and Apply banner _in the view editor_, place on apply.
-   Anything else — create a manual `x_` field, live immediately, placed at once.

One gesture and one component, with the tray appearing only in the first case. Hiding the difference would produce a form that silently does not show the field the user just added; a tray saying "one reload pending" is the honest version, and it is the same bargain the composer already makes.

**1.5 Buttons.** Wire `_op_add_button`, and add an option group matching `kind === "button"` — label, `btn-primary` / `btn-secondary`, and an action picker over `ir.actions.server` or a method name. Today a button is selectable (`DESCRIPTOR_TAGS` includes it) but no option group matches, so clicking one opens an empty panel: a dead end that reads as a bug. Smart buttons follow as a `button_box`\-aware variant with a related-field count.

**1.6 Tabs and groups.** Wire `_op_add_group`; add `add_page` and `add_notebook`. Notebook pages currently appear only as a side effect of placing an x2many, html or text field (`placement.py:72`).

**1.7 Cheap option rows**, all pure catalogue entries once P2m lands: `duplicate` on form and list roots, `edit` on the list root, `create` on the kanban root, `default_group_by` on the list root, `width` on a list column, `class` on any node.

**1.8 Groups visibility.** _Allow_ and _Forbid visibility to groups_ map to the `groups` attribute, which is already xmlid-based and therefore serializes correctly with no new machinery.

**1.9 Conditional invisible / required / readonly.** In 18.0 these attributes take a **Python expression**, not a domain — `attrs` was removed in 17.0. So the editor must emit an expression. Build it on core's `DomainSelector`, translating the condition tree to an expression, with a raw-expression escape hatch and server-side validation before write. Verify the round trip (expression → tree → expression) is stable before shipping; where it is not for some operator, fall back to raw-with-validation for that case rather than silently rewriting what the user typed.

* * *

## P2 — Field types and widgets

_Medium. Mostly catalogue entries once P2m lands._

`FIELD_TYPES` covers every ORM type Odoo has, with four refused for stated reasons — that part is done, and the refusals are better than Odoo's silence. What is missing is the layer above: Odoo's picker has 21 entries because it ships type-and-widget presets, and we ship none of them.

-   **The missing widgets** (~20): Copy to Clipboard, Image-from-URL, Enable SMS, Percentage Pie, Progress Bar on floats, Html-as-raw, Checkbox-as-Button, Selection Badges / Radio / **Status Bar**, PDF Viewer, Sign, many2one Badge / Radio plus `no_create`, `no_open` and typeahead threshold, many2many Checkboxes, Tags `color_field`.
-   **Type presets**: Priority (selection with four preset values and the `priority` widget), Image, Sign, Lines, Tags-with-widget — note `many2many` is currently _labelled_ "Tags" but never sets `many2many_tags` — and **Date Range** (`daterange` plus start and end field pickers plus `always_range`). Sign needs no dependency: the `signature` widget is community (`web/static/src/views/fields/signature/`), so the preset is binary plus that widget and nothing more.
-   **Related field.** A new `FieldType("related", …)` using core's `ModelFieldSelector` for the chained path. `FieldSpec.related` and the codegen already handle it; this is purely a picker gap.
-   **Computed field.** Expose `compute` and `depends` in the popover. The engine already promotes a compute string to a real `@api.depends` method, so this is also purely a UI gap — and closing it corrects `app_builder_model/readme/DESCRIPTION.md`, which today claims coverage the composer does not have.
-   **Date & Time properties**: all eleven (minimal and maximal precision, warning for future dates, numeric date format, show date / time / seconds, time interval, earliest and latest accepted date), as one `options` JSON row group.
-   **Monetary.** Offer to create the Currency field rather than disabling _Amount_ until one exists. The current message is good; doing the thing is better.

* * *

## P3 — View types and remaining settings

_Medium._

**3.0 View-type discovery — first.** Replace the hardcoded `ADDABLE_VIEW_TYPES` (`studio_view_editor.py:738`) with a derivation from `ir.ui.view.get_view_info()`, gated on the studio having a scaffold and an option group for the type, listing the rest disabled with a reason. Rationale and consequences are in §"Discover view types, do not hardcode them". Do this before adding any individual type, or each one is another hardcoded entry.

-   **Pivot, Graph and Activity.** Community types, and their absence is a real gap — _Monetary value_ in P4 is documented as activating Graph and Pivot. Scaffolds plus settings-panel option groups. Follow the calendar precedent: settings-only, no clickable DOM, and say so rather than inventing click targets.
-   **Timeline** (`web_timeline`) as the Gantt stand-in, and **Leaflet Map** (`web_view_leaflet_map`) as the Map stand-in. Both are settings-panel views like calendar. Neither becomes a dependency of anything: they appear when installed and are absent otherwise, which is what 3.0 buys. The three design consequences for timeline — mandatory `default_group_by`, expression-based `colors`, and a tag that is not `gantt` — are set out above.
-   **`web_pivot_computed_measure`**, if present, extends what the Pivot option group can offer. Same discovery discipline: detect, do not depend.
-   **Calendar**: all-day field and delay field.
-   **Search**: separators, and a real filter builder over `DomainSelector` replacing the four canned single-field conditions (`studio_view_editor.py:452`). The roadmap already names this.
-   **Set as Default view**, through `ir.actions.act_window.view` sequence — the serializer exists.
-   **XML source editing** inside the editor: an ace editor over the _extension_ view's arch, validated by Odoo's own validator before write. This is better than Odoo's equivalent by construction — you are editing the patch, not the base — and it is the escape hatch that makes every "not supported by the builder" answer acceptable.

* * *

## P4 — Feature packs

_Medium. No dependencies._

Reframe `ScaffoldOptions` (`scaffold.py:32`) as a **registry of feature packs**, each declaring the fields it adds, the views it activates and the arch fragments it contributes — data, in the same spirit as the option registry. Cross-feature interaction then composes instead of branching, which matters because the docs specify at least one: Picture plus Pipeline stages puts the image on the kanban card.

-   **Missing (7)**: Contact details, Date range, Tags (which creates a Tag model with its own ACL), Picture, Lines, Monetary value, Company. Odoo's _Date range & Gantt_ becomes **Date range & Timeline** and activates the timeline view when `web_timeline` is installed, degrading to date-range fields alone when it is not. _Contact details_ likewise activates Leaflet Map rather than Map.
-   **Finish (3)**: Pipeline stages needs Kanban State, Priority and Color; User assignment needs the `many2one_avatar_user` widget and the share-user domain; Date & Calendar should activate the Calendar view rather than only adding the field.
-   **Expose the four hardcoded options** — `ordering`, `active`, `description`, `activities` — which the wizard currently forces on.
-   **Keep the one we have that Odoo does not**: sequence-backed Reference numbers.

* * *

## P5 — Automations and webhooks as a studio surface

_Medium._

The capability is inherited wholesale from community `base_automation`, so every documented trigger category already works. What is missing is the surface: one wizard that only ever produces `state='code'` (`studio_menu_wizard.py:82`). Everything else has to be built in Settings → Technical and then assigned a package, which is exactly the technical-menu detour the studio exists to remove.

-   **An Automations panel** scoped to the model in view, with trigger-conditional fields (delay, date field, `trigger_field_ids`, `on_change_field_ids`, `filter_pre_domain`) and an action editor covering every community state: Update Record including sequences and many2many add / remove / set / clear, Create and Duplicate Record, Create Activity, Send Email and SMS, Add and Remove Followers, Send Webhook Notification, Multi Actions. Ordered, and reorderable, because order is semantic — the docs make the point that an email before an update sends stale values.
-   **A Webhooks panel**: create `on_webhook` rules, show the URL, rotate the secret, toggle call logging, edit the target-record expression, show a sample payload. `webhook_uuid` stays excluded from source, which is already right (`base_automation_serializer.py:50`).
-   **A sequence editor** for Update Record → Sequence; the `ir.sequence` serializer exists.
-   **§X2** belongs in this phase.

* * *

## P6 — PDF reports

_Extra large — the biggest variance in this plan. Sequenced after P1 because it reuses that machinery unchanged._

A qweb arch is XML, so `apply_operation`, the descriptor and locator layer, and the extension-view mechanism all apply as they stand. That is why this phase follows P1 rather than running beside it.

| Piece | Notes |
| --- | --- |
| Create a report | External / Internal / Blank → ir.actions.report plus a qweb ir.ui.view. Both already serialize; ir_ui_view.py already emits key for qweb |
| Edit an existing report | As an inheriting qweb view. Odoo's own documentation tells the user to duplicate the standard report and mutate the copy, which is why a Studio-customized database fights every upgrade. This is the report chapter's version of the project's central claim |
| The editor | html_editor is present in community 18.0. Powerbox / commands, field insertion (t-field), static tables, dynamic tables (t-foreach), formatting |
| Conditional blocks | Display and preview-switch t-if / t-elif / t-else, read-only — the same limit Odoo has |
| Options | Paper format, show in print menu, reload from attachment, visibility groups, edit sources, print preview. All plain fields, already in _studio_fields |
| Document layout | Company settings, not studio. Deep-link rather than reimplement |

Build the create path, the inheriting-patch path and XML source editing first. That subset is already usable and is the part Odoo cannot match; the WYSIWYG powerbox is the long tail and can land incrementally behind it.

* * *

## P7 — Approval rules

_Medium, on `base_tier_validation`. No dependencies on other phases._

Originally scoped as building an approval engine from nothing. It is not: `base_tier_validation` (server-ux 18.0, Mature) is that engine, its configuration model maps onto Studio's rule almost field for field, and its siblings cover delegation and post-approval actions. The mapping table is in §"base\_tier\_validation as the approval engine".

What this phase actually builds:

1.  **Mixin injection.** Turning approvals on for a model means adding `tier.validation` to `_inherit` — which `set_model_options` already does for `mail.thread`. For a core model it means generating a small class in the package that inherits the model and the mixin together. This is the code-first differentiator: enterprise Studio cannot emit a Python mixin, so its approvals are confined to what its own rule table can express.
2.  **A Studio-shaped configuration surface** over `tier.definition`, scoped to the model in view, so approval steps are configured where the button is rather than in a technical menu.
3.  **The button gate — the genuinely new work.** Studio attaches an approval to a button and blocks that button's method; tier validation blocks writes and state transitions. The mixin already injects its review UI at a configurable `_tier_validation_buttons_xpath`, and `base_tier_validation_server_action` handles _after_ approval. A pre-approval gate on a named button or server action does not exist and has to be written — as an upstreamable OCA module rather than something private to the studio.
4.  **Serialization.** `tier.definition` rows need a serializer and join I3. `tier.review` records are runtime state and must not be captured.

Optional siblings to surface in the UI when installed, on the same detect-do-not-depend discipline as P3.0: `base_tier_validation_formula` (Python conditions), `_forward` (delegation), `_server_action` (run on approve / reject, auto-validate by domain), `_correction`.

It is still last in the ordering, because nothing else in the plan depends on it — but it is no longer the largest phase.

* * *

## Cross-cutting

**X1 — Data-record capture.** The half of "Include Data" that survives the ZIP being irrelevant. A generic serializer for arbitrary models, so a package can carry reference data — stages, tags, categories — that its views and automations refer to. Needs xmlid minting for business records and a domain-scoped selection UI. Everything today is `ir.*` plus `base.automation`, so a package cannot ship the three pipeline stages its own kanban is grouped by.

**X2 — Code graduation.** `ir.actions.server.code` is a sandboxed string in Odoo, permanently. We already promote a compute string to a real `@api.depends` method when a model graduates to Python; do the same for automation code — a real method in the package, reviewable, testable, breakpoint-able, with the server action calling it. The machinery exists, so this is cheap, and it is the clearest instance in the plan of the thing the whole project claims.

**X3 — A studio shell.** The way in today is the Studio root menu plus a cog item. Once reports, automations, webhooks and approvals exist, they need one surface scoped to _the model in view_ — otherwise they are discoverable only by people who already read the technical menu. Not a feature; the thing that makes the features findable. Worth doing after P5, when there are three surfaces to unify and the shape is obvious.

**X4 — Rename with migration.** Odoo's answer to renaming a field is to remove it from every view, edit it in Settings → Technical, and add it back everywhere. We already generate pre-migrations for dropped columns (`tools/migrationgen.py`); extending that to renames deletes the whole dance.

**X5 — Invariant maintenance.** Every phase extends the three invariants rather than working around them: newly serializable models join I3, new field types and attribute combinations join I1's fixed-point matrix, new reflection surfaces join I2. State this as a definition of done per phase — the P0 guard catches serializer omissions only, not codegen ones.

* * *

## Rough shape

Relative sizes, not calendar estimates.

| Phase | Size | Blocks |
| --- | --- | --- |
| P0 correctness debt | S | everything serializer-adjacent |
| P2m catalogue | S–M | P1.7, P2, P3 |
| P1 view editor | L | P6 |
| P2 fields & widgets | M | — |
| P3 view types | M | — |
| P4 feature packs | M | — |
| P5 automations | M | — |
| P6 PDF reports | XL | — |
| P7 approval rules | M | — |
| X1, X2, X4, X5 | S each | — |
| X3 studio shell | M | after P5 |
