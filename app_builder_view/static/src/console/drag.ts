/** @odoo-module **/
/**
 * Picking something up and putting it down on the canvas.
 *
 * Built on `useDragAndDrop` from `html_editor`, the hook the website
 * builder drags its snippets with, because it already does the hard part
 * right: it tracks the pointer on the window, scrolls the canvas at its
 * edges, and matches a helper against drop zones by geometry alone -- and
 * geometry is the only thing that works, since the body takes no pointer
 * events while a drag is on. What is dragged is a palette tile, a leaf of
 * the view, a list heading, the grip of a selected container or a row of
 * the outline; where it can land is the set of zones `zones.js` lays out
 * from the node table the moment the drag starts -- and, when the outline
 * is open, the set `outline_zones.js` lays over its rows, in a layer of
 * the outline's own. One drag, one chip, one drop, whichever layer takes
 * it. Nothing is re-rendered until it ends.
 *
 * Five things the hook does not say out loud, and this module answers:
 *
 *  - the `element` it hands `onDrag` and `onDragEnd` is the *helper* in
 *    18 and the source in 19, so the source is captured once, in the
 *    `helper` callback, and never read from those.
 *  - it matches zones against the helper's box, from its top-left corner.
 *    So the helper is a small box whose corner *is* the pointer, and the
 *    chip the user sees is a child hanging off it -- a big or centred
 *    helper would pick the zone nearest a point the user is not pointing
 *    at.
 *  - any key, a pointer cancel or a fresh pointer down ends the drag with
 *    the last zone still set, so a cancel is flagged here first, in the
 *    capture phase, and the end handler drops nothing when it is.
 *  - a tab the pointer rests on cannot be hovered, so the dwell is a
 *    timer over the tab rectangles, and the zones are laid out again
 *    once the page has switched.
 *  - its edge scrolling measures the pointer against the canvas's edges
 *    whether or not the pointer is over the canvas, so picking a tile up
 *    at the bottom of the sidebar would scroll the canvas away. It is
 *    turned off, and the canvas is scrolled from here, only while the
 *    pointer is over it and near an edge -- and after each step the hook
 *    is shown the pointer again, where it is, since a zone that scrolled
 *    out from under a still pointer is one the hook would otherwise keep.
 *
 * A kanban adds one more. Its card template renders once per record, and
 * the zones are laid out on *one* card -- the one the dragged field came
 * from, or the first the user can see when what is dragged is a tile --
 * which the overlay marks as the template's stand-in. The pointer crossing
 * into another card lays the zones out again on that one, so the drop is
 * always into the card under the pointer; the server edits the template
 * once, and every card follows.
 *
 * No Owl. Created when the canvas mounts and destroyed when it unmounts;
 * everything it touches belongs to the canvas, the overlay and the
 * console model it is handed.
 */

import { useDragAndDrop } from "@html_editor/utils/drag_and_drop";
import { _t } from "@web/core/l10n/translation";
import * as compat from "./compat";
import type { ConsoleModel } from "./console_model";
import {
    childEntries,
    contains,
    contentElement,
    contentRect,
    flowOf,
    isActivePage,
    plain,
    tabsOf,
} from "./geometry";
import type { ChildEntry } from "./geometry";
import {
    cardAt,
    cardOf,
    cardsOf,
    centreOf,
    columnToken,
    firstVisibleCard,
    ownToken,
} from "./identity";
import { outlineZones } from "./outline_zones";
import type { Overlay, ZoneLayer } from "./overlay";
import { TYPE_ICONS } from "./pending_widget";
import type {
    DragPayload,
    NodeTable,
    Orientation,
    OutlineZoneRow,
    PlainRect,
    Point,
    Token,
    Zone,
} from "./types";
import { buildZones, labelOf, payloadTag } from "./zones";

/** Elements a drag can start from, all inside the console root. */
export const DRAG_SOURCES = [
    ".o_studio_tile",
    "[class*='o_studio_n_']",
    "th[data-name]",
    ".o_studio_grip",
    ".o_studio_outline_row",
].join(", ");

/** What a press on is never a pick-up: the sidebar's handles, the outline's caret. */
const DRAG_IGNORE = ".o_resize, .o_studio_outline_caret, .o_studio_outline_divider";

/** How long the pointer rests on a tab before the notebook switches to it. */
export const TAB_DWELL_MS = 250;

/** The side of the helper box, whose top-left corner is the pointer. */
const HIT = 8;

/** How far outside a zone the pointer may still be to count as over it. */
const DROP_SLACK = HIT;

/** Keys that do not end a drag, as the hook has them. */
const MODIFIER_KEYS = ["Alt", "Control", "Meta", "Shift"];

/** How near the canvas's edge the pointer scrolls it, and how fast, per frame. */
const EDGE = 30;
const EDGE_SPEED = 10;

/**
 * `TYPE_ICONS` (`./pending_widget`, still `.js`, outside this cluster) is a
 * plain object literal with a fixed, known key set, so TS infers a closed
 * literal-key type for it -- indexing it with an arbitrary runtime string
 * (`node.field.type: string`) does not type-check against that under
 * strict/`noImplicitAny`. Re-bound once, here, as the open dictionary it is
 * actually used as; `pending_widget.js` itself is untouched.
 */
const ICONS = TYPE_ICONS as Record<string, string>;

