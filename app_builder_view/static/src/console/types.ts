/** @odoo-module **/
/**
 * The shapes the canvas payload and node table carry, shared by every
 * console module that reads them. Not just the canvas: `PaneContext`
 * needs `PackageEntryJSON` for its own `package` field, hence the one
 * import from `wire.ts` below -- the two files' concerns overlap exactly
 * there and nowhere else.
 *
 * Transcribed from the server's own construction of a node
 * (`app_builder_view/tools/canvas_stamp.py:stamp`, `KIND_BY_TAG`,
 * `_orientation`, `label_of`), not guessed from how the client happens to
 * use them -- this is the contract, and the client is one of its readers.
 * A field the console does not yet read (`field`, `view_id`) is typed no
 * more precisely than the server's own dict guarantees, rather than
 * invented; it is narrowed when the code that actually consumes it is
 * converted (see TYPING.md, Phase 2b).
 *
 * This will eventually be generated from the annotated Python
 * (`wire.py` + a `TypedDict` for the node, per TYPING.md Phase 1c/2d)
 * rather than hand-kept in sync with `canvas_stamp.py`; until that
 * generator exists, a change to the node shape there must be mirrored
 * here by hand.
 */

import type {Component} from "@odoo/owl";
import type {Translated} from "./l10n";
import type {
  DraftFieldJSON,
  DraftPayload,
  FieldTypeEntry,
  InverseOptions,
  PackageEntryJSON,
  ResolveRelatedResult,
} from "./wire";

/** A node's role in the arch. One tag can be several kinds (`div` is
 * `label`, `button_box` or `html`); `_kind()` is the single source. */
export type NodeKind =
  | "root"
  | "html"
  | "button_box"
  | "label"
  | "column"
  | "field"
  | "button"
  | "page"
  | "group"
  | "notebook"
  | "sheet"
  | "header"
  | "footer"
  | "separator"
  | "widget"
  | "chatter"
  | "main"
  | "aside"
  | "card"
  // Emitted only for a field staged on a draft, spliced into the canvas
  // under a `p_<name>` token (`builder_view_canvas.py`); not one of
  // `canvas_stamp.py`'s own kinds.
  | "pending";

/** How a container lays its children out (`_orientation`; never `null`). */
export type Orientation = "row" | "column";

/** Why a node is hidden from a plain user, when it is. */
export type HiddenReason = "groups" | "invisible" | null;

/**
 * Where a field's `<label>` comes from, or that it has none (`label_of`
 * in full -- a dict, not the bare `"group"`/`"label"` string its `by` key
 * holds, a first-pass misreading corrected once `outline_tree.ts` needed
 * `.token`). Only ever set on a `field` node's own entry, and only when
 * the view is a form (`canvas_stamp.py:stamp`, the `root_tag == "form"`
 * branch) -- every other node's `label` is `null`.
 */
export interface FieldLabel {
  /** Whether the compiler draws a label for this field at all. */
  shown: boolean;
  by: "group" | "label" | null;
  /** The token of the `<label for>` naming this field, when `by` is
   * `"label"`. */
  token: Token | null;
  in_group: boolean;
}

/** A token naming one node of the arch (`o_builder_n_<ordinal>`), or the
 * ghost of a staged field (`p_<name>`). Opaque on the client: never parsed,
 * only compared and looked up in a `NodeTable`. */
export type Token = string;

/** One entry of the canvas's node table (`canvas_stamp.py:stamp`). */
export interface BuilderNode {
  tag: string;
  name: string | null;
  kind: NodeKind;
  parent: Token | null;
  children: Token[];
  index: number;
  string: string | null;
  container: boolean;
  orientation: Orientation;
  /** Child kinds/tags this node's `ACCEPTS` entry allows a drop of. */
  accepts: readonly string[];
  movable: boolean;
  removable: boolean;
  selectable: boolean;
  hidden: HiddenReason;
  attrs: Readonly<Record<string, string>>;
  /** Whether this node renders an element at all (a page's tab does; a
   * hidden-and-not-shown node does not). */
  dom: boolean;
  /** Field metadata for a `field`/`column` node. */
  field: CanvasFieldInfo | null;
  view_id: number | null;
  label: FieldLabel | null;
  /** Present only on a `kind: "pending"` ghost -- a field staged on a
   * draft, not yet applied (`builder_view_canvas.py`'s `_stamp_pending`
   * construction, the block after `"label": None,`). `BuilderNode` stays
   * one flat shape rather than a `kind`-discriminated union for now;
   * this is the one field that is genuinely conditional on `kind`. */
  pending?: PendingFieldInfo;
}

