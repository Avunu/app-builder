import {
  Component,
  onMounted,
  onPatched,
  onWillPatch,
  onWillUnmount,
  useEffect,
  useRef,
  useState
} from "@odoo/owl";
import { useThrottleForAnimation } from "@web/core/utils/timing";
import { View } from "@web/views/view";
import { canvasJsClass } from "./canvas_views";
import * as compat from "./compat";
import { makeCanvasDrag } from "./drag";
import { instanceOf } from "./geometry";
import { describeTab, findTab, ownToken, tabFor, tokenOf } from "./identity";
import { Overlay } from "./overlay";
class StudioCanvas extends Component {
  static template = "app_builder_view.StudioCanvas";
  static components = { View };
  static props = { model: Object, onRemove: { type: Function, optional: true } };
  /**
   * Every field through `hoverSoon` below is assigned unconditionally in
   * `setup()`; the five after it (`onClickCapture` through
   * `mutationObserver`) are assigned only once the canvas mounts
   * (`attach()`), and torn down again by `detach()` without ever being
   * reset -- see `detach()`'s own casts. Owl components are initialized
   * in `setup()`, not a constructor -- `Component` gives no other hook to
   * override for it -- so TypeScript's own `strictPropertyInitialization`,
   * which only ever looks at a constructor, cannot see any of this: the
   * first group carries a definite-assignment assertion (`!`) to say so
   * anyway, the second is typed `| undefined` instead, since that really
   * is what each one is before `attach()` first runs.
   */
  model;
  scrollRef;
  groundRef;
  overlay;
  drag;
  pendingPage;
  pendingScroll;
  /** A token to scroll into view once it is rendered: the outline
   * asked for it, and its page may still be switching. */
  pendingReveal;
  savedScroll;
  renderedVersion;
  restoringPage;
  point;
  selectionPoint;
  alignSoon;
  scrollSoon;
  hoverSoon;
  onClickCapture;
  onMove;
  onLeave;
  resizeObserver;
  mutationObserver;
  /** Cached by `viewProps`/`computeViewProps` -- see their own doc
   * comments; `undefined` until the first read. */
  viewPropsCanvas;
  viewPropsKey;
  viewPropsCache;
  setup() {
    this.model = useState(this.props.model);
    this.scrollRef = useRef("scroll");
    this.groundRef = useRef("ground");
    this.overlay = null;
    this.drag = null;
    this.pendingPage = null;
    this.pendingScroll = null;
    this.pendingReveal = null;
    this.savedScroll = 0;
    this.renderedVersion = null;
    this.restoringPage = false;
    this.point = null;
    this.selectionPoint = null;
    this.alignSoon = useThrottleForAnimation(() => this.afterRender());
    this.scrollSoon = useThrottleForAnimation(() => this.afterRender({ scrolled: true }));
    this.hoverSoon = useThrottleForAnimation((ev) => this.onHover(ev));
    onMounted(() => this.attach());
    onWillUnmount(() => this.detach());
    onWillPatch(() => {
      if (this.scrollRef.el) {
        this.savedScroll = this.scrollRef.el.scrollTop;
      }
    });
    onPatched(() => {
      const key = this.viewKey;
      if (key !== this.renderedVersion) {
        this.renderedVersion = key;
        this.pendingPage = this.model.activePage;
        this.pendingScroll = this.savedScroll;
      }
    });
    useEffect(
      () => {
        this.drawOverlay();
      },
      () => [
        this.model.hover,
        this.model.selection && this.model.selection.token,
        this.model.archVersion,
        this.model.showInvisible
      ]
    );
    useEffect(
      (serial) => {
        if (serial) {
          this.beginReveal(this.model.revealToken);
        }
      },
      () => [this.model.revealSerial]
    );
  }
  /**
   * Bring a node on screen: the page it is on is switched to, and its
   * element is scrolled to once the page has rendered. A node that is
   * not rendered -- hidden by its groups, on no page that exists --
   * leaves the request standing for the next reveal to overwrite.
   */
  beginReveal(token) {
    const el = this.scrollRef.el;
    const nodes = this.model.nodes;
    const startNode = token ? nodes[token] : void 0;
    if (!el || !token || !startNode) {
      return;
    }
    let page = startNode.kind === "page" ? token : null;
    let cursor = startNode.parent;
    while (!page && cursor) {
      const cursorNode = nodes[cursor];
      if (!cursorNode) {
        break;
      }
      if (cursorNode.kind === "page") {
        page = cursor;
      }
      cursor = cursorNode.parent;
    }
    const tab = page ? tabFor(page, el) : null;
    if (tab && !tab.classList.contains("active")) {
      this.model.rememberPage(describeTab(tab));
      this.restoringPage = true;
      try {
        tab.click();
      } finally {
        this.restoringPage = false;
      }
    }
    this.pendingReveal = token;
    this.alignSoon();
  }
  // -- listeners --------------------------------------------------------
  attach() {
    const el = this.scrollRef.el;
    this.renderedVersion = this.viewKey;
    this.overlay = new Overlay(el, {
      onRemove: (token) => this.props.onRemove && this.props.onRemove(token)
    });
    const overlay = this.overlay;
    this.drag = makeCanvasDrag({
      rootEl: el.closest(".o_studio_console") || el,
      scrollEl: el,
      overlay,
      model: this.model,
      point: () => this.point,
      // A drop selects what it dropped, in the card it dropped it
      // in: the frame is to be drawn there, not where the pointer
      // last hovered before the drag.
      pointAt: (point) => {
        this.point = point;
        this.selectionPoint = point;
      }
    });
    this.onClickCapture = (ev) => this.onClick(ev);
    el.addEventListener("click", this.onClickCapture, true);
    this.onMove = (ev) => this.hoverSoon(ev);
    this.onLeave = () => this.model.hoverAt(null);
    el.addEventListener("mousemove", this.onMove);
    el.addEventListener("mouseleave", this.onLeave);
    el.addEventListener("scroll", this.scrollSoon);
    this.resizeObserver = new ResizeObserver(() => this.alignSoon());
    this.resizeObserver.observe(el);
    this.mutationObserver = new MutationObserver(() => this.alignSoon());
    this.mutationObserver.observe(this.groundRef.el || el, {
      childList: true,
      subtree: true
    });
    this.drawOverlay();
  }
  detach() {
    const el = this.scrollRef.el;
    if (el) {
      el.removeEventListener("click", this.onClickCapture, true);
      el.removeEventListener("mousemove", this.onMove);
      el.removeEventListener("mouseleave", this.onLeave);
      el.removeEventListener("scroll", this.scrollSoon);
    }
    this.resizeObserver?.disconnect();
    this.mutationObserver?.disconnect();
    this.drag?.destroy();
    this.drag = null;
    this.overlay?.destroy();
    this.overlay = null;
  }
  /**
   * Select what was clicked, and keep the view from acting on it.
   *
   * The overlay's own controls and the notebook tabs are let through;
   * everything else is stopped here, before the view's own listeners see
   * it.
   */
  onClick(ev) {
    const target = ev.target instanceof Element ? ev.target : null;
    if (target && target.closest(".o_studio_overlay")) {
      return;
    }
    const tab = target && target.closest(compat.TAB_SELECTOR);
    if (tab) {
      this.model.rememberPage(describeTab(tab));
      const token = ownToken(tab);
      if (!this.restoringPage && !this.model.drag && token && this.model.nodes[token]) {
        this.model.select(token);
      }
      return;
    }
    ev.preventDefault();
    ev.stopPropagation();
    this.point = { x: ev.clientX, y: ev.clientY };
    this.selectionPoint = this.point;
    const hit = tokenOf(target, this.model.nodes);
    this.model.select(hit ? hit.token : this.model.root);
  }
  onHover(ev) {
    this.point = { x: ev.clientX, y: ev.clientY };
    const target = ev.target instanceof Element ? ev.target : null;
    if (!this.model.canvas || target && target.closest(".o_studio_overlay")) {
      return;
    }
    const tab = target && target.closest(compat.TAB_SELECTOR);
    const hit = tab ? { token: ownToken(tab) } : tokenOf(target, this.model.nodes);
    this.model.hoverAt(hit && hit.token && this.model.nodes[hit.token] ? hit.token : null);
  }
  // -- after the view has rendered ---------------------------------------
  afterRender({ scrolled = false } = {}) {
    const el = this.scrollRef.el;
    if (!el) {
      return;
    }
    if (this.pendingPage) {
      const tab = findTab(el, this.pendingPage);
      if (tab) {
        this.pendingPage = null;
        if (!tab.classList.contains("active")) {
          this.restoringPage = true;
          try {
            tab.click();
          } finally {
            this.restoringPage = false;
          }
          return;
        }
      }
    }
    if (this.pendingScroll !== null && el.scrollHeight - el.clientHeight >= this.pendingScroll) {
      el.scrollTop = this.pendingScroll;
      this.pendingScroll = null;
    }
    if (this.pendingReveal) {
      const instance = instanceOf(
        this.pendingReveal,
        el,
        this.model.nodes,
        this.selectionPoint
      );
      if (instance) {
        this.pendingReveal = null;
        instance.scrollIntoView({ block: "nearest", inline: "nearest" });
      }
    }
    this.drawOverlay();
    if (this.drag && !scrolled) {
      this.drag.onCanvasChanged();
    }
  }
  drawOverlay() {
    const overlay = this.overlay;
    if (!overlay) {
      return;
    }
    const selection = this.model.selection ? this.model.selection.token : null;
    overlay.update({
      hover: this.model.hover,
      selection,
      nodes: this.model.nodes,
      tag: selection ? this.model.tagFor(selection) : "",
      point: this.point,
      selectionPoint: this.selectionPoint
    });
  }
  /**
   * Whether the view is showing sample records: the model has none, and
   * the server asked a list or kanban for sample data so there are still
   * rows and cards to build on.
   */
  get showsSampleData() {
    const canvas = this.model.canvas;
    return Boolean(
      canvas && ["list", "kanban"].includes(canvas.view.type) && canvas.record_count === 0
    );
  }
  // -- what the View is told ---------------------------------------------
  get viewKey() {
    return `${this.model.archVersion}:${this.model.showInvisible}:${this.model.renderSerial}`;
  }
  /**
   * The props of the View, and nothing that would make it fetch views:
   * no `searchViewId`, no `loadActionMenus`, no `loadIrFilters`. Props a
   * controller does not declare are refused in dev mode, so the
   * form-only ones are sent to forms alone.
   *
   * One object per canvas payload, not per render: this component
   * re-renders on every hover, and a fresh props object each time would
   * have the View re-render with it for nothing. Keyed on the payload
   * itself rather than its version alone, since two payloads of one
   * version can differ in what they render -- with and without the
   * invisible elements.
   */
  get viewProps() {
    const canvas = this.model.canvas;
    if (this.viewPropsCanvas !== canvas || this.viewPropsKey !== this.viewKey) {
      this.viewPropsCanvas = canvas;
      this.viewPropsKey = this.viewKey;
      this.viewPropsCache = this.computeViewProps();
    }
    return this.viewPropsCache;
  }
  computeViewProps() {
    const canvas = this.model.canvas;
    const type = canvas.view.type;
    const modelName = canvas.view.model;
    const models = canvas.models;
    const props = {
      type,
      resModel: modelName,
      viewId: canvas.view.id,
      arch: canvas.arch,
      fields: models[modelName].fields,
      relatedModels: models,
      context: {},
      noBreadcrumbs: true,
      display: type === "form" ? { controlPanel: {} } : { controlPanel: false }
    };
    const jsClass = canvasJsClass(type, canvas.view.js_class);
    if (jsClass) {
      props.jsClass = jsClass;
    }
    if (type === "form") {
      Object.assign(props, {
        resId: canvas.res_id || false,
        preventCreate: true,
        preventEdit: true,
        ...compat.readonlyViewProps()
      });
    } else if (type === "list") {
      Object.assign(props, {
        allowSelectors: false,
        allowOpenAction: false,
        showButtons: false
      });
    }
    return props;
  }
  get hasCanvas() {
    return Boolean(this.model.canvas && this.model.canvas.arch);
  }
}
export {
  StudioCanvas
};