/**
 * `useDragAndDrop`'s own JSDoc (`html_editor/utils/drag_and_drop.js`)
 * infers a shape that is, in two places, inaccurate to what the hook
 * actually does -- the same class of JSDoc-vs-runtime mismatch this
 * migration already hit with `Registry.get`/`queryFirst` (TYPING.md),
 * spread across a whole hook's callbacks instead of one method's arity.
 * Traced against `useDragAndDrop`'s own implementation rather than its
 * JSDoc:
 *
 *  - `helper` is typed `(() => HTMLElement)`, zero arguments, but is
 *    always called with one: `ctx.getHelper({ ...ctx.current,
 *    ...ctx.pointer })` (`drag_and_drop.js:onDragStart`) -- an object
 *    this file's own `makeHelper` destructures as `{element,
 *    helperOffset}`.
 *  - the `dropzone` a `dropzoneOver`/`dropzoneOut`/`onDrag`/`onDragEnd`
 *    handler receives is typed `HTMLElement` (`DropzoneHandlerParams`/
 *    `DragAndDropHandlerParams`), but is actually `ctx.current.dropzone`
 *    itself, an `{el, rect}` pair (`drag_and_drop.js:onDrag`,
 *    `ctx.current.dropzone = { el: dropzoneEl, rect: {...} }`) -- this
 *    file has always read it that way (`dropzone.el`), correctly, against
 *    the real behavior rather than the JSDoc.
 *
 * So the hook is cast once, here, to a signature traced to what it
 * actually does -- the established fix for this class of mismatch, just
 * applied to the whole call instead of to one narrow binding, since
 * nearly every callback this file passes is affected. Each local
 * interface below names only the fields this file actually reads or
 * passes (the same narrow-interface style as `ConsoleModelOwner`); the
 * real objects carry more (`element`, `helper`, a dropzone's `rect`) that
 * nothing here needs.
 */
interface HelperParams {
    element: HTMLElement;
    helperOffset: Point;
}

/** What a drop zone actually is at runtime -- see the comment above. */
interface DropzoneRef {
    el: HTMLElement;
}

interface DragAndDropHandlerParams {
    x: number;
    y: number;
    dropzone: DropzoneRef | null | undefined;
}

interface DropzoneHandlerParams {
    dropzone: DropzoneRef;
}

interface CanvasDragHookParams {
    ref: ReturnType<typeof compat.dragRef>;
    elements: string;
    ignore: string;
    preventDrag: (el: HTMLElement) => boolean;
    tolerance: number;
    delay: number;
    cursor: string;
    scrollingElement: () => HTMLElement;
    edgeScrolling: { enabled: boolean };
    dropzones: () => Element[];
    helper: (params: HelperParams) => HTMLElement;
    onDragStart?: () => void;
    onDrag?: (params: DragAndDropHandlerParams) => void;
    dropzoneOver?: (params: DropzoneHandlerParams) => void;
    dropzoneOut?: (params: DropzoneHandlerParams) => void;
    onDragEnd?: (params: DragAndDropHandlerParams) => void;
    allowDisconnected?: boolean;
}

/** The narrow slice of `NativeDraggableState` (`drag_and_drop.js`'s own
 * JSDoc typedef) this file actually uses -- `.destroy()` alone. */
interface DragHook {
    destroy(): void;
}

const dragAndDrop = useDragAndDrop as (params: CanvasDragHookParams) => DragHook;

/**
 * What the outline registers on the model while it is mounted
 * (`sidebar/outline.js:registerDrag`, still `.js` -- outside this
 * cluster), traced to its real construction there rather than to
 * `ConsoleModel.outlineDrag`'s own declared `unknown` (`console_model.ts`,
 * left untyped since nothing converted before this file ever read it).
 * This file's own narrow reading of an untyped vendor shape, not promoted
 * to `types.ts`: no other converted file reads `outlineDrag` yet.
 */
interface OutlineDragProvider {
    el: HTMLElement;
    layer: ZoneLayer;
    rows(): HTMLElement[];
    /** `this: void`: the real construction (`registerDrag`) assigns this
     * as a plain arrow function of `depth` alone, never reading `this` --
     * confirmed against that source, not assumed -- so passing it on by
     * bare reference (`buildOutlineZones`'s own `indentOf: outline.indentOf`)
     * is genuinely safe, unlike `Registry.get`/`queryFirst`'s own
     * unbound-method traps elsewhere in this migration. Declaring it this
     * way is what lets `unbound-method` tell the two cases apart. */
    indentOf(this: void, depth: number): number;
    isCollapsed(token: Token): boolean;
    expand(token: Token): void;
}

/** What the tab dwell (`watchTab`) remembers while it waits. */
interface TabDwell {
    tab: Element;
    timer: number;
}

/** What the outline row dwell (`watchRow`) remembers while it waits. */
interface RowDwell {
    token: Token;
    timer: number;
}

/** What `CanvasDrag`'s constructor takes. */
export interface CanvasDragParams {
    /** the console element, holding both the sidebar and the canvas */
    rootEl: HTMLElement;
    /** the canvas's scroll container */
    scrollEl: HTMLElement;
    /** the canvas's overlay */
    overlay: Overlay;
    /** the console model */
    model: ConsoleModel;
    /** the last pointer position the canvas saw, for a node rendered more
     * than once */
    point: () => Point | null;
    /** told where a drop was made, so the canvas can keep pointing at
     * that card */
    pointAt?: (point: Point) => void;
}

