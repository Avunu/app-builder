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

export class Overlay {
    /**
     * @param {HTMLElement} scrollEl the canvas's scroll container
     * @param {Object} handlers `onRemove(token)`
     */
    constructor(scrollEl, handlers = {}) {
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
        this.gripEl.title = _t("Drag to move");
        this.gripEl.innerHTML = '<i class="oi oi-draggable"></i>';
        this.removeEl = child(this.frameEl, "button", "o_studio_remove");
        this.removeEl.type = "button";
        this.removeEl.title = _t("Remove from view");
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

    destroy() {
        this.layer.remove();
    }

    /**
     * What to draw. `hover` and `selection` are tokens; `point` the last
     * pointer position, for a node rendered more than once, and
     * `selectionPoint` where the selection was made -- the same point
     * when the caller keeps no other.
     */
    update({ hover, selection, nodes, tag, point, selectionPoint = null }) {
        Object.assign(this.state, { hover, selection, nodes, tag, point, selectionPoint });
        this.align();
    }

    /** Re-measure everything from the DOM as it is now. */
    align() {
        const { hover, selection, nodes, point, selectionPoint } = this.state;
        const hoverRect = hover && hover !== selection ? this.rectOf(hover, point) : null;
        if (hoverRect) {
            this.place(this.hoverEl, hoverRect);
        } else {
            this.hide(this.hoverEl);
        }
        const node = selection && nodes[selection];
        const frameRect = node ? this.rectOf(selection, selectionPoint || point) : null;
        if (frameRect) {
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
    rectOf(token, point = this.state.point) {
        const rect = outlineRect(token, this.scrollEl, this.state.nodes, point);
        return rect ? this.toContent(rect) : null;
    }

    /** Viewport coordinates to coordinates inside the scroll container. */
    toContent(rect) {
        return toContent(rect, this.scrollEl);
    }

    // -- drop zones ---------------------------------------------------------

    /** The zones of a drag, drawn in this layer; see `ZoneLayer.setZones`. */
    setZones(zones, containers = [], template = null) {
        return this.zones.setZones(zones, containers, template);
    }

    clearZones() {
        this.zones.clearZones();
    }

    place(el, rect) {
        place(el, rect);
    }

    hide(el) {
        el.hidden = true;
    }

    /** Every rendered instance of a token, for callers that need them all. */
    instancesOf(token) {
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
    /**
     * @param {HTMLElement} scrollEl the scroll container the zones are
     *   positioned in
     * @param {HTMLElement} [parent] where the layer element goes; the
     *   scroll container itself by default
     */
    constructor(scrollEl, parent = scrollEl) {
        this.scrollEl = scrollEl;
        this.el = child(parent, "div", "o_studio_zones");
    }

    destroy() {
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
    setZones(zones, containers = [], template = null) {
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
            el.dataset.token = zone.token;
            el.dataset.name = zone.name || "";
            el.dataset.kind = zone.kind;
            el.dataset.position = zone.position;
            el.dataset.caption = zone.caption;
            el.dataset.container = zone.container;
            el.dataset.containerKind = zone.containerKind;
            el.dataset.axis = zone.axis;
            el.dataset.layer = zone.layer || "canvas";
            if (zone.edge) {
                el.dataset.edge = zone.edge;
            }
            el.classList.add(
                zone.position === "inside" ? "o_studio_dz_inside" : `o_studio_dz_${zone.axis}`
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

    clearZones() {
        this.el.replaceChildren();
    }

    toContent(rect) {
        return toContent(rect, this.scrollEl);
    }
}

function place(el, rect) {
    el.hidden = false;
    el.style.top = `${rect.top}px`;
    el.style.left = `${rect.left}px`;
    el.style.width = `${rect.width}px`;
    el.style.height = `${rect.height}px`;
}

function child(parent, tag, className) {
    const el = document.createElement(tag);
    el.className = className;
    parent.appendChild(el);
    return el;
}