/** The canvas's node table: every node of the arch, by token. */
export type NodeTable = Readonly<Record<Token, BuilderNode>>;

/** Where a field came from: a real column (`ir.model.fields` with
 * `state="base"`, from Python) or one the builder itself created
 * (`state="manual"`). Decides whether the definition panel shows facts or
 * lets the user edit them (`_field_origin`). */
export type FieldOrigin = "core" | "manual";

/** A field on some model, no more than a picker needs
 * (`builder_view_editor.py:_model_fields`, `app_builder_base/tools/catalogue.py`'s
 * own `field_types` rows read the same three keys). */
export interface BuilderModelFieldEntry {
  name: string;
  string: string;
  type: string;
}

/**
 * `builder.view.editor._field_info`, plus where the field came from
 * (`_canvas_field_info`). `comodel_fields` is present only when explicitly
 * asked for (`describe_node`'s `comodel_fields=True`) -- the plain canvas
 * payload leaves it out to avoid shipping a relation's whole comodel field
 * list on every node of every drop; see `_canvas_field_info`'s own
 * docstring.
 */
export interface CanvasFieldInfo {
  name: string;
  type: string;
  string: string;
  store: boolean;
  required: boolean;
  readonly: boolean;
  origin: FieldOrigin;
  comodel_fields?: BuilderModelFieldEntry[];
}

/**
 * A field staged on a `builder.model.draft`, not yet applied: what
 * `BuilderNode.pending` carries on the ghost node the canvas splices in
 * for it (`builder_view_canvas.py`, the `_stamp_pending`-style
 * construction under `"kind": "pending"`).
 */
export interface PendingFieldInfo {
  draft_id: number;
  name: string;
  /** The field's Odoo type (`ir.model.fields.ttype`) -- named `ttype`,
   * not `type`, on this one shape, matching the Python dict key. */
  ttype: string;
  string: string;
  resolved: boolean;
}

/** One value of a manual selection field (`_field_definition`). */
export interface SelectionOption {
  value: string;
  label: string;
  sequence: number;
}

/**
 * The model-level facts of a field and which of them the definition panel
 * may write (`builder_view_canvas.py:_field_definition`). `editable` names
 * only the keys of `values` a manual field's ``ir.model.fields`` row
 * actually accepts; a core field's `editable` is always empty.
 */
export interface FieldDefinition {
  origin: FieldOrigin;
  editable: readonly string[];
  values: {
    field_description: string;
    help: string;
    required: boolean;
    readonly: boolean;
    index: boolean;
    translate: boolean;
    ttype: string;
    relation: string | false;
    selection?: SelectionOption[];
  };
}

/**
 * What the properties sidebar edits: the node table's own `kind`/`name`
 * (which the option catalogue matches on) merged with `describe_node`'s
 * answer for the same token -- what it currently carries and what its
 * field is (`console_model.js:describe`). `field` falls back to the node
 * table's own `field` when `describe_node` found none of its own, which
 * is why it is typed the same `CanvasFieldInfo | null` either way.
 */
/** `describe_node`'s own raw RPC answer (`builder_view_canvas.py:
 * describe_node`) -- before `describe()` merges in the node table's own
 * `kind`/`name`/`token` to build a `DescribedTarget`. */
export type DescribeNodeAnswer =
  | {found: false}
  | {
      found: true;
      tag: string;
      attrs: Readonly<Record<string, string>>;
      field: CanvasFieldInfo | null;
      definition: FieldDefinition | null;
    };

export interface DescribedTarget {
  kind: NodeKind;
  name: string | null;
  token: Token;
  found: boolean;
  tag?: string;
  attrs?: Readonly<Record<string, string>>;
  field: CanvasFieldInfo | null;
  definition?: FieldDefinition | null;
}