/** What `makeCanvasDrag` itself takes -- the same as `CanvasDragParams`,
 * but `point` optional too: this is the one place both defaults are
 * given (the constructor itself only defaults `pointAt`, matching the
 * original's own split between the factory and the class). */
export interface MakeCanvasDragParams {
    rootEl: HTMLElement;
    scrollEl: HTMLElement;
    overlay: Overlay;
    model: ConsoleModel;
    point?: () => Point | null;
    pointAt?: (point: Point) => void;
}

export function makeCanvasDrag({
    rootEl,
    scrollEl,
    overlay,
    model,
    point = () => null,
    pointAt = () => {},
}: MakeCanvasDragParams): CanvasDrag {
    return new CanvasDrag({ rootEl, scrollEl, overlay, model, point, pointAt });
}

export class CanvasDrag {
    rootEl: HTMLElement;
    scrollEl: HTMLElement;
    overlay: Overlay;
    model: ConsoleModel;
    point: () => Point | null;
    pointAt: (point: Point) => void;

    source: HTMLElement | null;
    payload: DragPayload | null;
    tag: string | null;
    moving: Token | null;
    /** The kanban card the zones are laid out on; `null` off a kanban. */
    card: Element | null;
    zones: Element[];
    zoneOf: Map<Element, Zone>;
    tabs: Element[];
    dwell: TabDwell | null;
    /** The outline's provider (`sidebar/outline.js`), taken from the
     * model when a drag starts and held until it ends; `null` when
     * there is no outline to drop on. */
    outline: OutlineDragProvider | null;
    outlineObserver: MutationObserver | null;
    rowDwell: RowDwell | null;
    /** The scroll container being edge-scrolled, the canvas or the
     * outline's list, for as long as the pointer stays at its edge. */
    edgeEl: Element | null;
    onOutlineScroll: () => void;
    pointer: Point;
    cancelled: boolean;
    dragging: boolean;
    hit: HTMLDivElement | null;
    chip: { el: HTMLDivElement; caption: HTMLSpanElement } | null;
    rebuildFrame: number | null;
    edgeFrame: number | null;
    observer: MutationObserver | null;

    onKeyDown: (ev: KeyboardEvent) => void;
    onPointerCancel: () => void;
    onPointerDown: () => void;

    hook: DragHook | null;

    constructor({ rootEl, scrollEl, overlay, model, point, pointAt = () => {} }: CanvasDragParams) {
        this.rootEl = rootEl;
        this.scrollEl = scrollEl;
        this.overlay = overlay;
        this.model = model;
        this.point = point;
        this.pointAt = pointAt;

        this.source = null;
        this.payload = null;
        this.tag = null;
        this.moving = null;
        this.card = null;
        this.zones = [];
        this.zoneOf = new Map();
        this.tabs = [];
        this.dwell = null;
        this.outline = null;
        this.outlineObserver = null;
        this.rowDwell = null;
        this.edgeEl = null;
        this.onOutlineScroll = () => this.onCanvasChanged();
        this.pointer = { x: 0, y: 0 };
        this.cancelled = false;
        this.dragging = false;
        this.hit = null;
        this.chip = null;
        this.rebuildFrame = null;
        this.edgeFrame = null;
        this.observer = null;

        // The hook's own key listener ends the drag; this one runs before
        // it -- same phase, registered first -- to say why it ended.
        this.onKeyDown = (ev: KeyboardEvent) => {
            if (this.dragging && !MODIFIER_KEYS.includes(ev.key)) {
                this.cancelled = true;
            }
        };
        this.onPointerCancel = () => {
            if (this.dragging) {
                this.cancelled = true;
            }
        };
        // A pointer going down during a drag means the pointer up was
        // never seen -- it happened outside the window -- and the hook
        // ends the drag on it; that is not a drop.
        this.onPointerDown = () => {
            if (this.dragging) {
                this.cancelled = true;
            }
        };
        window.addEventListener("keydown", this.onKeyDown, true);
        window.addEventListener("pointercancel", this.onPointerCancel, true);
        window.addEventListener("pointerdown", this.onPointerDown, true);

        this.hook = dragAndDrop({
            ref: compat.dragRef({ el: rootEl }),
            elements: DRAG_SOURCES,
            ignore: DRAG_IGNORE,
            preventDrag: (el) => !this.isDraggable(el),
            tolerance: 5,
            delay: 0,
            cursor: "grabbing",
            scrollingElement: () => this.scrollEl,
            edgeScrolling: { enabled: false },
            dropzones: () => this.zones,
            helper: (params) => this.makeHelper(params),
            onDragStart: () => this.onDragStart(),
            onDrag: (params) => this.onDrag(params),
            dropzoneOver: ({ dropzone }) => this.onZoneOver(dropzone),
            dropzoneOut: ({ dropzone }) => this.onZoneOut(dropzone),
            onDragEnd: (params) => this.onDragEnd(params),
            ...compat.dragExtraParams(),
        });
    }

    destroy(): void {
        window.removeEventListener("keydown", this.onKeyDown, true);
        window.removeEventListener("pointercancel", this.onPointerCancel, true);
        window.removeEventListener("pointerdown", this.onPointerDown, true);
        this.clearDwell();
        if (this.hook) {
            this.hook.destroy();
            this.hook = null;
        }
        this.teardown();
    }

    // -- what may be picked up ----------------------------------------------

    get nodes(): NodeTable {
        return this.model.nodes;
    }

