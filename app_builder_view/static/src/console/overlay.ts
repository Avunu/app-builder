/** @odoo-module **/
/**
 * The layer drawn over the canvas: a hover outline, a selection frame,
 * and -- while something is dragged -- the drop zones.
 *
 * Owned by the canvas's scroll container and drawn by hand, not by Owl.
 * Two reasons. The view underneath re-renders whenever the record loads or
 * a tab switches, and an outline that lived inside it would be torn down
 * with it; and the drag puts its drop zones in this same layer, where
 * `makeDraggableHook` can read their rectangles without them being
 * inside the view's own DOM. So the layer is a plain element the canvas
 * creates once, and this class positions things in it.
 *
 * Coordinates are relative to the scroll container's content, so the layer
 * scrolls with the view; `align()` re-measures on resize and after the view
 * has re-rendered. The zones are not re-measured: they are laid out by the
 * drag for the canvas as it is, and laid out again by it when that changes.
 *
 * A kanban renders one node once per card, and the two outlines answer
 * to two points: the hover to where the pointer is now, the selection to
 * where it was when the click was made. Without the second the frame
 * would leave the card that was clicked for whichever card the pointer
 * wandered over next.
 */

import { _t } from "@web/core/l10n/translation";
import { elementsFor } from "./identity";
import { outlineRect, toContent } from "./geometry";
import type { NodeTable, PlainRect, Point, StudioNode, Token, Zone, ZoneContainer } from "./types";

/** What the constructor's `handlers` argument carries: the one callback
 * the overlay itself triggers, when the remove button on the selection
 * frame is used. */
export interface OverlayHandlers {
    onRemove?(token: Token): void;
}

/** What `update()` takes: what to draw right now. `hover` and `selection`
 * are tokens; `point` the last pointer position, for a node rendered more
 * than once, and `selectionPoint` where the selection was made -- the same
 * point when the caller keeps no other. */
export interface OverlayUpdate {
    hover: Token | null;
    selection: Token | null;
    nodes: NodeTable;
    tag: string;
    point: Point | null;
    selectionPoint?: Point | null;
}

/** The overlay's own memory of the last `update()`, re-measured by
 * `align()` whenever the DOM might have moved under it. */
interface OverlayState {
    hover: Token | null;
    selection: Token | null;
    nodes: NodeTable;
    tag: string;
    point: Point | null;
    selectionPoint: Point | null;
}

export class Overlay {
    scrollEl: HTMLElement;
    handlers: OverlayHandlers;
    layer: HTMLDivElement;
    hoverEl: HTMLDivElement;
    frameEl: HTMLDivElement;
    tagEl: HTMLSpanElement;
    gripEl: HTMLButtonElement;
    removeEl: HTMLButtonElement;
    zones: ZoneLayer;
    zoneLayer: HTMLDivElement;
    state: OverlayState;

    /** `scrollEl` is the canvas's scroll container; `handlers` is
     * `{onRemove(token)}`. */
    constructor(scrollEl: HTMLElement, handlers: OverlayHandlers = {}) {
        this.scrollEl = scrollEl;
        this.handlers = handlers;
        this.layer = document.createElement("div");
        this.layer.className = "o_studio_overlay";
        this.hoverEl = child(this.layer, "div", "o_studio_hover");
        this.frameEl = child(this.layer, "div", "o_studio_selection");
        this.tagEl = child(this.frameEl, "span", "o_studio_tag");
        // The grip is picked up by the drag hook, which matches it by
        // class; nothing is listened to on it here.
        this.gripEl = child(this.frameEl, "button", "o_studio_grip");
        this.gripEl.type = "button";
        this.gripEl.title = String(_t("Drag to move"));
        this.gripEl.innerHTML = '<i class="oi oi-draggable"></i>';
        this.removeEl = child(this.frameEl, "button", "o_studio_remove");
        this.removeEl.type = "button";
        this.removeEl.title = String(_t("Remove from view"));
        this.removeEl.innerHTML = '<i class="fa fa-times"></i>';
        this.removeEl.addEventListener("click", (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            if (this.state.selection && this.handlers.onRemove) {
                this.handlers.onRemove(this.state.selection);
            }
        });
        // A sibling of the hover and the frame, so the zones can be
        // cleared in one go and drawn under nothing.
        this.zones = new ZoneLayer(scrollEl, this.layer);
        this.zoneLayer = this.zones.el;
        scrollEl.appendChild(this.layer);
        this.state = {
            hover: null,
            selection: null,
            nodes: {},
            tag: "",
            point: null,
            selectionPoint: null,
        };
        this.hide(this.hoverEl);
        this.hide(this.frameEl);
    }