// -- drop zones -------------------------------------------------------------
//
// Shared by `zones.js` (the canvas's own zones, `layer: "canvas"`) and
// `outline_zones.js` (the outline tree's, `layer: "outline"`, with a
// `line` a canvas zone never carries) -- one drop, two renderings; see
// `outline_zones.js`'s own module docstring.

/** What a drop means, relative to the node it names. */
export type ZonePosition = "before" | "after" | "inside";

/** Which end of a span a zone sits at, when it sits at one. */
export type ZoneEdge = "start" | "end" | null;

/** Which screen axis a zone's bar runs along. */
export type ZoneAxis = "x" | "y";

export type ZoneLayer = "canvas" | "outline";

/** One place a drag can land, as a rectangle plus what dropping there
 * would mean (`zones.js:buildZones`, `outline_zones.js:outlineZones`). */
export interface Zone {
  layer: ZoneLayer;
  token: Token;
  position: ZonePosition;
  kind: NodeKind;
  name: string;
  container: Token;
  containerKind: NodeKind;
  containerLabel: string;
  depth: number;
  axis: ZoneAxis;
  edge: ZoneEdge;
  rect: PlainRect;
  caption: string;
  /** The outline's own boundary line (viewport y), or `null` for a box
   * zone; absent entirely on a canvas zone, which draws no line. */
  line?: number | null;
}

/** A container a zone can be dropped into, empty or not
 * (`zones.js:buildZones`'s second return value). */
export interface ZoneContainer {
  token: Token;
  rect: PlainRect;
}

/** What a drag is carrying, named by `payloadTag` (`zones.js`) to decide
 * which containers accept it. `component`/`token` are read only for the
 * matching `kind`; other kind-specific fields (a new field's proposed
 * name, a pending edit's staged values...) are the dragging code's own
 * business and pass through untyped here. */
export interface DragPayload {
  kind: "existing_field" | "new_field" | "move_pending" | "component" | "move";
  /** For `kind: "component"`: the palette's name for it
   * (`zones.js:COMPONENT_TAGS`). `| undefined`, not just optional: a
   * component tile's `payloadFor` (`drag.ts`) builds this from
   * `el.dataset["key"] || el.dataset["name"]`, which is legitimately
   * `undefined` when a tile's markup sets neither -- an explicit
   * `component: undefined` on the built payload, which
   * `exactOptionalPropertyTypes` treats differently from the key being
   * absent altogether. */
  component?: string | undefined;
  /** For `kind: "move"`: the node being moved. */
  token?: Token;
  /** What a drag's own chip and status pill show while it is in the
   * air (`zones.ts:labelOf`, or a tile's own `dataset.label`/text) --
   * always set by `drag.ts:payloadFor`, the one builder that constructs
   * a payload for an actual drag. Optional, not required: the other
   * `DragPayload` construction sites (`console_model.ts`'s own
   * `addNewField`/`addButton`, the click-to-add path with no chip to
   * label) never set it. */
  label?: string;
  [key: string]: unknown;
}

/** A viewport or content-relative rectangle, as every geometry helper
 * here returns it -- never a live `DOMRect`, so it survives past the
 * layout that produced it. */
export interface PlainRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

/** A viewport point, e.g. from a pointer event. */
export interface Point {
  x: number;
  y: number;
}

/** A `PlainRect` with the two derived edges some callers want (`compat.rowRect`,
 * a plain `DOMRect` satisfies this structurally, so no conversion is needed
 * at that boundary). */
export interface BoxRect extends PlainRect {
  bottom: number;
  right: number;
}

// -- the outline --------------------------------------------------------

/** One row of the outline tree, as `outline_tree.ts:flatten` lays it out. */
export interface OutlineRow {
  token: Token;
  node: BuilderNode;
  depth: number;
  /** `pathKey`'s answer for this row -- survives a re-stamp, unlike
   * `token`. */
  key: string;
  hasChildren: boolean;
  expanded: boolean;
  label: string;
  /** A Font Awesome class string (`KIND_ICONS`/`TYPE_ICONS`). */
  icon: string;
  badges: {
    hidden: HiddenReason;
    pending: boolean;
    required: boolean;
  };
  /** Whether the row cannot be dragged (`!node.movable`). */
  fixed: boolean;
}