    /**
     * Whether `el` -- something matching `DRAG_SOURCES` -- starts a drag.
     *
     * A tile, unless disabled. A heading, when its column is movable. The
     * grip, when the selection is a movable container. A node of the view
     * when it is movable and a leaf: a container is picked up by its grip,
     * so that a press on it is a click on what it holds. A row of the
     * outline when its node is movable, container or not: a row holds
     * nothing a press could mean instead.
     */
    isDraggable(el: HTMLElement | null): boolean {
        if (!el || !this.model.canWrite) {
            return false;
        }
        if (el.classList.contains("o_studio_tile")) {
            return (
                el.classList.contains("o_studio_draggable") && !(el as HTMLButtonElement).disabled
            );
        }
        if (el.classList.contains("o_studio_grip")) {
            const node = this.model.selectedNode;
            return Boolean(node && node.container && node.movable);
        }
        const token = this.tokenOfSource(el);
        const node = token ? this.nodes[token] : null;
        if (el.classList.contains("o_studio_outline_row")) {
            return Boolean(node && node.movable);
        }
        return Boolean(node && node.movable && !node.container);
    }

    /** The token a source element stands for: its own, its column's, its row's. */
    tokenOfSource(el: HTMLElement): Token | null {
        if (el.classList.contains("o_studio_outline_row")) {
            return el.dataset["token"] || null;
        }
        if (el.matches("th[data-name]")) {
            return columnToken(el.dataset["name"] || "", this.nodes);
        }
        return ownToken(el);
    }

    /** What a source element means as a drop payload, or `null`. */
    payloadFor(el: HTMLElement): DragPayload | null {
        if (el.classList.contains("o_studio_tile")) {
            const kind = el.dataset["kind"];
            const key = el.dataset["key"] || el.dataset["name"];
            const label = el.dataset["label"] || (el.textContent || "").trim();
            if (kind === "existing_field") {
                return { kind, name: key, label };
            }
            if (kind === "component") {
                return { kind, component: key, values: {}, label };
            }
            if (kind === "new_field") {
                return {
                    kind,
                    values: { ttype: key, field_description: String(_t("New %s", label)) },
                    label,
                };
            }
            return null;
        }
        const token = el.classList.contains("o_studio_grip")
            ? this.model.selection && this.model.selection.token
            : this.tokenOfSource(el);
        // A separate guard from the node lookup below -- not folded into
        // one ternary the way the original reads -- so that `token` itself
        // narrows to `Token` for the returns further down; deriving `node`
        // from `token` in a ternary and checking only `node` afterwards
        // does not, under `exactOptionalPropertyTypes`, tell the checker
        // `token` was non-null too (two different bindings, no tracked
        // correlation between them).
        if (!token) {
            return null;
        }
        const node = this.nodes[token];
        if (!node) {
            return null;
        }
        if (node.kind === "pending") {
            // A ghost is not in the arch to be moved: dragging it re-anchors
            // the staged field, which is the draft's business.
            const name = (node.pending && node.pending.name) || node.name;
            return { kind: "move_pending", token, name, label: labelOf(node) };
        }
        return { kind: "move", token, label: labelOf(node) };
    }

    // -- the helper ---------------------------------------------------------

    /**
     * The element the hook moves with the pointer: a small box whose
     * top-left corner sits on the pointer, and the chip as its child.
     */
    makeHelper({ element, helperOffset }: HelperParams): HTMLDivElement {
        this.source = element;
        this.payload = this.payloadFor(element);
        const hit = document.createElement("div");
        hit.className = "o_studio_drag_hit";
        hit.style.width = `${HIT}px`;
        hit.style.height = `${HIT}px`;
        const chip = document.createElement("div");
        chip.className = "o_studio_drag_chip";
        const icon = document.createElement("i");
        icon.className = this.iconFor(element);
        const label = document.createElement("span");
        label.className = "o_studio_chip_label";
        label.textContent = this.payload ? this.payload.label || "" : "";
        const caption = document.createElement("span");
        caption.className = "o_studio_chip_caption";
        chip.append(icon, label, caption);
        hit.appendChild(chip);
        document.body.appendChild(hit);
        helperOffset.x = 0;
        helperOffset.y = 0;
        this.hit = hit;
        this.chip = { el: chip, caption };
        return hit;
    }

    /** The chip's icon: a field's type, a tile's own, else a generic one. */
    iconFor(el: HTMLElement): string {
        const token = this.payload && this.payload.kind === "move" ? this.payload.token : null;
        const node = token ? this.nodes[token] : null;
        // Captured once: a second `ICONS[node.field.type]` below would not
        // re-narrow to the same result under `noUncheckedIndexedAccess`,
        // the same repeated-bracket-index trap this migration has already
        // hit on index-signature reads elsewhere.
        const icon = node && node.field ? ICONS[node.field.type] : undefined;
        if (icon) {
            return icon;
        }
        const own = el.classList.contains("o_studio_tile") ? el.querySelector("i") : null;
        if (own && own.className) {
            return own.className;
        }
        return "fa fa-arrows";
    }

    setCaption(text: string): void {
        if (this.chip && this.chip.caption.textContent !== text) {
            this.chip.caption.textContent = text;
            this.chip.el.classList.toggle("o_studio_chip_has_caption", Boolean(text));
        }
        this.model.setDragCaption(text);
    }

    // -- the drag -----------------------------------------------------------

