/** @odoo-module **/
/**
 * The shapes the canvas payload and node table carry, shared by every
 * console module that reads them.
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
    // under a `p_<name>` token (`studio_view_canvas.py`); not one of
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

/** A token naming one node of the arch (`o_studio_n_<ordinal>`), or the
 * ghost of a staged field (`p_<name>`). Opaque on the client: never parsed,
 * only compared and looked up in a `NodeTable`. */
export type Token = string;

/** One entry of the canvas's node table (`canvas_stamp.py:stamp`). */
export interface StudioNode {
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
     * draft, not yet applied (`studio_view_canvas.py`'s `_stamp_pending`
     * construction, the block after `"label": None,`). `StudioNode` stays
     * one flat shape rather than a `kind`-discriminated union for now;
     * this is the one field that is genuinely conditional on `kind`. */
    pending?: PendingFieldInfo;
}

/** The canvas's node table: every node of the arch, by token. */
export type NodeTable = Readonly<Record<Token, StudioNode>>;

/** Where a field came from: a real column (`ir.model.fields` with
 * `state="base"`, from Python) or one the studio itself created
 * (`state="manual"`). Decides whether the definition panel shows facts or
 * lets the user edit them (`_field_origin`). */
export type FieldOrigin = "core" | "manual";

/** A field on some model, no more than a picker needs
 * (`studio_view_editor.py:_model_fields`, `app_builder_base/tools/catalogue.py`'s
 * own `field_types` rows read the same three keys). */
export interface StudioModelFieldEntry {
    name: string;
    string: string;
    type: string;
}

/**
 * `studio.view.editor._field_info`, plus where the field came from
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
    comodel_fields?: StudioModelFieldEntry[];
}

/**
 * A field staged on a `studio.model.draft`, not yet applied: what
 * `StudioNode.pending` carries on the ghost node the canvas splices in
 * for it (`studio_view_canvas.py`, the `_stamp_pending`-style
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
 * may write (`studio_view_canvas.py:_field_definition`). `editable` names
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
     * (`zones.js:COMPONENT_TAGS`). */
    component?: string;
    /** For `kind: "move"`: the node being moved. */
    token?: Token;
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
    node: StudioNode;
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