/** One row as `outline_zones.ts:outlineZones` is handed it: just enough
 * to lay bars out over, not a full `OutlineRow` (no `label`/`icon`/etc). */
export interface OutlineZoneRow {
  token: Token;
  depth: number;
  /** In viewport coordinates. */
  rect: PlainRect;
  /** Passed through by some callers; this module's own layout never
   * reads it (a caller has already left a collapsed row's children out
   * of `rows` by the time it gets here). */
  collapsed?: boolean;
}

// -- the canvas payload ---------------------------------------------------
//
// `app_builder_view/models/builder_view_canvas.py`,
// `app_builder_view/models/builder_view_editor.py`,
// `app_builder_view/models/builder_view_new_field.py` -- the Views pane's
// own RPC surface (`console_model.ts`). Kept here rather than in
// `wire.ts` since every one of these carries a `Token` or a `NodeTable`,
// this module's own concern per the docstring above; `wire.ts` has the
// rest of this RPC surface (`EditingContext`, `OperationResult`, ...),
// which does not.

/** One row of `canvas()`'s `history` (`builder_view_edit.py:_entry`). */
export interface HistoryEntry {
  id: number;
  summary: string;
  author: string;
}

/** `canvas()`'s `package` -- who a drop here would record into
 * (`builder_view_canvas.py:_canvas_package`), a narrower vocabulary than
 * `PackageEntryJSON` (`builder.workspace`'s own, unrelated `package`). */
export interface CanvasPackageSummary {
  id: number;
  name: string;
  writable: boolean;
}

/** A field staged on the draft this canvas shows, drawn as a ghost or not
 * (`builder_view_canvas.py:_splice_pending`, `_pending_anchored`'s own
 * `{name, label, ttype, widget, anchor}` plus what splicing adds). Not
 * `BuilderNode.pending` (`PendingFieldInfo`, the ghost *node's* own entry
 * in the node table) -- this is the tray's flat list, one per staged
 * field whether or not it has a place to draw. */
export interface CanvasPendingEntry {
  name: string;
  label: string;
  ttype: string;
  widget: string;
  /** `p_<name>` -- the ghost's own token, whether or not it was placed. */
  token: Token;
  /** Whether a ghost was actually spliced into `nodes` under `token`. */
  placed: boolean;
  /** Whether the anchor resolved to a real neighbour, as opposed to the
   * balanced fallback spot. */
  resolved: boolean;
  view_id: number | false;
}

/**
 * `canvas()`'s whole return (`builder_view_canvas.py:canvas`) -- everything
 * the console needs to render one view and address it. `models`/`source`
 * are left `unknown`: nothing converted so far reads either (the field
 * descriptions of inline subviews, and "what the builder wrote" for a View
 * tab neither pane model owns); narrow when a real reader appears.
 */
export interface CanvasPayload {
  view: {
    id: number;
    name: string;
    type: string;
    model: string | false;
    mode: string;
    js_class: string | null;
  };
  arch: string | null;
  models: unknown;
  arch_version: string;
  res_id: number | false;
  root: Token | null;
  nodes: NodeTable;
  pending: CanvasPendingEntry[];
  draft_id: number | false;
  editable_as: "canvas" | "report" | "search_lists";
  source: unknown;
  history: {undo: HistoryEntry[]; redo: HistoryEntry[]};
  package: CanvasPackageSummary | null;
  record_count: number;
}

/** What a live-created field's `created` names, on a `drop_at` answer
 * (`builder_view_new_field.py:_drop_live_field`). */
export interface DropCreatedField {
  name: string;
  label: string;
  live: true;
}

/** What a staged field's `staged` names, on a `drop_at` answer
 * (`builder_view_new_field.py:_drop_field_definition`). */
export interface DropStagedField {
  name: string;
  label: string;
  draft_id: number;
}