    onDragStart(): void {
        this.dragging = true;
        this.cancelled = false;
        // Captured once: `this.payload` is read again below, past several
        // calls (`payloadTag`, `classList.add`, `beginDrag`...), each of
        // which invalidates the checker's narrowing of a `this.`-property
        // the same way one already does for `this.state` in `overlay.ts`'s
        // own `align()` -- a plain local binding, once narrowed, does not
        // lose it that way.
        const payload = this.payload;
        if (!payload) {
            this.cancelled = true;
            return;
        }
        this.tag = payloadTag(payload, this.nodes);
        this.moving = ["move", "move_pending"].includes(payload.kind)
            ? (payload.token ?? null)
            : null;
        document.body.classList.add("o_studio_dragging");
        this.rootEl.classList.add("o_studio_dragging");
        this.model.beginDrag(payload.label || "");
        this.card = this.startingCard();
        // The outline, as it is now: its provider is taken once, since a
        // pane cannot change under a drag -- that takes a click, which
        // ends it -- and a half-registered one is not to be trusted.
        const outline = this.model.outlineDrag as OutlineDragProvider | null;
        this.outline = outline && outline.el && outline.el.isConnected ? outline : null;
        this.buildZones();
        // The canvas re-renders under the drag when a tab switches; the
        // zones follow. Watched from here, for the drag's own duration,
        // so the drag does not depend on who else is watching the canvas.
        // The overlay's own changes -- the zones being drawn -- are not
        // what is watched for.
        this.observer = this.watch(this.scrollEl, ".o_studio_overlay");
        // Captured for the same reason as `payload` above: `this.watch(...)`
        // is itself a call, and `this.outline.el` is read twice past it.
        const activeOutline = this.outline;
        if (activeOutline) {
            // The outline re-renders when a row unfolds, and its rows move
            // when its list scrolls: either way the zones over it are laid
            // out again.
            this.outlineObserver = this.watch(activeOutline.el, ".o_studio_zones");
            activeOutline.el.addEventListener("scroll", this.onOutlineScroll);
        }
    }

    /**
     * Lay the zones out again whenever `el` changes under the drag, its
     * own zone layer -- `layerSelector` -- excepted.
     */
    watch(el: HTMLElement, layerSelector: string): MutationObserver {
        const observer = new MutationObserver((records: MutationRecord[]) => {
            // `MutationRecord.target` is typed `Node` by the DOM lib, which
            // has no `.closest()` -- the original's own duck check
            // (`!r.target.closest`) is written as "does this target support
            // `.closest`", which `instanceof Element` says precisely.
            if (
                records.some(
                    (r) => !(r.target instanceof Element) || !r.target.closest(layerSelector),
                )
            ) {
                this.onCanvasChanged();
            }
        });
        observer.observe(el, { childList: true, subtree: true });
        return observer;
    }

    /**
     * The kanban card a drag starts on, or `null` off a kanban: the card
     * the dragged node is in, or -- for a tile, which is in no card --
     * the first one the user can see. Only on a kanban canvas: a form
     * with an x2many kanban in it has cards too, and none of them is a
     * template of this view.
     */
    startingCard(): Element | null {
        if (this.model.viewType !== "kanban" || !cardsOf(this.scrollEl).length) {
            return null;
        }
        const source = this.source;
        const own = source && this.scrollEl.contains(source) ? cardOf(source) : null;
        return own || firstVisibleCard(this.scrollEl, this.scrollEl);
    }

    /**
     * Lay the zones out from the canvas as it is now, and remember the
     * tabs, so the dwell can find them without pointer events.
     *
     * On a kanban every container is measured in the one card the drag
     * is on: the point handed to the geometry is that card's centre,
     * which every part of the card answers to, and the card's rendering
     * -- not the arch -- says which way its parts flow.
     */
    buildZones(): void {
        const canvas = this.buildCanvasZones();
        const outline = this.outline ? this.buildOutlineZones(this.outline) : [];
        // Kept across rebuilds, not replaced: the hook may still hold a
        // zone from before, and what it stood for has to be answerable.
        this.zones = [...canvas, ...outline];
        this.tabs = tabsOf(this.scrollEl);
    }

    /** The canvas's zones, drawn in its overlay; the elements, in order. */
    buildCanvasZones(): Element[] {
        const root = this.scrollEl;
        const nodes = this.nodes;
        if (this.card && !this.card.isConnected) {
            // The board re-rendered under the drag: the same place, or
            // the first card there is.
            this.card = cardAt(root, this.pointer) || firstVisibleCard(root, root);
        }
        const point = this.card ? centreOf(this.card) : this.point();
        const contentOf = (token: Token): PlainRect | null =>
            contentRect(token, root, nodes, point);
        const childrenOf = (token: Token): ChildEntry[] =>
            childEntries(token, root, nodes, contentElement(token, root, nodes, point));
        const isActive = (token: Token): boolean => isActivePage(token, root, nodes);
        const flow = (token: Token): Orientation | null =>
            this.card ? flowOf(contentElement(token, root, nodes, point)) : null;
        const { zones, containers } = buildZones({
            nodes,
            tag: this.tag,
            moving: this.moving,
            contentOf,
            childrenOf,
            isActive,
            flowOf: flow,
        });
        const template = this.card ? plain(this.card.getBoundingClientRect()) : null;
        const els = this.overlay.setZones(zones, containers, template);
        // `!`: `overlay.ts:setZones` returns one element per zone, in the
        // same order (its own docstring), so `els`/`zones` are always
        // parallel, same-length arrays -- an invariant `noUncheckedIndexedAccess`
        // cannot see from the two independent array types alone.
        els.forEach((el, index) => {
            this.zoneOf.set(el, zones[index]!);
        });
        return els;
    }

