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
import type { ConsoleModel } from "./console_model";
import { makeCanvasDrag } from "./drag";
import type { CanvasDrag } from "./drag";
import { instanceOf } from "./geometry";
import { describeTab, findTab, ownToken, tabFor, tokenOf } from "./identity";
import type { TabMemory } from "./identity";
import { Overlay } from "./overlay";
import type { CanvasPayload, Point, Token } from "./types";

export interface Props {
    model: ConsoleModel;
    onRemove?: (token: Token) => void;
}

/**
 * The real shape of `CanvasPayload.models` (`studio_view_canvas.py:canvas`):
 * one entry per model the view or one of its inline subviews reads from,
 * each carrying `fields_get()`'s own per-field dict for exactly the field
 * names that model uses here. `types.ts` still types `CanvasPayload.models`
 * as `unknown` -- its own docstring says nothing converted before this file
 * read it. This is that first real reader, so the shape is traced to the
 * Python construction (`payload["models"]`'s dict comprehension) rather
 * than guessed; cast at the one place it is read below, not widened on
 * `CanvasPayload` itself -- narrowing the shared type is this migration's
 * own job to reconcile once another file needs the same shape.
 */
interface CanvasModelEntry {
    fields: Record<string, unknown>;
}

/**
 * What `viewProps` sends the stock `View` -- exactly the keys
 * `computeViewProps` builds, traced against `@web/views/view.js`'s own
 * `ViewProps` JSDoc typedef and `STANDARD_PROPS` list for which of them
 * are real props and not something `View` computes for itself.  `View`'s
 * own `static props` validates with `"*": true` at runtime, so nothing
 * here is cross-checked against the vendor component's own schema by
 * `tsc` -- this interface exists for this file's own construction and
 * caching, not for a prop contract Owl would otherwise enforce.
 */
interface CanvasViewProps {
    type: string;
    resModel: string;
    viewId: number;
    arch: string;
    fields: Record<string, unknown>;
    relatedModels: Record<string, CanvasModelEntry>;
    context: Record<string, unknown>;
    noBreadcrumbs: boolean;
    display: { controlPanel: Record<string, unknown> } | { controlPanel: false };
    jsClass?: string;
    resId?: number | false;
    preventCreate?: boolean;
    preventEdit?: boolean;
    readonly?: boolean;
    mode?: string;
    allowSelectors?: boolean;
    allowOpenAction?: boolean;
    showButtons?: boolean;
}

export class StudioCanvas extends Component<Props> {
    static override template = "app_builder_view.StudioCanvas";
    static components = { View };
    static override props = { model: Object, onRemove: { type: Function, optional: true } };

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
    model!: ConsoleModel;
    scrollRef!: { el: HTMLElement | null };
    groundRef!: { el: HTMLElement | null };
    overlay!: Overlay | null;
    drag!: CanvasDrag | null;
    pendingPage!: TabMemory | null;
    pendingScroll!: number | null;
    /** A token to scroll into view once it is rendered: the outline
     * asked for it, and its page may still be switching. */
    pendingReveal!: Token | null;
    savedScroll!: number;
    renderedVersion!: string | null;
    restoringPage!: boolean;
    point!: Point | null;
    selectionPoint!: Point | null;

    alignSoon!: (() => void) & { cancel(): void };
    scrollSoon!: (() => void) & { cancel(): void };
    hoverSoon!: ((ev: MouseEvent) => void) & { cancel(): void };

    onClickCapture: ((ev: MouseEvent) => void) | undefined;
    onMove: ((ev: MouseEvent) => void) | undefined;
    onLeave: (() => void) | undefined;
    resizeObserver: ResizeObserver | undefined;
    mutationObserver: MutationObserver | undefined;

    /** Cached by `viewProps`/`computeViewProps` -- see their own doc
     * comments; `undefined` until the first read. */
    viewPropsCanvas?: CanvasPayload | null;
    viewPropsKey?: string;
    viewPropsCache?: CanvasViewProps;

