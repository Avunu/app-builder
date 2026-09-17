import { _t } from "@web/core/l10n/translation";
import { elementsFor } from "./identity";
import { outlineRect, toContent } from "./geometry";
class Overlay {
  scrollEl;
  handlers;
  layer;
  hoverEl;
  frameEl;
  tagEl;
  gripEl;
  removeEl;
  zones;
  zoneLayer;
  state;
  /** `scrollEl` is the canvas's scroll container; `handlers` is
   * `{onRemove(token)}`. */
  constructor(scrollEl, handlers = {}) {
    this.scrollEl = scrollEl;
    this.handlers = handlers;
    this.layer = document.createElement("div");
    this.layer.className = "o_studio_overlay";
    this.hoverEl = child(this.layer, "div", "o_studio_hover");
    this.frameEl = child(this.layer, "div", "o_studio_selection");
    this.tagEl = child(this.frameEl, "span", "o_studio_tag");
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
    this.zones = new ZoneLayer(scrollEl, this.layer);
    this.zoneLayer = this.zones.el;
    scrollEl.appendChild(this.layer);
    this.state = {
      hover: null,
      selection: null,
      nodes: {},
      tag: "",
      point: null,
      selectionPoint: null
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
    const node = selection ? nodes[selection] : void 0;
    const frameRect = selection && node ? this.rectOf(selection, selectionPoint || point) : null;
    if (frameRect && node) {
      this.place(this.frameEl, frameRect);
      const tag = this.state.tag || "";
      if (this.tagEl.textContent !== tag) {
        this.tagEl.textContent = tag;
      }
      this.frameEl.classList.toggle("o_studio_invisible_node", Boolean(node.hidden));
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
class ZoneLayer {
  scrollEl;
  el;
  /** `scrollEl` is the scroll container the zones are positioned in;
   * `parent` is where the layer element goes, the scroll container
   * itself by default. */
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
        zone.position === "inside" ? "o_studio_dz_inside" : `o_studio_dz_${zone.axis}`
      );
      if (zone.line !== null && zone.line !== void 0) {
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
export {
  Overlay,
  ZoneLayer
};
