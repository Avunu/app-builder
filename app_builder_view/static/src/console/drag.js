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
import { outlineZones } from "./outline_zones";
import { TYPE_ICONS } from "./pending_widget";
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
        // The outline's provider (`sidebar/outline.js`), taken from the
        // model when a drag starts and held until it ends; `null` when
        // there is no outline to drop on.
        this.outline = null;
        this.outlineObserver = null;
        this.rowDwell = null;
        // The scroll container being edge-scrolled, the canvas or the
        // outline's list, for as long as the pointer stays at its edge.
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
     * so that a press on it is a click on what it holds. A row of the
     * outline when its node is movable, container or not: a row holds
     * nothing a press could mean instead.
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
        if (el.classList.contains("o_studio_outline_row")) {
            return Boolean(node && node.movable);
        }
        return Boolean(node && node.movable && !node.container);
    }

    /** The token a source element stands for: its own, its column's, its row's. */
    tokenOfSource(el) {
        if (el.classList.contains("o_studio_outline_row")) {
            return el.dataset.token || null;
        }
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
        // The outline, as it is now: its provider is taken once, since a
        // pane cannot change under a drag -- that takes a click, which
        // ends it -- and a half-registered one is not to be trusted.
        const outline = this.model.outlineDrag;
        this.outline = outline && outline.el && outline.el.isConnected ? outline : null;
        this.buildZones();
        // The canvas re-renders under the drag when a tab switches; the
        // zones follow. Watched from here, for the drag's own duration,
        // so the drag does not depend on who else is watching the canvas.
        // The overlay's own changes -- the zones being drawn -- are not
        // what is watched for.
        this.observer = this.watch(this.scrollEl, ".o_studio_overlay");
        if (this.outline) {
            // The outline re-renders when a row unfolds, and its rows move
            // when its list scrolls: either way the zones over it are laid
            // out again.
            this.outlineObserver = this.watch(this.outline.el, ".o_studio_zones");
            this.outline.el.addEventListener("scroll", this.onOutlineScroll);
        }
    }

    /**
     * Lay the zones out again whenever `el` changes under the drag, its
     * own zone layer -- `layerSelector` -- excepted.
     */
    watch(el, layerSelector) {
        const observer = new MutationObserver((records) => {
            if (records.some((r) => !r.target.closest || !r.target.closest(layerSelector))) {
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
        const canvas = this.buildCanvasZones();
        const outline = this.outline ? this.buildOutlineZones() : [];
        // Kept across rebuilds, not replaced: the hook may still hold a
        // zone from before, and what it stood for has to be answerable.
        this.zones = [...canvas, ...outline];
        this.tabs = tabsOf(this.scrollEl);
    }

    /** The canvas's zones, drawn in its overlay; the elements, in order. */
    buildCanvasZones() {
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
        const els = this.overlay.setZones(zones, containers, template);
        els.forEach((el, index) => this.zoneOf.set(el, zones[index]));
        return els;
    }

    /**
     * The outline's zones, drawn in its own layer over the rows that are
     * on screen -- the list clips what it scrolls away, and the hook
     * measures boxes that clipping does not shrink.
     */
    buildOutlineZones() {
        const outline = this.outline;
        if (!outline.el.isConnected) {
            return [];
        }
        const box = plain(outline.el.getBoundingClientRect());
        const rows = [];
        for (const el of outline.rows()) {
            const rect = plain(el.getBoundingClientRect());
            if (rect.top + rect.height <= box.top || rect.top >= box.top + box.height) {
                continue;
            }
            rows.push({
                token: el.dataset.token,
                depth: Number(el.dataset.depth) || 0,
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
        els.forEach((el, index) => this.zoneOf.set(el, zones[index]));
        return els;
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
                // What is under a still pointer may have changed -- a row
                // unfolded, the list scrolled -- and only a pointer event
                // has the hook look again.
                this.nudge();
            }
        });
    }

    onDrag({ x, y }) {
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
    watchRow(x, y) {
        if (!this.outline) {
            return;
        }
        const row = this.rowAt({ x, y });
        const token = row && row.dataset.token;
        const folds = Boolean(
            token &&
                row.classList.contains("o_studio_outline_collapsed") &&
                this.outline.isCollapsed(token)
        );
        if (!folds) {
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
                if (this.dragging && still && still.dataset.token === token) {
                    this.outline.expand(token);
                    this.onCanvasChanged();
                }
            }, TAB_DWELL_MS),
        };
    }

    /** The outline row under a viewport point, or `null`. */
    rowAt(point) {
        if (!this.outline || !this.outline.el.isConnected) {
            return null;
        }
        if (!contains(plain(this.outline.el.getBoundingClientRect()), point)) {
            return null;
        }
        return (
            this.outline.rows().find((row) => contains(plain(row.getBoundingClientRect()), point)) ||
            null
        );
    }

    clearRowDwell() {
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
     * Scroll the canvas -- or the outline's list -- while the pointer is
     * over it and near its top or bottom, and keep scrolling until it
     * moves away: the canvas's zones travel with its content, so nothing
     * has to be laid out again for it, and the outline's are laid out
     * again on its scroll. What is under the pointer changes either way,
     * and only a pointer event has the hook look again.
     */
    watchEdge() {
        const { x, y } = this.pointer;
        const candidates = [this.scrollEl, this.outline && this.outline.el].filter(Boolean);
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
        this.edgeEl = el;
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
            if (zone.layer !== "outline") {
                // A point in the sidebar says nothing about which card the
                // frame should be drawn in.
                this.pointAt({ x, y });
            }
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
        if (this.outline) {
            this.outline.el.removeEventListener("scroll", this.onOutlineScroll);
            this.outline.layer.clearZones();
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

/**
 * Whether two zone descriptors name the same place, across a rebuild --
 * in the same layer: the canvas and the outline both offer "after City
 * in the group", and a zone the outline held is found again in the
 * outline, not under the pointer's old spot on the canvas.
 */
function samePlace(a, b) {
    return (
        Boolean(a && b) &&
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