/**
 * `drop_at`'s settled answer -- what a caller of `ConsoleModel`'s own
 * mutators actually receives (`builder_view_editor.py:drop_at`,
 * `builder_view_new_field.py:_drop_live_field`/`_drop_field_definition`,
 * the three return sites that are not the stale one). `_mutate` peels the
 * stale answer (`{stale: true, canvas}`, no other key) off internally and
 * resolves to `undefined` instead of handing it on, so nothing that
 * reaches a caller of `dropAt`/`drop` needs to carry `stale: true` --
 * seeing it here would be typing ahead of what any reader actually gets.
 */
export interface DropSuccessResult {
  stale: false;
  select: Token | null;
  created: DropCreatedField | null;
  staged: DropStagedField | null;
  canvas: CanvasPayload;
  history: CanvasPayload["history"];
  draft: DraftPayload | null;
}

// -- errors ---------------------------------------------------------------

/**
 * What an Odoo RPC error carries that the console reads, across every
 * file that catches one: `data.name` (`compat.ts:isStaleError`, the
 * exception's Python class name), `data.context.confirm_required`
 * (`compat.ts:isConfirmError`), and `data.message`/`message`
 * (`shell/draft_model.ts:messageOf`, the sentence to show). Real errors
 * carry plenty else (a traceback, an arguments list); this names only
 * what the console itself ever reads off one.
 */
export interface OdooRpcError {
  message?: string;
  data?: {
    name?: string;
    message?: string;
    context?: {confirm_required?: boolean};
  };
}

// -- panes ------------------------------------------------------------------
//
// Traced against `shell/pane_registry.ts`'s real implementation
// (`resolvePane`/`paneAvailable`/`paneTabs`/`paneFlows`), reconciled
// against the earlier guess this section held (transcribed only from the
// module's own docstring and from `shell_model.ts`'s reads, before
// `pane_registry.ts` itself existed). Two real differences turned up:
//
//   - `sequence` was never a field of the *stored* entry -- despite the
//     module docstring listing it beside `label`/`icon` as if it were
//     one, every real `paneRegistry.add(key, value, options)` call
//     (`views_pane.js`, `changes_pane.js`, `home_pane.js`, the
//     addon-owned `console_items.js` files) passes it as `add()`'s own
//     third-argument *option* (`{ sequence: 10 }`), never inside the
//     registered value -- the docstring's own parenthetical ("sequence
//     (add() option)") already said so. `resolvePane`'s `paneRegistry.get()`
//     read never carries it, and nothing in this tree has ever read
//     `entry.sequence`. Dropped from both interfaces below.
//   - `Component`/`sidebar`/`makeModel`/`surface`/`flow` are read
//     directly by dot access inside `pane_registry.ts` itself
//     (`resolvePane`'s three-way branch), which `noPropertyAccessFromIndexSignature`
//     does not allow against a bare index signature -- named explicitly
//     below instead of left for the index signature to cover, the same
//     kind of extra field a from-the-outside guess misses. `sidebar`/
//     `makeModel` both need `| null`, not just optionality: no real
//     registration ever writes a literal `sidebar`/`makeModel: null`
//     itself (`home_pane.js`'s own `sidebar: null` is the one exception
//     -- see `sidebar`'s own comment below), but `resolvePane`'s
//     Component-branch default (`entry.makeModel ?? null`) genuinely
//     produces a `null` value on the *resolved* entry when a
//     Component-bearing registration supplies neither -- a real,
//     reachable state the function itself handles -- `shell_model.ts`'s
//     `paneModel()` already defends against exactly `!entry.makeModel`
//     being true. One shared type carries `| null` on both `PaneRegistration`
//     and `PaneEntry` rather than narrowing it away on the stored side:
//     `PaneEntry extends PaneRegistration`, and TypeScript's interface
//     extension requires an overriding property to be *narrower* than
//     what it overrides, not wider, so a `PaneEntry`-only `| null` would
//     not compile against a non-nullable `PaneRegistration.makeModel`.
//     `surfaceArgs`/`rowActions`/`empty`/`newFlow` stay under the index
//     signature -- `pane_registry.ts` never reads them (only
//     `record_pane_model.ts`/`record_pane.js` do), so they remain
//     unmodeled until one of those is converted.

/** What a pane needs in hand to decide it can be shown
 * (`pane_registry.ts:paneAvailable`, `shell_model.ts:paneContext`). */