    /**
     * The outline's zones, drawn in its own layer over the rows that are
     * on screen -- the list clips what it scrolls away, and the hook
     * measures boxes that clipping does not shrink.
     */
    buildOutlineZones(outline: OutlineDragProvider): Element[] {
        if (!outline.el.isConnected) {
            return [];
        }
        const box = plain(outline.el.getBoundingClientRect());
        const rows: OutlineZoneRow[] = [];
        for (const el of outline.rows()) {
            const rect = plain(el.getBoundingClientRect());
            if (rect.top + rect.height <= box.top || rect.top >= box.top + box.height) {
                continue;
            }
            const token = el.dataset["token"];
            if (!token) {
                continue;
            }
            rows.push({
                token,
                depth: Number(el.dataset["depth"]) || 0,
                rect,
                collapsed: el.classList.contains("o_studio_outline_collapsed"),
            });
        }
        const { zones, containers } = outlineZones({
            nodes: this.nodes,
            tag: this.tag,
            moving: this.moving,
            rows,
            indentOf: outline.indentOf,
            box,
        });
        const els = outline.layer.setZones(zones, containers);
        els.forEach((el, index) => {
            this.zoneOf.set(el, zones[index]!);
        });
        return els;
    }

    /**
     * The canvas has re-rendered under the drag -- a tab switched. The
     * zones are laid out again on the next frame, once, however many
     * mutations the switch produced.
     */
    onCanvasChanged(): void {
        if (!this.dragging || this.rebuildFrame) {
            return;
        }
        this.rebuildFrame = window.requestAnimationFrame(() => {
            this.rebuildFrame = null;
            if (this.dragging) {
                this.buildZones();
                // What is under a still pointer may have changed -- a row
                // unfolded, the list scrolled -- and only a pointer event
                // has the hook look again.
                this.nudge();
            }
        });
    }

    onDrag({ x, y }: DragAndDropHandlerParams): void {
        this.pointer = { x, y };
        if (!this.dragging || this.cancelled) {
            return;
        }
        this.watchTab(x, y);
        this.watchRow(x, y);
        this.watchCard(x, y);
        this.watchEdge();
    }

    /**
     * The pointer resting on a folded row of the outline for
     * `TAB_DWELL_MS` unfolds it, as resting on a tab switches to it: what
     * is inside becomes a place to drop. The row is itself a zone -- into
     * it -- so the chip keeps saying so; the unfold re-renders the list,
     * and the zones follow.
     */
    watchRow(x: number, y: number): void {
        // Captured once, for the same reason as `payload` in `onDragStart`:
        // `outline.isCollapsed(token)` below is past a call (`this.rowAt`).
        const outline = this.outline;
        if (!outline) {
            return;
        }
        const row = this.rowAt({ x, y });
        const token = row ? row.dataset["token"] : undefined;
        const folds = Boolean(
            token &&
            row &&
            row.classList.contains("o_studio_outline_collapsed") &&
            outline.isCollapsed(token),
        );
        // `!token` here is never true when `folds` is: `folds` is derived
        // from the same `token`, never reassigned in between. It exists
        // for the checker, which cannot see that correlation through
        // `Boolean(...)` -- an opaque call, as far as narrowing goes,
        // the same way `samePlace`'s own `Boolean(a && b)` isn't enough
        // to narrow `a`/`b` for what follows it.
        if (!folds || !token) {
            this.clearRowDwell();
            return;
        }
        if (this.rowDwell && this.rowDwell.token === token) {
            return;
        }
        this.clearRowDwell();
        this.rowDwell = {
            token,
            timer: window.setTimeout(() => {
                this.rowDwell = null;
                const still = this.rowAt(this.pointer);
                if (this.dragging && still && still.dataset["token"] === token) {
                    outline.expand(token);
                    this.onCanvasChanged();
                }
            }, TAB_DWELL_MS),
        };
    }

    /** The outline row under a viewport point, or `null`. */
    rowAt(point: Point): HTMLElement | null {
        const outline = this.outline;
        if (!outline || !outline.el.isConnected) {
            return null;
        }
        if (!contains(plain(outline.el.getBoundingClientRect()), point)) {
            return null;
        }
        return (
            outline.rows().find((row) => contains(plain(row.getBoundingClientRect()), point)) ||
            null
        );
    }

    clearRowDwell(): void {
        if (this.rowDwell) {
            window.clearTimeout(this.rowDwell.timer);
            this.rowDwell = null;
        }
    }

    /**
     * The pointer has crossed into another card of the kanban: the zones
     * are laid out again on that one, on the next frame -- the same
     * throttle as a re-render, and for the same reason.
     */
    watchCard(x: number, y: number): void {
        if (!this.card) {
            return;
        }
        const card = cardAt(this.scrollEl, { x, y });
        if (card && card !== this.card) {
            this.card = card;
            this.onCanvasChanged();
        }
    }

