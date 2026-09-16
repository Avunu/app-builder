/** @odoo-module **/
/**
 * The canvas: the real view, rendered, with nothing it does taken at face
 * value.
 *
 * Rendered through the stock `View` from the arch and field descriptions
 * the server hands over, so no `get_views` is made for it and the arch the
 * user sees is the arch the server named. Three things are intercepted on
 * the way in, and only three:
 *
 *  - **clicks**, in the capture phase on the scroll container -- a click in
 *    a list would open a record, one on a button would run it. A notebook
 *    tab is let through, since selecting a page you cannot see is useless,
 *    and the page it shows is remembered so that a remount lands on it.
 *  - **saving**, by rendering under a derived view class whose controller
 *    never saves (`canvas_views.js`).
 *  - **the pager and the rest of the control panel**, by stylesheet; the
 *    panel itself stays mounted because a form's smart buttons render in it.
 *
 * The overlay -- hover, selection, the drop zones -- is a layer this
 * component owns in its scroll container, drawn by `overlay.js` and
 * re-aligned whenever the view underneath has re-rendered. The drag that
 * fills the zones is `drag.js`, created here because its life is the
 * canvas's: it picks things up anywhere in the console -- the palette is
 * outside this component -- but everything it drops on is in here.
 *
 * A kanban renders its card once per record, so a token is many elements
 * and the canvas keeps two points to tell them apart: where the pointer
 * is, for the hover, and where the selection was made -- a click, a drop
 * -- for the frame, which stays on that card while the pointer wanders.
 * An empty model shows sample records instead, and says so: the drop
 * still works, since it changes the arch and not the data.
 */