    destroy(): void {
        this.layer.remove();
    }

    /**
     * What to draw. `hover` and `selection` are tokens; `point` the last
     * pointer position, for a node rendered more than once, and
     * `selectionPoint` where the selection was made -- the same point
     * when the caller keeps no other.
     */
    update({ hover, selection, nodes, tag, point, selectionPoint = null }: OverlayUpdate): void {
        Object.assign(this.state, { hover, selection, nodes, tag, point, selectionPoint });
        this.align();
    }

    /** Re-measure everything from the DOM as it is now. */
    align(): void {
        const { hover, selection, nodes, point, selectionPoint } = this.state;
        const hoverRect = hover && hover !== selection ? this.rectOf(hover, point) : null;
        if (hoverRect) {
            this.place(this.hoverEl, hoverRect);
        } else {
            this.hide(this.hoverEl);
        }
        // Captured once, rather than indexed again below: `nodes[selection]`
        // is a `NodeTable` (index-signature) read, so under
        // `noUncheckedIndexedAccess` a second `nodes[selection]` would not
        // re-narrow to the same result the type checker already forgot.
        // `selection && node` (not `node` alone) is what gates `rectOf`,
        // so `selection`, not just `node`, narrows to `Token` for that call.
        const node: StudioNode | undefined = selection ? nodes[selection] : undefined;
        const frameRect =
            selection && node ? this.rectOf(selection, selectionPoint || point) : null;
        if (frameRect && node) {
            this.place(this.frameEl, frameRect);
            // Written only on change: assigning textContent replaces the
            // text node even for an equal string, and a childList mutation
            // in here must not be what triggers the next re-alignment.
            const tag = this.state.tag || "";
            if (this.tagEl.textContent !== tag) {
                this.tagEl.textContent = tag;
            }
            this.frameEl.classList.toggle("o_studio_invisible_node", Boolean(node.hidden));
            // A container is moved by its grip; a leaf is dragged directly
            // and gets the cross instead. Neither for what stays put.
            this.gripEl.hidden = !(node.container && node.movable);
            this.removeEl.hidden = !node.removable;
        } else {
            this.hide(this.frameEl);
        }
    }

    /**
     * The content-relative rectangle of a node, or `null` when unrendered;
     * `point` picks the instance when the node is rendered more than once.
     */
    rectOf(token: Token, point: Point | null = this.state.point): PlainRect | null {
        const rect = outlineRect(token, this.scrollEl, this.state.nodes, point);
        return rect ? this.toContent(rect) : null;
    }

    /** Viewport coordinates to coordinates inside the scroll container. */
    toContent(rect: PlainRect): PlainRect {
        return toContent(rect, this.scrollEl);
    }

    // -- drop zones ---------------------------------------------------------

    /** The zones of a drag, drawn in this layer; see `ZoneLayer.setZones`. */
    setZones(
        zones: Zone[],
        containers: ZoneContainer[] = [],
        template: PlainRect | null = null,
    ): Element[] {
        return this.zones.setZones(zones, containers, template);
    }

    clearZones(): void {
        this.zones.clearZones();
    }

    place(el: HTMLElement, rect: PlainRect): void {
        place(el, rect);
    }

