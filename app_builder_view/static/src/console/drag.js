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
 * the view, a list heading or the grip of a selected container; where it
 * can land is the set of zones `zones.js` lays out from the node table
 * the moment the drag starts. Nothing is re-rendered until it ends.
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
import {
    cardAt,
    cardOf,
    cardsOf,
    centreOf,
    columnToken,
    firstVisibleCard,
    ownToken,
} from "./identity";
import { TYPE_ICONS } from "./pending_widget";
import { buildZones, labelOf, payloadTag } from "./zones";

/** Elements a drag can start from, all inside the console root. */
export const DRAG_SOURCES = [
    ".o_studio_tile",
    "[class*='o_studio_n_']",
    "th[data-name]",
    ".o_studio_grip",
].join(", ");

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
 * @param {Object} params
 * @param {HTMLElement} params.rootEl the console element, holding both
 *   the sidebar and the canvas
 * @param {HTMLElement} params.scrollEl the canvas's scroll container
 * @param {Overlay} params.overlay the canvas's overlay
 * @param {ConsoleModel} params.model the console model
 * @param {Function} params.point `() => {x, y}|null`, the last pointer
 *   position the canvas saw, for a node rendered more than once
 * @param {Function} [params.pointAt] `({x, y}) => void`, told where a
 *   drop was made, so the canvas can keep pointing at that card
 */
export function makeCanvasDrag({
    rootEl,
    scrollEl,
    overlay,
    model,
    point = () => null,
    pointAt = () => {},
}) {
    return new CanvasDrag({ rootEl, scrollEl, overlay, model, point, pointAt });
}