export interface PaneContext {
  packageId: number | false;
  package: PackageEntryJSON | null;
  modelName: string;
  view: {view_id: number | false; view_type: string | false; res_id: number | false};
  pane: string;
  inventory: unknown;
  pythonOwned: boolean;
}

/**
 * What a module hands `paneRegistry.add(key, value, options)` -- the
 * *stored* shape, before `resolvePane` merges in `key`. Also the item
 * shape `app_builder.panes` itself is declared with (`pane_registry.ts`'s
 * own `declare module "registries"` augmentation), since nothing else in
 * this tree names that category yet.
 */
export interface PaneRegistration {
  /** Built at module load by every real registration, so a lazy `_t`
   * value (`Translated`, `l10n.ts`) and never a primitive `string`:
   * translations are not loaded yet when a module body runs, and
   * `String()` on a lazy value at that moment throws `translation error`
   * out of `odoo.define`, aborting the rest of the asset bundle -- the
   * whole backend, not just this pane. Stringify where it is read. */
  label: Translated;
  icon?: string;
  scope?: "package" | "model" | "view";
  isAvailable?: (ctx: PaneContext) => boolean;
  /** `false` for a pane the top bar does not list (a flow). */
  tab?: false;
  /** A custom pane's own component (`ViewsPane`, `HomePane`,
   * `ChangesPane`, ...) -- the first of `resolvePane`'s three
   * discriminators. Only ever checked for truthiness and passed
   * through untouched by `pane_registry.ts`; never instantiated or
   * read for its `Props` there, so this names the class and nothing
   * more. */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Component?: typeof Component<any, any>;
  /** The custom pane's sidebar, or `null` for none (`home_pane.js`
   * sets this explicitly; every other `Component`-bearing entry
   * supplies a real one). */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sidebar?: typeof Component<any, any> | null;
  /** `(shell) => new SomeModel(...)` at every real registration that
   * has one (`record_pane.js`, `views_pane.js`, `home_pane.js`,
   * `changes_pane.js`, `flow.js` -- never a literal `null` on this
   * side); `resolvePane`'s own Component-branch default can still
   * produce `null` on the *resolved* `PaneEntry` when an entry
   * supplies none, which is why `null` is part of this shared type at
   * all (see this section's own header comment). */
  makeModel?: ((shell: unknown) => PaneModel) | null;
  /** A record pane's surface name -- the second discriminator.
   * `surfaceArgs`/`rowActions`/`empty`/`newFlow`, the rest of "a
   * record pane"'s own vocabulary, are read by
   * `record_pane_model.ts`/`record_pane.js`, never by
   * `pane_registry.ts`, so they stay under the index signature below. */
  surface?: string;
  /** A flow pane's spec -- the third discriminator. Only ever checked
   * for truthiness in `pane_registry.ts`; `console/flows/flow.ts`'s own
   * `FlowModel` is the real reader of it -- modeled now that this
   * conversion has happened, per this comment's own earlier promise. */
  flow?: FlowSpec;
  [key: string]: unknown;
}

/**
 * A registered pane, resolved (`pane_registry.ts:resolvePane`): the
 * stored `PaneRegistration` with its `key` merged in, and -- for a
 * `surface`/`flow` entry -- the record/flow resolver's own additions
 * folded on top. `shell_model.ts` only ever reads `key`/`scope`/`label`/
 * `makeModel`/`isAvailable`/`tab` off the result, never picks a variant
 * apart itself, so the rest stays under the index signature rather than
 * modeled ahead of a real reader (Owl components and flow steps belong
 * to files this migration has not reached yet).
 */
export interface PaneEntry extends PaneRegistration {
  key: string;
}

// -- flows ----------------------------------------------------------------
//
// `console/flows/flow.ts`'s own vocabulary (`FlowModel`, `Flow`), named
// here rather than there so `PaneRegistration.flow` (above) can reference
// it without `types.ts` importing from `flow.ts` -- the same reverse-
// import problem `CanvasPayload`/`Token` hit in cluster 2, solved the
// same way (the shared shape lives at the lower layer). `shell`/`flow`
// stay `unknown` in every function signature here for the identical
// reason `PaneRegistration.makeModel` already does: this module does not
// import the concrete shell class (`shell/shell_model.ts`) or `FlowModel`
// itself, to stay a leaf the rest of `console/` can depend on without a
// cycle. `flow.ts`'s own `FlowModel` narrows `shell` back to the real
// `BuilderShell` on its own fields; nothing here needs to.