    /**
     * Scroll the canvas -- or the outline's list -- while the pointer is
     * over it and near its top or bottom, and keep scrolling until it
     * moves away: the canvas's zones travel with its content, so nothing
     * has to be laid out again for it, and the outline's are laid out
     * again on its scroll. What is under the pointer changes either way,
     * and only a pointer event has the hook look again.
     */
    watchEdge(): void {
        const { x, y } = this.pointer;
        const outline = this.outline;
        // Built by hand rather than `[a, b].filter(Boolean)`: `filter`
        // does not narrow a `(T | null)[]` to `T[]` without an explicit
        // type-predicate callback, which `Boolean` -- a plain function
        // reference here, not one -- does not give it.
        const candidates: Element[] = [this.scrollEl];
        if (outline) {
            candidates.push(outline.el);
        }
        let el = this.edgeEl && candidates.includes(this.edgeEl) ? this.edgeEl : null;
        let step = 0;
        for (const candidate of el ? [el] : candidates) {
            const rect = candidate.getBoundingClientRect();
            if (x < rect.left || x > rect.right) {
                continue;
            }
            if (y >= rect.top && y < rect.top + EDGE) {
                step = -EDGE_SPEED * (1 - (y - rect.top) / EDGE);
            } else if (y <= rect.bottom && y > rect.bottom - EDGE) {
                step = EDGE_SPEED * (1 - (rect.bottom - y) / EDGE);
            }
            if (step) {
                el = candidate;
                break;
            }
        }
        if (!step || !el) {
            this.stopEdge();
            return;
        }
        // Frozen into its own const: a `let` is never narrowed inside a
        // nested closure regardless of what was checked before it, since
        // the closure could run after a later reassignment -- `tick` below
        // needs a value that stays non-null for its own lifetime, not
        // `el`'s widest declared type.
        const edgeEl = el;
        this.edgeEl = edgeEl;
        if (this.edgeFrame) {
            return;
        }
        const tick = (): void => {
            if (!this.dragging) {
                this.edgeFrame = null;
                return;
            }
            edgeEl.scrollBy({ top: step });
            this.edgeFrame = window.requestAnimationFrame(() => {
                this.edgeFrame = null;
                this.watchEdge();
            });
            this.nudge();
        };
        tick();
    }

    /**
     * A pointer move at the pointer's own position, for the hook: it
     * matches zones and tabs only when the pointer moves, and the canvas
     * has just moved under it instead.
     */
    nudge(): void {
        const { x, y } = this.pointer;
        const move: PointerEventInit = { clientX: x, clientY: y, bubbles: true, cancelable: true };
        window.dispatchEvent(new PointerEvent("pointermove", move));
    }

    stopEdge(): void {
        this.edgeEl = null;
        if (this.edgeFrame) {
            window.cancelAnimationFrame(this.edgeFrame);
            this.edgeFrame = null;
        }
    }

    /**
     * The tab under the pointer, geometrically -- measured as it is now,
     * since the canvas may have scrolled since the tabs were found.
     * Resting on one that is not the active page for `TAB_DWELL_MS`
     * clicks it; the canvas lets that click through, and its re-render is
     * what rebuilds the zones.
     */
    watchTab(x: number, y: number): void {
        const tab = this.tabAt({ x, y });
        if (!tab) {
            if (this.dwell) {
                this.clearDwell();
                this.setCaption(this.captionOfCurrent());
            }
            return;
        }
        if (this.dwell && this.dwell.tab === tab) {
            return;
        }
        this.clearDwell();
        this.setCaption(String(_t("switching to %s…", (tab.textContent || "").trim())));
        this.dwell = {
            tab,
            timer: window.setTimeout(() => {
                this.dwell = null;
                if (!this.dragging || this.tabAt(this.pointer) !== tab) {
                    return;
                }
                // `this.tabs`/`tabAt` are `Element[]`/`Element | null`,
                // inherited from `geometry.ts:tabsOf`'s own `Element[]`
                // return -- `.click()` is an `HTMLElement` method, not a
                // plain `Element` one. Real tabs are always `<a>`/`<button>`
                // (`compat.ts:TAB_SELECTOR`'s own docstring).
                (tab as HTMLElement).click();
                // The page is switching: the chip says so no longer, and
                // says what the next zone says once the pointer is on one.
                this.setCaption(this.captionOfCurrent());
                this.onCanvasChanged();
            }, TAB_DWELL_MS),
        };
    }

    /** The inactive tab under a viewport point, or `null`. */
    tabAt(point: Point): Element | null {
        return (
            this.tabs.find(
                (tab) =>
                    tab.isConnected &&
                    !tab.classList.contains("active") &&
                    contains(plain(tab.getBoundingClientRect()), point),
            ) || null
        );
    }

    clearDwell(): void {
        if (this.dwell) {
            window.clearTimeout(this.dwell.timer);
            this.dwell = null;
        }
    }

    captionOfCurrent(): string {
        const active = this.zones.find((el) => el.classList.contains("o_studio_dz_active"));
        const zone = active && this.zoneOf.get(active);
        return zone ? zone.caption : "";
    }

    onZoneOver(dropzone: DropzoneRef): void {
        const zone = this.zoneOf.get(dropzone.el);
        dropzone.el.classList.add("o_studio_dz_active");
        if (!this.dwell) {
            this.setCaption(zone ? zone.caption : "");
        }
    }

    onZoneOut(dropzone: DropzoneRef): void {
        dropzone.el.classList.remove("o_studio_dz_active");
        if (!this.dwell) {
            this.setCaption("");
        }
    }

