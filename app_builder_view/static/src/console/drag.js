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
  tabsOf
} from "./geometry";
import {
  cardAt,
  cardOf,
  cardsOf,
  centreOf,
  columnToken,
  firstVisibleCard,
  ownToken
} from "./identity";
import { outlineZones } from "./outline_zones";
import { TYPE_ICONS } from "./pending_widget";
import { buildZones, labelOf, payloadTag } from "./zones";
const DRAG_SOURCES = [
  ".o_studio_tile",
  "[class*='o_studio_n_']",
  "th[data-name]",
  ".o_studio_grip",
  ".o_studio_outline_row"
].join(", ");
const DRAG_IGNORE = ".o_resize, .o_studio_outline_caret, .o_studio_outline_divider";
const TAB_DWELL_MS = 250;
const HIT = 8;
const DROP_SLACK = HIT;
const MODIFIER_KEYS = ["Alt", "Control", "Meta", "Shift"];
const EDGE = 30;
const EDGE_SPEED = 10;
const ICONS = TYPE_ICONS;
const dragAndDrop = useDragAndDrop;
function makeCanvasDrag({
  rootEl,
  scrollEl,
  overlay,
  model,
  point = () => null,
  pointAt = () => {
  }
}) {
  return new CanvasDrag({ rootEl, scrollEl, overlay, model, point, pointAt });
}
class CanvasDrag {
  rootEl;
  scrollEl;
  overlay;
  model;
  point;
  pointAt;
  source;
  payload;
  tag;
  moving;
  /** The kanban card the zones are laid out on; `null` off a kanban. */
  card;
  zones;
  zoneOf;
  tabs;
  dwell;
  /** The outline's provider (`sidebar/outline.js`), taken from the
   * model when a drag starts and held until it ends; `null` when
   * there is no outline to drop on. */
  outline;
  outlineObserver;
  rowDwell;
  /** The scroll container being edge-scrolled, the canvas or the
   * outline's list, for as long as the pointer stays at its edge. */
  edgeEl;
  onOutlineScroll;
  pointer;
  cancelled;
  dragging;
  hit;
  chip;
  rebuildFrame;
  edgeFrame;
  observer;
  onKeyDown;
  onPointerCancel;
  onPointerDown;
  hook;
  constructor({ rootEl, scrollEl, overlay, model, point, pointAt = () => {
  } }) {
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
    this.zoneOf = /* @__PURE__ */ new Map();
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
      ...compat.dragExtraParams()
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
      const node2 = this.model.selectedNode;
      return Boolean(node2 && node2.container && node2.movable);
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
      return el.dataset["token"] || null;
    }
    if (el.matches("th[data-name]")) {
      return columnToken(el.dataset["name"] || "", this.nodes);
    }
    return ownToken(el);
  }
  /** What a source element means as a drop payload, or `null`. */
  payloadFor(el) {
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
          label
        };
      }
      return null;
    }
    const token = el.classList.contains("o_studio_grip") ? this.model.selection && this.model.selection.token : this.tokenOfSource(el);
    if (!token) {
      return null;
    }
    const node = this.nodes[token];
    if (!node) {
      return null;
    }
    if (node.kind === "pending") {
      const name = node.pending && node.pending.name || node.name;
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
  iconFor(el) {
    const token = this.payload && this.payload.kind === "move" ? this.payload.token : null;
    const node = token ? this.nodes[token] : null;
    const icon = node && node.field ? ICONS[node.field.type] : void 0;
    if (icon) {
      return icon;
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
    const payload = this.payload;
    if (!payload) {
      this.cancelled = true;
      return;
    }
    this.tag = payloadTag(payload, this.nodes);
    this.moving = ["move", "move_pending"].includes(payload.kind) ? payload.token ?? null : null;
    document.body.classList.add("o_studio_dragging");
    this.rootEl.classList.add("o_studio_dragging");
    this.model.beginDrag(payload.label || "");
    this.card = this.startingCard();
    const outline = this.model.outlineDrag;
    this.outline = outline && outline.el && outline.el.isConnected ? outline : null;
    this.buildZones();
    this.observer = this.watch(this.scrollEl, ".o_studio_overlay");
    const activeOutline = this.outline;
    if (activeOutline) {
      this.outlineObserver = this.watch(activeOutline.el, ".o_studio_zones");
      activeOutline.el.addEventListener("scroll", this.onOutlineScroll);
    }
  }
  /**
   * Lay the zones out again whenever `el` changes under the drag, its
   * own zone layer -- `layerSelector` -- excepted.
   */
  watch(el, layerSelector) {
    const observer = new MutationObserver((records) => {
      if (records.some(
        (r) => !(r.target instanceof Element) || !r.target.closest(layerSelector)
      )) {
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
  buildZones() {
    const canvas = this.buildCanvasZones();
    const outline = this.outline ? this.buildOutlineZones(this.outline) : [];
    this.zones = [...canvas, ...outline];
    this.tabs = tabsOf(this.scrollEl);
  }
  /** The canvas's zones, drawn in its overlay; the elements, in order. */
  buildCanvasZones() {
    const root = this.scrollEl;
    const nodes = this.nodes;
    if (this.card && !this.card.isConnected) {
      this.card = cardAt(root, this.pointer) || firstVisibleCard(root, root);
    }
    const point = this.card ? centreOf(this.card) : this.point();
    const contentOf = (token) => contentRect(token, root, nodes, point);
    const childrenOf = (token) => childEntries(token, root, nodes, contentElement(token, root, nodes, point));
    const isActive = (token) => isActivePage(token, root, nodes);
    const flow = (token) => this.card ? flowOf(contentElement(token, root, nodes, point)) : null;
    const { zones, containers } = buildZones({
      nodes,
      tag: this.tag,
      moving: this.moving,
      contentOf,
      childrenOf,
      isActive,
      flowOf: flow
    });
    const template = this.card ? plain(this.card.getBoundingClientRect()) : null;
    const els = this.overlay.setZones(zones, containers, template);
    els.forEach((el, index) => {
      this.zoneOf.set(el, zones[index]);
    });
    return els;
  }
  /**
   * The outline's zones, drawn in its own layer over the rows that are
   * on screen -- the list clips what it scrolls away, and the hook
   * measures boxes that clipping does not shrink.
   */
  buildOutlineZones(outline) {
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
      const token = el.dataset["token"];
      if (!token) {
        continue;
      }
      rows.push({
        token,
        depth: Number(el.dataset["depth"]) || 0,
        rect,
        collapsed: el.classList.contains("o_studio_outline_collapsed")
      });
    }
    const { zones, containers } = outlineZones({
      nodes: this.nodes,
      tag: this.tag,
      moving: this.moving,
      rows,
      indentOf: outline.indentOf,
      box
    });
    const els = outline.layer.setZones(zones, containers);
    els.forEach((el, index) => {
      this.zoneOf.set(el, zones[index]);
    });
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
    const outline = this.outline;
    if (!outline) {
      return;
    }
    const row = this.rowAt({ x, y });
    const token = row ? row.dataset["token"] : void 0;
    const folds = Boolean(
      token && row && row.classList.contains("o_studio_outline_collapsed") && outline.isCollapsed(token)
    );
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
      }, TAB_DWELL_MS)
    };
  }
  /** The outline row under a viewport point, or `null`. */
  rowAt(point) {
    const outline = this.outline;
    if (!outline || !outline.el.isConnected) {
      return null;
    }
    if (!contains(plain(outline.el.getBoundingClientRect()), point)) {
      return null;
    }
    return outline.rows().find((row) => contains(plain(row.getBoundingClientRect()), point)) || null;
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
    const outline = this.outline;
    const candidates = [this.scrollEl];
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
    const edgeEl = el;
    this.edgeEl = edgeEl;
    if (this.edgeFrame) {
      return;
    }
    const tick = () => {
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
    this.setCaption(String(_t("switching to %s…", (tab.textContent || "").trim())));
    this.dwell = {
      tab,
      timer: window.setTimeout(() => {
        this.dwell = null;
        if (!this.dragging || this.tabAt(this.pointer) !== tab) {
          return;
        }
        tab.click();
        this.setCaption(this.captionOfCurrent());
        this.onCanvasChanged();
      }, TAB_DWELL_MS)
    };
  }
  /** The inactive tab under a viewport point, or `null`. */
  tabAt(point) {
    return this.tabs.find(
      (tab) => tab.isConnected && !tab.classList.contains("active") && contains(plain(tab.getBoundingClientRect()), point)
    ) || null;
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
      const found = this.zones.find(
        (candidate) => samePlace(this.zoneOf.get(candidate), zone)
      );
      if (!found) {
        return null;
      }
      el = found;
    }
    const rect = el.getBoundingClientRect();
    const box = {
      top: rect.top,
      left: rect.left,
      width: rect.width,
      height: rect.height
    };
    return contains(box, pointer, DROP_SLACK) ? this.zoneOf.get(el) ?? null : null;
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
    this.zoneOf = /* @__PURE__ */ new Map();
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
      sent["token"] = token;
    }
    const result = await this.model.drop(zone.token, zone.position, sent);
    if (result && result.created_field) {
      focusLabelRow(this.rootEl);
    }
  }
}
function samePlace(a, b) {
  if (!a || !b) {
    return false;
  }
  return (a.layer || "canvas") === (b.layer || "canvas") && a.container === b.container && a.token === b.token && a.position === b.position;
}
function focusLabelRow(rootEl, { tries = 40, every = 50 } = {}) {
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
export {
  CanvasDrag,
  DRAG_SOURCES,
  TAB_DWELL_MS,
  focusLabelRow,
  makeCanvasDrag
};