/** One value a flow's steps read and write, keyed by name. A plain bag
 * rather than a per-flow union: `create_package_flow.ts` keys it
 * `name`/`root_dir`/`git_init`, `build_app_flow.ts` keys it
 * `model_name`/`features`/`groups`, `adopt_model_flow.ts` keys it
 * `models`/`previews` -- nothing here could name a shape common to
 * every real flow without widening it to little more than this. */
export type FlowValues = Record<string, unknown>;

/** One step of a flow, as `flow.ts:FlowModel` reads it off `spec.steps`. */
export interface FlowStep {
  key: string;
  /** A lazy `_t` value, built at module load -- see
   * `PaneRegistration.label`. */
  label: Translated;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Component: typeof Component<any, any>;
  validate?(values: FlowValues, shell: unknown): string;
  onEnter?(values: FlowValues, shell: unknown, flow: unknown): void | Promise<void>;
}

/**
 * A flow's own spec -- what `paneRegistry.add(key, { flow: {...} })`
 * carries under `flow` (`flow.ts`'s own module docstring, and every real
 * registration). `PaneRegistration.flow` was typed no more precisely
 * than `unknown` until this shape existed for real (that field's own
 * comment said so); it is `FlowSpec` now.
 */
export interface FlowSpec {
  /** Set by every real registration, matching the registry's own key;
   * read only by the template (`flow.xml`'s `t-att-data-flow`), never
   * by `FlowModel` itself. */
  key?: string;
  /** Lazy `_t` values, like every flow's step labels. */
  title: Translated;
  doneLabel?: Translated;
  initial?: FlowValues;
  steps: FlowStep[];
  onOpen?(shell: unknown, flow: unknown): void | Promise<void>;
  onDone(shell: unknown, flow: unknown): Promise<unknown>;
  onCancel?(shell: unknown, flow: unknown): void | Promise<void>;
}

// -- field editor -----------------------------------------------------------
//
// The field editor contract every registrant of `app_builder.field_editor`
// implements alike -- `field_editor_fallback.ts`'s own module docstring,
// the load-bearing source for every key below. `app_builder_model`
// registers its own full popover against this exact same shape
// (`console_items.js`'s `ConsoleFieldEditor`, `field_popover.js`), so this
// is a whole-tree contract, not just `field_editor_fallback.ts`'s own
// usage of a subset of it. Named here rather than in
// `field_editor_fallback.ts` itself because two wave-2 files in this
// addon build these props directly (`sidebar/add_tab.ts`,
// `sidebar/properties_tab.ts`), so it needs to be importable without
// depending on the fallback component's own module.

/** What a brand new field starts from -- the palette tile's own
 * `{ttype, string}` (`sidebar/add_tab.js`'s new-field tiles); given
 * instead of `field` when there is nothing staged yet to edit. */
export interface FieldEditorInitial {
  ttype?: string;
  string?: string;
}

/**
 * The field editor contract every registrant of `app_builder.field_editor`
 * implements alike.
 */
export interface FieldEditorProps {
  /** The staged definition to edit, or `null`/absent for a new field
   * with nothing chosen yet -- every real opener passes a
   * `DraftFieldJSON` (`console_model.ts:stagedField`), never a live
   * `ir.model.fields` row directly. */
  field?: DraftFieldJSON | null;
  initial?: FieldEditorInitial;
  /** `live` (an `ir.model.fields` row) or `staged` (a draft) -- absent
   * only on the one call site (`view_tab.js`'s model-field editor) that
   * never varies it, always effectively `"staged"`. */
  mode?: "live" | "staged";
  /** The picker's entries for this model, each saying whether it can be
   * made live here and whether it needs this editor first
   * (`console_model.ts`'s own `ConsoleModel.fieldTypes`, the one real
   * builder every call site hands through unchanged). */
  fieldTypes: FieldTypeEntry[];
  existingNames: string[];
  modelName: string;
  inverseOptions: (comodel: string) => Promise<InverseOptions>;
  resolveRelated: (path: string) => Promise<ResolveRelatedResult>;
  /** The draft's spec shape: `string`, `ttype`, `comodel`, `inverse_name`,
   * `selection`, `related`, ... -- every real handler forwards this
   * straight into one of `ConsoleModel`'s own mutators (`addNewField`,
   * `updateStaged`, `addModelField`), all three of which already take
   * the same `Record<string, unknown>`. */
  onSave: (values: Record<string, unknown>) => void;
  /** Offered only for a staged field that can be removed; `null` or
   * absent when there is nothing to delete (a brand new field). */
  onDelete?: (() => void) | null;
  close: () => void;
}

