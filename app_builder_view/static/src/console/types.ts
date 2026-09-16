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

/** Which label style a field renders with, or none (`label_of`). */
export type LabelStyle = "group" | "label" | null;

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
    /** Field metadata for a `field`/`column` node; not yet given a precise
     * shape here (see module docstring). */
    field: unknown | null;
    view_id: number | null;
    label: LabelStyle;
}

/** The canvas's node table: every node of the arch, by token. */
export type NodeTable = Readonly<Record<Token, StudioNode>>;

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