    hide(el: HTMLElement): void {
        el.hidden = true;
    }

    /** Every rendered instance of a token, for callers that need them all. */
    instancesOf(token: Token): Element[] {
        return elementsFor(token, this.scrollEl, this.state.nodes);
    }
}

/**
 * The layer the drop zones of a drag are drawn in: a plain element in a
 * scroll container, positioned in that container's content coordinates
 * so the zones travel with what they were laid out on. The canvas has
 * one inside its overlay; the outline has one of its own in its list,
 * and the drag matches the hook against both.
 */
export class ZoneLayer {
    scrollEl: HTMLElement;
    el: HTMLDivElement;

    /** `scrollEl` is the scroll container the zones are positioned in;
     * `parent` is where the layer element goes, the scroll container
     * itself by default. */
    constructor(scrollEl: HTMLElement, parent: Element = scrollEl) {
        this.scrollEl = scrollEl;
        this.el = child(parent, "div", "o_studio_zones");
    }

    destroy(): void {
        this.el.remove();
    }

    /**
     * Draw the zones of a drag, and the outline of every container that
     * would take the drop. Returns the zone elements, in the order given,
     * for the drag hook to match against; each carries the zone's
     * identity in its dataset, which is also what a tour points at.
     *
     * `template` is the box of the one kanban card the zones were laid
     * out on, drawn dashed so the user can see which card stands for the
     * template: the drop edits the template, and every card follows.
     */
    setZones(
        zones: Zone[],
        containers: ZoneContainer[] = [],
        template: PlainRect | null = null,
    ): Element[] {
        this.clearZones();
        if (template) {
            const el = child(this.el, "div", "o_studio_dz_template");
            place(el, this.toContent(template));
        }
        for (const { rect } of containers) {
            const el = child(this.el, "div", "o_studio_dz_container");
            place(el, this.toContent(rect));
        }
        return zones.map((zone) => {
            const el = child(this.el, "div", "o_studio_dropzone");
            // Bracket notation throughout: `dataset` is a `DOMStringMap`,
            // a pure index-signature type, and `noPropertyAccessFromIndexSignature`
            // rejects the dot form for it the same way `identity.ts`'s own
            // `heading.dataset["name"]` already does.
            el.dataset["token"] = zone.token;
            el.dataset["name"] = zone.name || "";
            el.dataset["kind"] = zone.kind;
            el.dataset["position"] = zone.position;
            el.dataset["caption"] = zone.caption;
            el.dataset["container"] = zone.container;
            el.dataset["containerKind"] = zone.containerKind;
            el.dataset["axis"] = zone.axis;
            el.dataset["layer"] = zone.layer || "canvas";
            if (zone.edge) {
                el.dataset["edge"] = zone.edge;
            }
            el.classList.add(
                zone.position === "inside" ? "o_studio_dz_inside" : `o_studio_dz_${zone.axis}`,
            );
            // A bar drawn on a line inside the zone -- the boundary of two
            // rows of the outline -- rather than at its top.
            if (zone.line !== null && zone.line !== undefined) {
                el.style.setProperty("--o-studio-dz-line", `${zone.line - zone.rect.top}px`);
            }
            place(el, this.toContent(zone.rect));
            return el;
        });
    }

    clearZones(): void {
        this.el.replaceChildren();
    }

    toContent(rect: PlainRect): PlainRect {
        return toContent(rect, this.scrollEl);
    }
}

function place(el: HTMLElement, rect: PlainRect): void {
    el.hidden = false;
    el.style.top = `${rect.top}px`;
    el.style.left = `${rect.left}px`;
    el.style.width = `${rect.width}px`;
    el.style.height = `${rect.height}px`;
}

function child<K extends keyof HTMLElementTagNameMap>(
    parent: Element,
    tag: K,
    className: string,
): HTMLElementTagNameMap[K] {
    const el = document.createElement(tag);
    el.className = className;
    parent.appendChild(el);
    return el;
}