export class CanvasDrag {
    constructor({ rootEl, scrollEl, overlay, model, point, pointAt = () => {} }) {
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
        // The kanban card the zones are laid out on; `null` off a kanban.
        this.card = null;
        this.zones = [];
        this.zoneOf = new Map();
        this.tabs = [];
        this.dwell = null;
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
        this.onKeyDown = (ev) => {
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

        this.hook = useDragAndDrop({
            ref: compat.dragRef({ el: rootEl }),
            elements: DRAG_SOURCES,
            ignore: ".o_resize",
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

    destroy() {
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

    get nodes() {
        return this.model.nodes;
    }

    /**
     * Whether `el` -- something matching `DRAG_SOURCES` -- starts a drag.
     *
     * A tile, unless disabled. A heading, when its column is movable. The
     * grip, when the selection is a movable container. A node of the view
     * when it is movable and a leaf: a container is picked up by its grip,
     * so that a press on it is a click on what it holds.
     */
    isDraggable(el) {
        if (!el || !this.model.canWrite) {
            return false;
        }
        if (el.classList.contains("o_studio_tile")) {
            return el.classList.contains("o_studio_draggable") && !el.disabled;
        }
        if (el.classList.contains("o_studio_grip")) {
            const node = this.model.selectedNode;
            return Boolean(node && node.container && node.movable);
        }
        const token = this.tokenOfSource(el);
        const node = token ? this.nodes[token] : null;
        return Boolean(node && node.movable && !node.container);
    }

    /** The token a canvas element stands for: its own, or its column's. */
    tokenOfSource(el) {
        if (el.matches("th[data-name]")) {
            return columnToken(el.dataset.name, this.nodes);
        }
        return ownToken(el);
    }

    /** What a source element means as a drop payload, or `null`. */
    payloadFor(el) {
        if (el.classList.contains("o_studio_tile")) {
            const kind = el.dataset.kind;
            const key = el.dataset.key || el.dataset.name;
            const label = el.dataset.label || el.textContent.trim();
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
        const node = token ? this.nodes[token] : null;
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
    makeHelper({ element, helperOffset }) {
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
        label.textContent = this.payload ? this.payload.label : "";
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
    iconFor(el) {
        const token = this.payload && this.payload.kind === "move" ? this.payload.token : null;
        const node = token ? this.nodes[token] : null;
        if (node && node.field && TYPE_ICONS[node.field.type]) {
            return TYPE_ICONS[node.field.type];
        }
        const own = el.classList.contains("o_studio_tile") ? el.querySelector("i") : null;
        if (own && own.className) {
            return own.className;
        }
        return "fa fa-arrows";
    }

    setCaption(text) {
        if (this.chip && this.chip.caption.textContent !== text) {
            this.chip.caption.textContent = text;
            this.chip.el.classList.toggle("o_studio_chip_has_caption", Boolean(text));
        }
        this.model.setDragCaption(text);
    }

    // -- the drag -----------------------------------------------------------

    onDragStart() {
        this.dragging = true;
        this.cancelled = false;
        if (!this.payload) {
            this.cancelled = true;
            return;
        }
        this.tag = payloadTag(this.payload, this.nodes);
        this.moving = ["move", "move_pending"].includes(this.payload.kind)
            ? this.payload.token
            : null;
        document.body.classList.add("o_studio_dragging");
        this.rootEl.classList.add("o_studio_dragging");
        this.model.beginDrag(this.payload.label);
        this.card = this.startingCard();
        this.buildZones();
        // The canvas re-renders under the drag when a tab switches; the
        // zones follow. Watched from here, for the drag's own duration,
        // so the drag does not depend on who else is watching the canvas.
        // The overlay's own changes -- the zones being drawn -- are not
        // what is watched for.
        this.observer = new MutationObserver((records) => {
            if (records.some((r) => !r.target.closest || !r.target.closest(".o_studio_overlay"))) {
                this.onCanvasChanged();
            }
        });
        this.observer.observe(this.scrollEl, { childList: true, subtree: true });
    }

    /**
     * The kanban card a drag starts on, or `null` off a kanban: the card
     * the dragged node is in, or -- for a tile, which is in no card --
     * the first one the user can see. Only on a kanban canvas: a form
     * with an x2many kanban in it has cards too, and none of them is a
     * template of this view.
     */
    startingCard() {
        if (this.model.viewType !== "kanban" || !cardsOf(this.scrollEl).length) {
            return null;
        }
        const own = this.source && this.scrollEl.contains(this.source) ? cardOf(this.source) : null;
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
    buildZones() {
        const root = this.scrollEl;
        const nodes = this.nodes;
        if (this.card && !this.card.isConnected) {
            // The board re-rendered under the drag: the same place, or
            // the first card there is.
            this.card = cardAt(root, this.pointer) || firstVisibleCard(root, root);
        }
        const point = this.card ? centreOf(this.card) : this.point();
        const contentOf = (token) => contentRect(token, root, nodes, point);
        const childrenOf = (token) =>
            childEntries(token, root, nodes, contentElement(token, root, nodes, point));
        const isActive = (token) => isActivePage(token, root, nodes);
        const flow = (token) =>
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
        this.zones = this.overlay.setZones(zones, containers, template);
        // Kept across rebuilds, not replaced: the hook may still hold a
        // zone from before, and what it stood for has to be answerable.
        this.zones.forEach((el, index) => this.zoneOf.set(el, zones[index]));
        this.tabs = tabsOf(root);
    }

    /**
     * The canvas has re-rendered under the drag -- a tab switched. The
     * zones are laid out again on the next frame, once, however many
     * mutations the switch produced.
     */
    onCanvasChanged() {
        if (!this.dragging || this.rebuildFrame) {
            return;
        }
        this.rebuildFrame = window.requestAnimationFrame(() => {
            this.rebuildFrame = null;
            if (this.dragging) {
                this.buildZones();
            }
        });
    }

    onDrag({ x, y }) {
        this.pointer = { x, y };
        if (!this.dragging || this.cancelled) {
            return;
        }
        this.watchTab(x, y);
        this.watchCard(x, y);
        this.watchEdge();
    }

    /**
     * The pointer has crossed into another card of the kanban: the zones
     * are laid out again on that one, on the next frame -- the same
     * throttle as a re-render, and for the same reason.
     */
    watchCard(x, y) {
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
     * Scroll the canvas while the pointer is over it and near its top or
     * bottom, and keep scrolling until it moves away: the zones travel
     * with the content, so nothing has to be laid out again for it. What
     * is under the pointer changes, though, and only a pointer event has
     * the hook look again.
     */
    watchEdge() {
        const el = this.scrollEl;
        const rect = el.getBoundingClientRect();
        const { x, y } = this.pointer;
        let step = 0;
        if (x >= rect.left && x <= rect.right) {
            if (y >= rect.top && y < rect.top + EDGE) {
                step = -EDGE_SPEED * (1 - (y - rect.top) / EDGE);
            } else if (y <= rect.bottom && y > rect.bottom - EDGE) {
                step = EDGE_SPEED * (1 - (rect.bottom - y) / EDGE);
            }
        }
        if (!step) {
            this.stopEdge();
            return;
        }
        if (this.edgeFrame) {
            return;
        }
        const tick = () => {
            if (!this.dragging) {
                this.edgeFrame = null;
                return;
            }
            el.scrollBy({ top: step });
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
    nudge() {
        const { x, y } = this.pointer;
        const move = { clientX: x, clientY: y, bubbles: true, cancelable: true };
        window.dispatchEvent(new PointerEvent("pointermove", move));
    }

    stopEdge() {
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
    watchTab(x, y) {
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
        this.setCaption(String(_t("switching to %s…", tab.textContent.trim())));
        this.dwell = {
            tab,
            timer: window.setTimeout(() => {
                this.dwell = null;
                if (!this.dragging || this.tabAt(this.pointer) !== tab) {
                    return;
                }
                tab.click();
                // The page is switching: the chip says so no longer, and
                // says what the next zone says once the pointer is on one.
                this.setCaption(this.captionOfCurrent());
                this.onCanvasChanged();
            }, TAB_DWELL_MS),
        };
    }

    /** The inactive tab under a viewport point, or `null`. */
    tabAt(point) {
        return (
            this.tabs.find(
                (tab) =>
                    tab.isConnected &&
                    !tab.classList.contains("active") &&
                    contains(plain(tab.getBoundingClientRect()), point)
            ) || null
        );
    }

    clearDwell() {
        if (this.dwell) {
            window.clearTimeout(this.dwell.timer);
            this.dwell = null;
        }
    }

    captionOfCurrent() {
        const active = this.zones.find((el) => el.classList.contains("o_studio_dz_active"));
        const zone = active && this.zoneOf.get(active);
        return zone ? zone.caption : "";
    }

    onZoneOver(dropzone) {
        const zone = this.zoneOf.get(dropzone.el);
        dropzone.el.classList.add("o_studio_dz_active");
        if (!this.dwell) {
            this.setCaption(zone ? zone.caption : "");
        }
    }

    onZoneOut(dropzone) {
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
    onDragEnd({ dropzone, x, y }) {
        const zone = this.zoneToDrop(dropzone, { x, y });
        const payload = this.payload;
        this.teardown();
        if (zone && payload) {
            this.pointAt({ x, y });
            this.drop(zone, payload);
        }
    }

    /**
     * The zone a drop lands in, or `null`: not after a cancel, and not one
     * the pointer is no longer over. The hook may hold a zone from before
     * a rebuild -- the page switched under it -- in which case the same
     * place in the zones as they are now is what counts.
     */
    zoneToDrop(dropzone, pointer) {
        if (this.cancelled || !dropzone || !dropzone.el) {
            return null;
        }
        const zone = this.zoneOf.get(dropzone.el);
        if (!zone) {
            return null;
        }
        let el = dropzone.el;
        if (!el.isConnected || !this.zones.includes(el)) {
            el = this.zones.find((candidate) => samePlace(this.zoneOf.get(candidate), zone));
            if (!el) {
                return null;
            }
        }
        const rect = el.getBoundingClientRect();
        const box = { top: rect.top, left: rect.left, width: rect.width, height: rect.height };
        return contains(box, pointer, DROP_SLACK) ? this.zoneOf.get(el) : null;
    }

    teardown() {
        const wasDragging = this.dragging;
        this.dragging = false;
        this.clearDwell();
        this.stopEdge();
        if (this.observer) {
            this.observer.disconnect();
            this.observer = null;
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

    async drop(zone, payload) {
        const { label, token, ...sent } = payload;
        if (sent.kind === "move") {
            sent.token = token;
        }
        const result = await this.model.drop(zone.token, zone.position, sent);
        if (result && result.created_field) {
            focusLabelRow(this.rootEl);
        }
    }
}

/** Whether two zone descriptors name the same place, across a rebuild. */
function samePlace(a, b) {
    return (
        Boolean(a && b) &&
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
export function focusLabelRow(rootEl, { tries = 40, every = 50 } = {}) {
    const attempt = (left) => {
        const input = rootEl.querySelector(
            ".o_studio_properties .o_studio_row[data-row='string'] input"
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