    override setup(): void {
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
        // A scroll moves the overlay with the content and changes nothing
        // else: the outlines are re-measured, the drop zones left alone.
        this.scrollSoon = useThrottleForAnimation(() => this.afterRender({ scrolled: true }));
        this.hoverSoon = useThrottleForAnimation((ev: MouseEvent) => this.onHover(ev));

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
            ],
        );
        useEffect(
            (serial: number | undefined) => {
                if (serial) {
                    this.beginReveal(this.model.revealToken);
                }
            },
            () => [this.model.revealSerial],
        );
    }

    /**
     * Bring a node on screen: the page it is on is switched to, and its
     * element is scrolled to once the page has rendered. A node that is
     * not rendered -- hidden by its groups, on no page that exists --
     * leaves the request standing for the next reveal to overwrite.
     */
    beginReveal(token: Token | null): void {
        const el = this.scrollRef.el;
        const nodes = this.model.nodes;
        const startNode = token ? nodes[token] : undefined;
        if (!el || !token || !startNode) {
            return;
        }
        let page: Token | null = startNode.kind === "page" ? token : null;
        // Rewritten from the original's `for (let cursor = ...; !page &&
        // cursor && nodes[cursor]; )` -- `noUncheckedIndexedAccess` types
        // every `nodes[cursor]` independently as `StudioNode | undefined`,
        // even a second read of the very same key within one iteration, so
        // the node has to be captured into a local once per step and
        // reused, which a `for` loop's own condition has nowhere to put.
        // Same walk, same stopping conditions, one lookup per step instead
        // of up to three.
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

    attach(): void {
        // `onMounted` runs only once this component's own DOM exists, so
        // `scrollRef.el` is never null from here on while it stays
        // mounted -- `useRef`'s own type says `HTMLElement | null` only
        // because the same `Ref` answers `null` before mount and after
        // unmount.
        const el = this.scrollRef.el as HTMLElement;
        this.renderedVersion = this.viewKey;
        this.overlay = new Overlay(el, {
            onRemove: (token) => this.props.onRemove && this.props.onRemove(token),
        });
        const overlay = this.overlay;
        // The drag listens on the console root, which holds the palette as
        // well as this canvas; the root is found rather than passed so the
        // canvas can be mounted alone, in a test, and still work.
        this.drag = makeCanvasDrag({
            rootEl: el.closest<HTMLElement>(".o_studio_console") || el,
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

    detach(): void {
        const el = this.scrollRef.el;
        if (el) {
            // Cast past the `| undefined` half of each field's own type:
            // all three are only ever assigned in `attach()`, which --
            // by the same `onMounted`/`onWillUnmount` ordering `attach()`'s
            // own cast above already relies on -- always runs before
            // `detach()` can.
            el.removeEventListener("click", this.onClickCapture as EventListener, true);
            el.removeEventListener("mousemove", this.onMove as EventListener);
            el.removeEventListener("mouseleave", this.onLeave as EventListener);
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
    onClick(ev: MouseEvent): void {
        // `ev.target` is `EventTarget | null` in the DOM lib -- `.closest`
        // only exists on `Element`, which is also what the original JS's
        // own `target.closest && ...` guard was really checking (a text
        // node, say, has no `closest` at all). Narrowed once here, the
        // same way, instead of repeating the `instanceof` check below.
        const target = ev.target instanceof Element ? ev.target : null;
        if (target && target.closest(".o_studio_overlay")) {
            return;
        }
        const tab = target && target.closest(compat.TAB_SELECTOR);
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

    onHover(ev: MouseEvent): void {
        this.point = { x: ev.clientX, y: ev.clientY };
        const target = ev.target instanceof Element ? ev.target : null;
        if (!this.model.canvas || (target && target.closest(".o_studio_overlay"))) {
            return;
        }
        const tab = target && target.closest(compat.TAB_SELECTOR);
        const hit = tab ? { token: ownToken(tab) } : tokenOf(target, this.model.nodes);
        this.model.hoverAt(hit && hit.token && this.model.nodes[hit.token] ? hit.token : null);
    }

    // -- after the view has rendered ---------------------------------------

    afterRender({ scrolled = false }: { scrolled?: boolean } = {}): void {
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
        if (
            this.pendingScroll !== null &&
            el.scrollHeight - el.clientHeight >= this.pendingScroll
        ) {
            el.scrollTop = this.pendingScroll;
            this.pendingScroll = null;
        }
        if (this.pendingReveal) {
            const instance = instanceOf(
                this.pendingReveal,
                el,
                this.model.nodes,
                this.selectionPoint,
            );
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

    drawOverlay(): void {
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
            selectionPoint: this.selectionPoint,
        });
    }

    /**
     * Whether the view is showing sample records: the model has none, and
     * the server asked a list or kanban for sample data so there are still
     * rows and cards to build on.
     */
    get showsSampleData(): boolean {
        const canvas = this.model.canvas;
        return Boolean(
            canvas && ["list", "kanban"].includes(canvas.view.type) && canvas.record_count === 0,
        );
    }

    // -- what the View is told ---------------------------------------------

    get viewKey(): string {
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
    get viewProps(): CanvasViewProps {
        const canvas = this.model.canvas;
        if (this.viewPropsCanvas !== canvas || this.viewPropsKey !== this.viewKey) {
            this.viewPropsCanvas = canvas;
            this.viewPropsKey = this.viewKey;
            this.viewPropsCache = this.computeViewProps();
        }
        // `viewPropsCache` is `undefined` only before this getter's first
        // call; the branch above always fills it in on that call
        // (`undefined !== canvas` the first time), so every reachable path
        // past it carries a real value -- a fact that `viewPropsCanvas`/
        // `viewPropsCache` being two separate fields keeps from the type
        // checker itself.
        return this.viewPropsCache as CanvasViewProps;
    }

    computeViewProps(): CanvasViewProps {
        // `viewProps`/`computeViewProps` are only ever reached from the
        // template behind `hasCanvas`, which requires `canvas.arch` to be
        // truthy -- and `studio_view_canvas.py:canvas`'s own early return
        // means `arch` (and `models`) are filled in only once `view.model`
        // names a real, existing model too. Both casts below trust that
        // same invariant, the same way `console_model.ts`'s own
        // `this.modelName as string` already does at its own call site.
        const canvas = this.model.canvas as CanvasPayload;
        const type = canvas.view.type;
        const modelName = canvas.view.model as string;
        const models = canvas.models as Record<string, CanvasModelEntry>;
        const props: CanvasViewProps = {
            type,
            resModel: modelName,
            viewId: canvas.view.id,
            arch: canvas.arch as string,
            fields: (models[modelName] as CanvasModelEntry).fields,
            relatedModels: models,
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

    get hasCanvas(): boolean {
        return Boolean(this.model.canvas && this.model.canvas.arch);
    }
}