    /**
     * The drag is over. Whatever ended it, the zones and the chip go and
     * the canvas is told; only a drop the pointer actually made -- not a
     * cancel, not a zone the hook kept out of stickiness after the
     * pointer left it -- is sent to the server.
     */
    onDragEnd({ dropzone, x, y }: DragAndDropHandlerParams): void {
        const zone = this.zoneToDrop(dropzone, { x, y });
        const payload = this.payload;
        this.teardown();
        if (zone && payload) {
            if (zone.layer !== "outline") {
                // A point in the sidebar says nothing about which card the
                // frame should be drawn in.
                this.pointAt({ x, y });
            }
            void this.drop(zone, payload);
        }
    }

    /**
     * The zone a drop lands in, or `null`: not after a cancel, and not one
     * the pointer is no longer over. The hook may hold a zone from before
     * a rebuild -- the page switched under it -- in which case the same
     * place in the zones as they are now is what counts.
     */
    zoneToDrop(dropzone: DropzoneRef | null | undefined, pointer: Point): Zone | null {
        if (this.cancelled || !dropzone || !dropzone.el) {
            return null;
        }
        const zone = this.zoneOf.get(dropzone.el);
        if (!zone) {
            return null;
        }
        let el: Element = dropzone.el;
        if (!el.isConnected || !this.zones.includes(el)) {
            const found = this.zones.find((candidate) =>
                samePlace(this.zoneOf.get(candidate), zone),
            );
            if (!found) {
                return null;
            }
            el = found;
        }
        const rect = el.getBoundingClientRect();
        const box: PlainRect = {
            top: rect.top,
            left: rect.left,
            width: rect.width,
            height: rect.height,
        };
        return contains(box, pointer, DROP_SLACK) ? (this.zoneOf.get(el) ?? null) : null;
    }

    teardown(): void {
        const wasDragging = this.dragging;
        this.dragging = false;
        this.clearDwell();
        this.clearRowDwell();
        this.stopEdge();
        if (this.observer) {
            this.observer.disconnect();
            this.observer = null;
        }
        if (this.outlineObserver) {
            this.outlineObserver.disconnect();
            this.outlineObserver = null;
        }
        // Captured once, for the same reason as elsewhere: `.layer` is
        // read past `.el`'s own `removeEventListener` call.
        const outline = this.outline;
        if (outline) {
            outline.el.removeEventListener("scroll", this.onOutlineScroll);
            outline.layer.clearZones();
            this.outline = null;
        }
        if (this.rebuildFrame) {
            window.cancelAnimationFrame(this.rebuildFrame);
            this.rebuildFrame = null;
        }
        this.overlay.clearZones();
        this.zones = [];
        this.zoneOf = new Map();
        this.tabs = [];
        if (this.hit) {
            this.hit.remove();
            this.hit = null;
        }
        this.chip = null;
        this.source = null;
        this.payload = null;
        this.tag = null;
        this.moving = null;
        this.card = null;
        document.body.classList.remove("o_studio_dragging");
        this.rootEl.classList.remove("o_studio_dragging");
        if (wasDragging) {
            this.model.endDrag();
        }
    }

    async drop(zone: Zone, payload: DragPayload): Promise<void> {
        // `sent` carries an index signature (from `DragPayload`'s own),
        // so the write below needs the same bracket-notation treatment as
        // `draft_model.ts:updateStaged`'s own `rest["field_description"]`:
        // `token` was pulled out of the named view by this destructure, so
        // it is reachable on `sent` only through the index signature.
        const { label, token, ...sent } = payload;
        void label;
        if (sent.kind === "move") {
            sent["token"] = token;
        }
        const result = await this.model.drop(zone.token, zone.position, sent);
        if (result && result.created_field) {
            focusLabelRow(this.rootEl);
        }
    }
}

/**
 * Whether two zone descriptors name the same place, across a rebuild --
 * in the same layer: the canvas and the outline both offer "after City
 * in the group", and a zone the outline held is found again in the
 * outline, not under the pointer's old spot on the canvas.
 */
function samePlace(a: Zone | null | undefined, b: Zone | null | undefined): boolean {
    // An early guard rather than the original's `Boolean(a && b) && ...`:
    // `Boolean(...)` is an opaque function call as far as the checker's
    // narrowing goes, so it would not carry `a`/`b`'s non-null-ness into
    // the property reads that follow it. Same result, provable.
    if (!a || !b) {
        return false;
    }
    return (
        (a.layer || "canvas") === (b.layer || "canvas") &&
        a.container === b.container &&
        a.token === b.token &&
        a.position === b.position
    );
}

/**
 * Put the cursor in the Label row of the properties, its text selected,
 * once the panel has drawn it: a field just dropped is most often
 * renamed next. The panel asks the server what the node carries before
 * it draws its rows, so the input is waited for rather than assumed.
 */
export function focusLabelRow(
    rootEl: HTMLElement,
    { tries = 40, every = 50 }: { tries?: number; every?: number } = {},
): void {
    const attempt = (left: number): void => {
        // Typed via the generic form rather than a cast after the fact:
        // the selector always names a real `<input>`, so this is the
        // element the query actually returns, not a widened `Element`
        // narrowed back down.
        const input = rootEl.querySelector<HTMLInputElement>(
            ".o_studio_properties .o_studio_row[data-row='string'] input",
        );
        if (input) {
            input.focus();
            if (typeof input.select === "function") {
                input.select();
            }
            return;
        }
        if (left > 0) {
            window.setTimeout(() => attempt(left - 1), every);
        }
    };
    attempt(tries);
}