import {
    Component,
    onMounted,
    onPatched,
    onWillPatch,
    onWillUnmount,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { useThrottleForAnimation } from "@web/core/utils/timing";
import { View } from "@web/views/view";
import { canvasJsClass } from "./canvas_views";
import * as compat from "./compat";
import { makeCanvasDrag } from "./drag";
import { instanceOf } from "./geometry";
import { describeTab, findTab, ownToken, tabFor, tokenOf } from "./identity";
import { Overlay } from "./overlay";

export class StudioCanvas extends Component {
    static template = "app_builder_view.StudioCanvas";
    static components = { View };
    static props = { model: Object, onRemove: { type: Function, optional: true } };

    setup() {
        this.model = useState(this.props.model);
        this.scrollRef = useRef("scroll");
        this.groundRef = useRef("ground");
        this.overlay = null;
        this.drag = null;
        this.pendingPage = null;
        this.pendingScroll = null;
        // A token to scroll into view once it is rendered: the outline
        // asked for it, and its page may still be switching.
        this.pendingReveal = null;
        this.savedScroll = 0;
        this.renderedVersion = null;
        this.restoringPage = false;
        this.point = null;
        this.selectionPoint = null;

        this.alignSoon = useThrottleForAnimation(() => this.afterRender());
        // A scroll moves the overlay with the content and changes nothing
        // else: the outlines are re-measured, the drop zones left alone.
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
                // The View is being remounted -- the arch changed, or the
                // invisible elements were toggled -- and the page and the
                // scroll position it should come back to are decided now,
                // then applied once the DOM has arrived.
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
                this.model.showInvisible,
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
        if (!el || !token || !nodes[token]) {
            return;
        }
        let page = nodes[token].kind === "page" ? token : null;
        for (let cursor = nodes[token].parent; !page && cursor && nodes[cursor]; ) {
            if (nodes[cursor].kind === "page") {
                page = cursor;
            }
            cursor = nodes[cursor].parent;
        }
        const tab = page ? tabFor(page, el) : null;
        if (tab && !tab.classList.contains("active")) {
            // The switch is not the user choosing a page, and the selection
            // is already what was asked for: the click must not re-select.
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
            onRemove: (token) => this.props.onRemove && this.props.onRemove(token),
        });
        // The drag listens on the console root, which holds the palette as
        // well as this canvas; the root is found rather than passed so the
        // canvas can be mounted alone, in a test, and still work.
        this.drag = makeCanvasDrag({
            rootEl: el.closest(".o_studio_console") || el,
            scrollEl: el,
            overlay: this.overlay,
            model: this.model,
            point: () => this.point,
            // A drop selects what it dropped, in the card it dropped it
            // in: the frame is to be drawn there, not where the pointer
            // last hovered before the drag.
            pointAt: (point) => {
                this.point = point;
                this.selectionPoint = point;
            },
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
        // The view fills in asynchronously -- the record loads, a tab
        // switches -- and every one of those changes what the overlay sits
        // on; watching the subtree is the one hook that sees them all. The
        // View's own wrapper is watched, not the scroll container: the
        // overlay lives in the container too, and a layer that re-aligns
        // on its own mutations would re-align forever.
        this.mutationObserver = new MutationObserver(() => this.alignSoon());
        this.mutationObserver.observe(this.groundRef.el || el, {
            childList: true,
            subtree: true,
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
        this.resizeObserver && this.resizeObserver.disconnect();
        this.mutationObserver && this.mutationObserver.disconnect();
        this.drag && this.drag.destroy();
        this.drag = null;
        this.overlay && this.overlay.destroy();
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
        const target = ev.target;
        if (target.closest && target.closest(".o_studio_overlay")) {
            return;
        }
        const tab = target.closest && target.closest(compat.TAB_SELECTOR);
        if (tab) {
            this.model.rememberPage(describeTab(tab));
            const token = ownToken(tab);
            // A tab the canvas re-activates after a remount is not a tab
            // the user chose, and neither is one a drag switched to on
            // its way somewhere: the selection stays where it was.
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
        const target = ev.target;
        if (!this.model.canvas || (target.closest && target.closest(".o_studio_overlay"))) {
            return;
        }
        const tab = target.closest && target.closest(compat.TAB_SELECTOR);
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
            const instance = instanceOf(this.pendingReveal, el, this.model.nodes, this.selectionPoint);
            if (instance) {
                this.pendingReveal = null;
                instance.scrollIntoView({ block: "nearest", inline: "nearest" });
            }
        }
        this.drawOverlay();
        // A drag in flight lays its zones out again for the canvas as it
        // is now: the view re-rendered or the canvas was resized under it.
        // A scroll is neither -- the zones are drawn in content
        // coordinates and travel with it.
        if (this.drag && !scrolled) {
            this.drag.onCanvasChanged();
        }
    }

    drawOverlay() {
        if (!this.overlay) {
            return;
        }
        const selection = this.model.selection ? this.model.selection.token : null;
        this.overlay.update({
            hover: this.model.hover,
            selection,
            nodes: this.model.nodes,
            tag: selection ? this.model.tagFor(selection) : "",
            point: this.point,
            selectionPoint: this.selectionPoint,
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
            canvas &&
                ["list", "kanban"].includes(canvas.view.type) &&
                canvas.record_count === 0
        );
    }

    // -- what the View is told ---------------------------------------------

    get viewKey() {
        // The serial is for a change under an unchanged arch -- a manual
        // field renamed -- which the version alone would not remount on.
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
        const props = {
            type,
            resModel: modelName,
            viewId: canvas.view.id,
            arch: canvas.arch,
            fields: canvas.models[modelName].fields,
            relatedModels: canvas.models,
            context: {},
            noBreadcrumbs: true,
            display: type === "form" ? { controlPanel: {} } : { controlPanel: false },
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
                ...compat.readonlyViewProps(),
            });
        } else if (type === "list") {
            Object.assign(props, {
                allowSelectors: false,
                allowOpenAction: false,
                showButtons: false,
            });
        }
        return props;
    }

    get hasCanvas() {
        return Boolean(this.model.canvas && this.model.canvas.arch);
    }
}