// -- services -----------------------------------------------------------
//
// Narrow facades for the two `env.services` every plain (Owl-free) model
// class in `console/` is handed (`DraftModel`, `BuilderShell`, and every
// pane model besides). Each names only what these files actually call;
// the real services (`@web/core/orm_service`, `@web/core/notifications/
// notification_service`) take a context, extra kwargs, more notification
// options. A single narrow facade module (TYPING.md Phase 2c,
// `console/odoo.ts`) is where these belong once one exists.

export interface OrmService {
  call<T = unknown>(
    model: string,
    method: string,
    args?: unknown[],
    kwargs?: Record<string, unknown>
  ): Promise<T>;
  /** `@web/core/orm_service.js:searchRead` -- `console_model.ts`'s own
   * server-actions list is the one caller so far (the others go through
   * `call`, whose method name and args vary too much to lift into its
   * own facade member). */
  searchRead<T = unknown>(
    model: string,
    domain: unknown[],
    fields: string[],
    kwargs?: Record<string, unknown>
  ): Promise<T[]>;
}

export interface NotificationService {
  add(message: string, options?: {type?: string; sticky?: boolean}): void;
}

/** As much of a field's definition as `console_model.ts:resolveRelated`/
 * `inverseOptions` read off `@web/core/field_service`'s own answer
 * (`fields_get`'s dict, wrapped in a cache) -- that service's own JSDoc
 * types every one of its returns as a bare `object`, so this is traced to
 * the two call sites' actual property reads (`def.type`, `def.relation`,
 * `def.string`, `def.store`) rather than to a vendor type that does not
 * exist. */
export interface FieldDefLite {
  type: string;
  relation?: string | false;
  string?: string;
  store?: boolean;
}

/** `@web/core/field_service`'s own two calls, narrowed the same way
 * (`loadPath`'s `modelsInfo`/`isInvalid`, `loadFields`'s dict by name). */
export interface FieldService {
  loadFields(
    resModel: string,
    options?: {fieldNames?: string[] | false; attributes?: string[]}
  ): Promise<Record<string, FieldDefLite>>;
  loadPath(
    resModel: string,
    path: string
  ): Promise<{
    isInvalid?: string;
    modelsInfo: {resModel: string | null; fieldDefs: Record<string, FieldDefLite>}[];
  }>;
}

/** What the status pill reads (`shell_model.ts`'s `NEUTRAL_ACTIVITY`
 * names every key and its neutral value). */
export interface PaneActivity {
  busy: boolean;
  status: string;
  error: string;
  drag: unknown;
  applying: boolean;
}

/**
 * The contract every pane's own model is expected to answer to, traced
 * from every `this.activeModel.xxx`/`model.xxx` `shell_model.ts` reads or
 * sets. `console_model.ts`'s `ConsoleModel` (the Views pane) and
 * `record_pane_model.ts`'s `RecordPaneModel` are each expected to satisfy
 * this structurally once converted, not literally implement it -- there
 * is no base class here, by the module's own "No Owl... plain so it can
 * be tested and ported" rule.
 */
export interface PaneModel {
  /** Set by the shell itself after the first `open()`; read before
   * deciding whether to `open()` or `reactivate()`. */
  opened: boolean;
  open(target: unknown): void | Promise<void>;
  reactivate?(): void | Promise<void>;
  activity?: PaneActivity;
  history?: unknown;
  afterApply?(): void | Promise<void>;
  refresh?(): void | Promise<void>;
}
