/** @odoo-module **/
/**
 * The outline: the view as a tree, above the sidebar's tabs.
 *
 * One row per node of the arch, indented by depth, in document order --
 * what the canvas shows, and what it does not: a field on a tab that is
 * not open, one hidden by its groups or by `invisible`, a field staged
 * and waiting for Apply. The tree and the canvas select the same thing:
 * a click on a row reveals the node -- its page switched to, its element
 * scrolled to, the properties opened, as for a click on the canvas --
 * and a click on the canvas opens the row's ancestors and scrolls to it.
 * Hovering either outlines the other.
 *
 * Rows are picked up and put down like anything else in the console:
 * `drag.ts` reads `data-token` off a row and lays its zones over the
 * list (`outline_zones.ts`) beside the canvas's, through the provider
 * this component leaves on the model while it is mounted. The keyboard
 * makes the same moves without aim -- Alt with an arrow puts the focused
 * row before its neighbour, after it, out of its container or into the
 * one above -- and a right-click offers them by name, with Remove and
 * the label switch.
 *
 * Nothing a person does to the tree is remembered by token: tokens are
 * ordinals and the whole table is minted anew on every edit. A folded
 * container and the focused row are kept by path (`outline_tree.ts`),
 * so both are still there on the next table. The panel's height, whether
 * it is open, and what is folded in each view are kept in this browser
 * alone -- a convenience, never something the server is asked about.
 */

import {
    Component,
    markRaw,
    onMounted,
    onPatched,
    onWillUnmount,
    toRaw,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { usePopover } from "@web/core/popover/popover_hook";
import { focusLabelRow } from "../drag";
import type { OutlineDragProvider } from "../drag";
import { useService } from "../odoo";
import type { DialogService } from "../odoo";
import {
    flatten,
    moveTarget,
    nextFocus,
    pathAfterMove,
    pathKey,
    visibleChildren,
} from "../outline_tree";
import type { MoveDirection } from "../outline_tree";
import { ZoneLayer } from "../overlay";
import { attachVerticalResize } from "../split";
import type { VerticalResizeHandle } from "../split";
import { removeWithConfirm } from "./remove_flow";
import type { ConsoleModel } from "../console_model";
import type { CanvasPayload, DragPayload, DropSuccessResult, OutlineRow, Token } from "../types";
import type { OperationResult } from "../wire";

/** Where a row of depth 0 starts, and how much each level adds, in px. */
export const OUTLINE_PAD = 8;
export const OUTLINE_INDENT = 16;

/** The panel's height when nothing is remembered, and its least. */
export const DEFAULT_HEIGHT = 240;
export const MIN_HEIGHT = 120;
/** What the tabs and their pane keep of the sidebar's height, at the least. */
export const KEEP_BELOW = 160;

const PREF_KEY = "app_builder.outline";
/** How many views' folds are remembered before the oldest is forgotten. */
const REMEMBERED_VIEWS = 20;

/** Which keyboard-move direction each Alt-arrow key asks for
 * (`onKeyDown`'s own Alt branch). */
const ARROW_DIRECTIONS: Record<string, MoveDirection> = {
    ArrowUp: "up",
    ArrowDown: "down",
    ArrowLeft: "out",
    ArrowRight: "in",
};

/** What this browser remembers of the outline, keyed by `String(viewId)`
 * (the same coercion a plain-object key already applies at runtime to a
 * numeric `viewId`, made explicit here to give `collapsed` one honest key
 * type). */
export interface OutlinePrefs {
    height?: number;
    open?: boolean;
    collapsed?: Record<string, string[]>;
}

/** What this browser remembers of the outline, or nothing. */
export function loadPrefs(): OutlinePrefs {
    try {
        return JSON.parse(browser.localStorage.getItem(PREF_KEY) || "{}") || {};
    } catch {
        return {};
    }
}

export function savePrefs(prefs: OutlinePrefs): void {
    try {
        browser.localStorage.setItem(PREF_KEY, JSON.stringify(prefs));
    } catch {
        // A private window, storage blocked: the outline forgets, and
        // works the same.
    }
}

/** One item of the right-click menu, and whether it can be picked. */
interface OutlineMenuItem {
    key: string;
    /** `_t(...)`'s own lazy return, not stringified: nothing here needs a
     * plain `string`, and the template reads it with `t-esc`. */
    label: ReturnType<typeof _t>;
    icon: string;
    disabled: boolean;
}

interface OutlineMenuProps {
    items: OutlineMenuItem[];
    onPick: (key: string) => void;
    close: () => void;
}

/** The items of the right-click menu, and what picking one does. */
export class OutlineMenu extends Component<OutlineMenuProps> {
    static override template = "app_builder_view.OutlineMenu";
    static override props = { items: Array, onPick: Function, close: Function };

    pick(item: OutlineMenuItem): void {
        if (item.disabled) {
            return;
        }
        this.props.close();
        this.props.onPick(item.key);
    }
}

interface Props {
    model: ConsoleModel;
}

/** The panel's own local, reactive state -- everything here is UI
 * bookkeeping the outline keeps for itself, not part of the model. */
interface OutlineViewState {
    collapseSerial: number;
    filter: string;
    /** The row the keyboard is on, by path; the selection's row, then the
     * first, when none. */
    focusPath: string | null;
    height: number;
    open: boolean;
}

export class Outline extends Component<Props> {
    static override template = "app_builder_view.Outline";
    static components = { OutlineMenu };
    static override props = { model: Object };

    /**
     * Every field here is assigned unconditionally in `setup()` -- even
     * the ones that start `null` -- so each carries a definite-assignment
     * assertion (`!`); Owl components initialize in `setup()`, not a
     * constructor, which is the one hook `strictPropertyInitialization`
     * actually inspects. The two exceptions, `rowsCanvas` and `zoneLayer`,
     * are never written in `setup()`, only later (`get rows`/`registerDrag`
     * respectively), so neither gets one -- `undefined` really is their
     * state before that first happens.
     */
    model!: ConsoleModel;
    dialog!: DialogService;
    menu!: ReturnType<typeof usePopover>;
    rootRef!: { el: HTMLElement | null };
    listRef!: { el: HTMLElement | null };
    dividerRef!: { el: HTMLElement | null };
    filterRef!: { el: HTMLElement | null };
    prefs!: OutlinePrefs;
    /** The paths folded shut, outside the state: a plain Set, and the
     * serial is what the rows are recomputed on. */
    collapsed!: Set<string>;
    state!: OutlineViewState;
    rowsCache!: OutlineRow[] | null;
    rowsCanvas?: CanvasPayload | null;
    rowsKey!: string | null;
    /** Whether the focused row is to be focused again once the rows
     * have been drawn -- after a key press, after a move. */
    pendingFocus!: boolean;
    pendingScroll!: Token | null;
    resizer!: VerticalResizeHandle | null;
    resizeObserver!: ResizeObserver | null;
    zoneLayer?: ZoneLayer | null;

    override setup(): void {
        this.model = useState(this.props.model);
        this.dialog = useService("dialog");
        this.menu = usePopover(OutlineMenu, {
            position: "bottom-start",
            popoverClass: "o_studio_outline_menu_popover",
        });
        this.rootRef = useRef("root");
        this.listRef = useRef("list");
        this.dividerRef = useRef("divider");
        this.filterRef = useRef("filter");
        const prefs = loadPrefs();
        this.prefs = prefs;
        this.collapsed = new Set<string>();
        this.state = useState<OutlineViewState>({
            collapseSerial: 0,
            filter: "",
            focusPath: null,
            height: Number(prefs.height) || DEFAULT_HEIGHT,
            open: prefs.open !== false,
        });
        this.rowsCache = null;
        this.rowsKey = null;
        this.pendingFocus = false;
        this.pendingScroll = null;
        this.resizer = null;
        this.resizeObserver = null;

        // The folds of the view being edited, from what is remembered.
        useEffect(
            (viewId: number | false) => {
                const key = String(viewId);
                const folds = (prefs.collapsed && prefs.collapsed[key]) || [];
                this.collapsed = new Set(folds);
                this.state.collapseSerial += 1;
                this.state.focusPath = null;
            },
            () => [this.model.viewId],
        );
        // The canvas's selection: the row is opened up to and scrolled to.
        useEffect(
            (token: Token | null) => {
                if (token) {
                    this.revealRow(token);
                }
            },
            () => [this.model.selection && this.model.selection.token],
        );
        // The list exists while the panel is open: the drag's provider
        // and the divider come and go with it.
        useEffect(
            (open: boolean) => {
                if (!open) {
                    return undefined;
                }
                this.registerDrag();
                this.attachResizer();
                return () => {
                    this.unregisterDrag();
                    this.detachResizer();
                };
            },
            () => [this.state.open],
        );
        onMounted(() => {
            const inner = this.rootRef.el && this.rootRef.el.parentElement;
            if (inner && window.ResizeObserver) {
                this.resizeObserver = new ResizeObserver(() => this.clampHeight());
                this.resizeObserver.observe(inner);
            }
        });
        onPatched(() => this.afterPatch());
        onWillUnmount(() => {
            // Optional chaining, not `a && a.method()`: a bare
            // short-circuit guard as its own statement is flagged by
            // `no-unused-expressions`, the same fix already applied to
            // `canvas.ts`'s `detach()` (TYPING.md, cluster 4 wave 1).
            this.resizeObserver?.disconnect();
            this.unregisterDrag();
            this.detachResizer();
        });
    }

    // -- the rows -------------------------------------------------------------

    /** The rows, laid out again only when the table, the folds or the filter change. */
    get rows(): OutlineRow[] {
        const modelCanvas = this.model.canvas;
        // `toRaw`'s own type (`@odoo/owl/dist/types/runtime/reactivity.d.ts`)
        // requires a non-null `Target` (`object`); calling it only once
        // `modelCanvas` is known truthy, rather than handing it `null`
        // directly, keeps this within `toRaw`'s real, declared contract
        // instead of leaning on its runtime tolerance for other inputs.
        const canvas = modelCanvas ? toRaw(modelCanvas) : null;
        const key = `${this.state.collapseSerial}:${this.state.filter}`;
        if (this.rowsCache && this.rowsCanvas === canvas && this.rowsKey === key) {
            return this.rowsCache;
        }
        this.rowsCanvas = canvas;
        this.rowsKey = key;
        this.rowsCache =
            canvas && this.model.root
                ? flatten(this.model.nodes, this.model.root, {
                      collapsed: this.collapsed,
                      filter: this.state.filter,
                  })
                : [];
        return this.rowsCache;
    }

    get selectedToken(): Token | null {
        return this.model.selection ? this.model.selection.token : null;
    }

    get hoverToken(): Token | null {
        return this.model.hover;
    }

    get canWrite(): boolean {
        return this.model.canWrite;
    }

    /** The path of the row that takes the Tab key: the focused, the selected, the first. */
    get focusKey(): string | null {
        const rows = this.rows;
        const focusPath = this.state.focusPath;
        if (focusPath && rows.some((row) => row.key === focusPath)) {
            return focusPath;
        }
        // Captured once: `selectedToken` is a getter, re-evaluated on
        // every access rather than a stored value, so it is read here
        // just once instead of once per row `.find()` would otherwise
        // call it against.
        const selectedToken = this.selectedToken;
        const selected = selectedToken && rows.find((row) => row.token === selectedToken);
        if (selected) {
            return selected.key;
        }
        // `rows.length` just confirmed index 0 exists; `noUncheckedIndexedAccess`
        // cannot see that from the length check alone (the same assertion
        // this migration already uses for other length-guarded first-element
        // reads, e.g. `field_editor_fallback.ts`'s `entries[0]!`).
        return rows.length ? rows[0]!.key : null;
    }

    get toggleTitle(): ReturnType<typeof _t> {
        return this.state.open ? _t("Hide the outline") : _t("Show the outline");
    }

    caretLabel(entry: OutlineRow): ReturnType<typeof _t> {
        return entry.expanded ? _t("Fold") : _t("Unfold");
    }

    hiddenTitle(entry: OutlineRow): ReturnType<typeof _t> {
        return entry.badges.hidden === "groups" ? _t("Hidden for your groups") : _t("Invisible");
    }

    /** The row element at a path, or `null`. */
    rowEl(path: string | null): HTMLElement | null {
        const list = this.listRef.el;
        if (!list || !path) {
            return null;
        }
        return (
            [...list.querySelectorAll<HTMLElement>(".o_studio_outline_row")].find(
                (el) => el.dataset["path"] === path,
            ) || null
        );
    }

    rowElOf(token: Token): HTMLElement | null {
        const list = this.listRef.el;
        return list
            ? [...list.querySelectorAll<HTMLElement>(".o_studio_outline_row")].find(
                  (el) => el.dataset["token"] === token,
              ) || null
            : null;
    }

    /** The row at a path, as laid out. */
    rowAt(path: string | null): OutlineRow | null {
        return this.rows.find((row) => row.key === path) || null;
    }

    // -- clicks ---------------------------------------------------------------

    /**
     * A click selects, and puts the keyboard on the row. The focus is
     * taken by hand: the drag hook prevents the default of a press on
     * anything it could pick up, and a row is one, so the browser gives
     * the row no focus of its own.
     */
    onRowClick(entry: OutlineRow, ev: MouseEvent): void {
        this.state.focusPath = entry.key;
        // `ev.currentTarget` is `EventTarget | null`, not `Element` --
        // narrowed the same way this migration already narrows `ev.target`
        // (TYPING.md's Known traps): the row that dispatched the event is
        // always a real `HTMLElement` at runtime, but the DOM lib's own
        // type does not know that.
        const currentTarget = ev.currentTarget instanceof HTMLElement ? ev.currentTarget : null;
        if (ev && currentTarget && currentTarget.focus) {
            currentTarget.focus();
        }
        this.model.reveal(entry.token);
    }

    onRowDblClick(entry: OutlineRow): void {
        this.model.reveal(entry.token);
        const root = this.rootRef.el && this.rootRef.el.closest<HTMLElement>(".o_studio_console");
        focusLabelRow(root || document.body);
    }

    onRowEnter(entry: OutlineRow): void {
        this.model.hoverAt(entry.token);
    }

    onRowLeave(): void {
        this.model.hoverAt(null);
    }

    onToggle(entry: OutlineRow, ev: MouseEvent): void {
        ev.stopPropagation();
        this.toggleCollapsed(entry);
    }

    onContextMenu(entry: OutlineRow, ev: MouseEvent): void {
        ev.preventDefault();
        ev.stopPropagation();
        this.state.focusPath = entry.key;
        const currentTarget = ev.currentTarget instanceof HTMLElement ? ev.currentTarget : null;
        if (currentTarget && currentTarget.focus) {
            currentTarget.focus();
        }
        this.openMenu(entry, currentTarget);
    }

    openMenu(entry: OutlineRow, target: HTMLElement | null): void {
        if (this.menu.isOpen) {
            this.menu.close();
        }
        // `target` is always a real element by the time either real call
        // site reaches here (`onContextMenu`'s own `ev.currentTarget`, the
        // row that dispatched the event; `onKeyDown`'s own
        // `this.rowEl(entry.key) || this.listRef.el`, the always-mounted
        // list itself). Typed nullable only because the DOM lib's own
        // `EventTarget`/`Ref.el` types are, the same gap already tracked
        // for `ev.target` (TYPING.md's Known traps).
        this.menu.open(target as HTMLElement, {
            items: this.menuItems(entry),
            // `void`, not a bare expression body: `runMenu` is `async`,
            // and `onPick` is a fire-and-forget callback with nothing
            // to await it, the same `no-floating-promises`/
            // `no-misused-promises` fix already established for
            // `doAction`/`discard`/`remove` (TYPING.md, cluster 4 wave 1).
            onPick: (key: string) => void this.runMenu(entry, key),
        });
    }

    /** What the menu offers for a row, each item said to be possible or not. */
    menuItems(entry: OutlineRow): OutlineMenuItem[] {
        const nodes = this.model.nodes;
        const node = entry.node;
        const write = this.canWrite;
        const can = (direction: MoveDirection): boolean =>
            Boolean(write && moveTarget(nodes, entry.token, direction));
        const siblings = node.parent ? visibleChildren(nodes, node.parent) : [];
        const above = siblings[siblings.indexOf(entry.token) - 1];
        const items: OutlineMenuItem[] = [
            { key: "move_up", label: _t("Move up"), icon: "fa fa-arrow-up", disabled: !can("up") },
            {
                key: "move_down",
                label: _t("Move down"),
                icon: "fa fa-arrow-down",
                disabled: !can("down"),
            },
            {
                key: "move_out",
                label: node.parent
                    ? _t("Move out of %s", this.model.tagFor(node.parent))
                    : _t("Move out"),
                icon: "fa fa-outdent",
                disabled: !can("out"),
            },
            {
                key: "move_in",
                label: above
                    ? _t("Move into %s", this.model.tagFor(above))
                    : _t("Move into the one above"),
                icon: "fa fa-indent",
                disabled: !can("in"),
            },
        ];
        if (node.kind === "field" && node.label) {
            items.push({
                key: "toggle_label",
                label: node.label.shown ? _t("Hide label") : _t("Show label"),
                icon: "fa fa-tag",
                disabled: !write,
            });
        }
        items.push({
            key: "reveal",
            label: _t("Reveal on canvas"),
            icon: "fa fa-crosshairs",
            disabled: false,
        });
        if (node.removable) {
            items.push({
                key: "remove",
                label: _t("Remove from view"),
                icon: "fa fa-times",
                disabled: !write,
            });
        }
        return items;
    }

    async runMenu(entry: OutlineRow, key: string) {
        switch (key) {
            case "move_up":
                return this.move(entry, "up");
            case "move_down":
                return this.move(entry, "down");
            case "move_out":
                return this.move(entry, "out");
            case "move_in":
                return this.move(entry, "in");
            case "toggle_label":
                // `entry.node.label` is only ever `null` on a node the
                // "toggle_label" item is never built for (`menuItems`'s
                // own `node.kind === "field" && node.label` guard); the
                // same unchecked assumption the original JS already made
                // with a plain `.shown` dot access.
                return this.model.setLabelShown(entry.token, !entry.node.label!.shown);
            case "reveal":
                return this.model.reveal(entry.token);
            case "remove":
                return this.remove(entry);
            default:
                return undefined;
        }
    }

    // -- the keyboard ---------------------------------------------------------

    onKeyDown(ev: KeyboardEvent): void {
        const rows = this.rows;
        // The row the key lands on is the one that has the focus, which
        // the roving index follows; the index alone when none has it.
        // `ev.target` is `EventTarget | null`, narrowed the same way as
        // `ev.currentTarget` above -- `HTMLElement`, not just `Element`,
        // since `.dataset` below is only on the former.
        const targetEl = ev.target instanceof HTMLElement ? ev.target : null;
        const focused = targetEl ? targetEl.closest<HTMLElement>(".o_studio_outline_row") : null;
        let index = focused ? rows.findIndex((row) => row.token === focused.dataset["token"]) : -1;
        if (index < 0) {
            index = rows.findIndex((row) => row.key === this.focusKey);
        }
        const entry = index >= 0 ? rows[index] : null;
        if (!entry) {
            return;
        }
        if (this.state.focusPath !== entry.key) {
            this.state.focusPath = entry.key;
        }
        let handled = true;
        if (ev.altKey && ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(ev.key)) {
            // `ev.key` is one of the four keys just checked; `ARROW_DIRECTIONS`
            // covers exactly them, so this lookup is always present -- the
            // same always-there index read this migration already asserts
            // elsewhere (`entries[0]!`, `candidates[0]!`). `void`: fire
            // and forget, the same as the `remove` branch below.
            void this.move(entry, ARROW_DIRECTIONS[ev.key]!);
        } else if (["ArrowUp", "ArrowDown", "Home", "End"].includes(ev.key)) {
            this.focusRow(rows[nextFocus(rows, index, ev.key)]);
        } else if (ev.key === "ArrowLeft") {
            if (entry.hasChildren && entry.expanded) {
                this.setCollapsed(entry, true);
            } else if (entry.node.parent) {
                const parent = rows.find((row) => row.token === entry.node.parent);
                this.focusRow(parent || entry);
            }
        } else if (ev.key === "ArrowRight") {
            if (entry.hasChildren && !entry.expanded) {
                this.setCollapsed(entry, false);
            } else if (entry.hasChildren && index + 1 < rows.length) {
                this.focusRow(rows[index + 1]);
            }
        } else if (ev.key === "Enter" || ev.key === " ") {
            this.model.reveal(entry.token);
        } else if (ev.key === "Delete" || ev.key === "Backspace") {
            if (entry.node.removable) {
                // Fire and forget, same as the Alt-arrow branch above.
                void this.remove(entry);
            }
        } else if (ev.key === "ContextMenu" || (ev.shiftKey && ev.key === "F10")) {
            this.openMenu(entry, this.rowEl(entry.key) || this.listRef.el);
        } else if (ev.key === "Escape" && this.menu.isOpen) {
            this.menu.close();
        } else {
            handled = false;
        }
        if (handled) {
            ev.preventDefault();
            ev.stopPropagation();
        }
    }

    onFilterKeyDown(ev: KeyboardEvent): void {
        if (ev.key === "Escape") {
            this.state.filter = "";
            ev.preventDefault();
            ev.stopPropagation();
            this.focusRow(this.rows[0]);
        } else if (ev.key === "ArrowDown") {
            ev.preventDefault();
            this.focusRow(this.rows[0]);
        }
    }

    /** Put the focus on a row: now when it is drawn, else once it is. */
    focusRow(entry: OutlineRow | undefined): void {
        if (!entry) {
            return;
        }
        this.state.focusPath = entry.key;
        const el = this.rowEl(entry.key);
        if (el) {
            el.focus();
        }
        this.pendingFocus = true;
    }

    // -- moves ----------------------------------------------------------------

    /**
     * A move asked for by key or by menu: the same request a drag makes,
     * and refused here first when the server would refuse it. The row is
     * followed by the path it will have, since the table comes back
     * with every token minted anew.
     */
    async move(
        entry: OutlineRow,
        direction: MoveDirection,
    ): Promise<
        (DropSuccessResult & { created_field: boolean; staged_field: boolean }) | undefined
    > {
        if (!this.canWrite) {
            return undefined;
        }
        const target = moveTarget(this.model.nodes, entry.token, direction);
        if (!target) {
            return undefined;
        }
        const node = entry.node;
        const payload: DragPayload =
            node.kind === "pending"
                ? {
                      kind: "move_pending",
                      token: entry.token,
                      name: (node.pending && node.pending.name) || node.name,
                  }
                : { kind: "move", token: entry.token };
        this.state.focusPath = pathAfterMove(this.model.nodes, entry.token, target);
        const result = await this.model.drop(target.target, target.position, payload);
        if (result !== undefined) {
            // The table is new: the row at the path is drawn on the next
            // patch, and the focus -- lost with the old row -- goes to it
            // then. Armed only now: armed before, the patch that drew the
            // path on the old table would have spent it.
            this.pendingFocus = true;
            this.afterMove();
        }
        return result;
    }

    /**
     * The server selects what it moved by name; an unnamed node it finds
     * again by its old token, which may now be its neighbour. The path
     * knows better, and the selection follows it when they disagree.
     */
    afterMove(): void {
        const row = this.rowAt(this.state.focusPath);
        const selected = this.selectedToken;
        if (row && selected && row.token !== selected) {
            const node = this.model.nodes[selected];
            if (node && node.tag === row.node.tag) {
                this.model.select(row.token);
            }
        }
    }

    async remove(
        entry: OutlineRow,
    ): Promise<OperationResult | { confirm: string; context: unknown } | undefined> {
        if (!this.canWrite) {
            return undefined;
        }
        return removeWithConfirm({ model: this.model, dialog: this.dialog, token: entry.token });
    }

    // -- folds ----------------------------------------------------------------

    toggleCollapsed(entry: OutlineRow): void {
        this.setCollapsed(entry, !this.collapsed.has(entry.key));
    }

    setCollapsed(entry: OutlineRow, collapsed: boolean): void {
        if (collapsed) {
            this.collapsed.add(entry.key);
        } else {
            this.collapsed.delete(entry.key);
        }
        this.state.collapseSerial += 1;
        this.saveFolds();
    }

    /** Open every container above `token`; whether any was shut. */
    expandAncestors(token: Token): boolean {
        const nodes = this.model.nodes;
        let changed = false;
        // Captured once, rather than re-reading `nodes[cursor]` on every
        // loop turn's condition and again in the body -- the
        // repeated-bracket-index trap (TYPING.md's Known traps).
        const startNode = nodes[token];
        let cursor: Token | null = startNode ? startNode.parent : null;
        for (;;) {
            if (!cursor) {
                break;
            }
            const node = nodes[cursor];
            if (!node) {
                break;
            }
            const key = pathKey(nodes, cursor);
            if (this.collapsed.delete(key)) {
                changed = true;
            }
            cursor = node.parent;
        }
        if (changed) {
            this.state.collapseSerial += 1;
            this.saveFolds();
        }
        return changed;
    }

    /** Open one container, for the drag resting on its row. */
    expand(token: Token): void {
        const nodes = this.model.nodes;
        if (!nodes[token]) {
            return;
        }
        const key = pathKey(nodes, token);
        if (this.collapsed.delete(key)) {
            this.state.collapseSerial += 1;
            this.saveFolds();
        }
    }

    isCollapsed(token: Token): boolean {
        const nodes = this.model.nodes;
        return Boolean(nodes[token] && this.collapsed.has(pathKey(nodes, token)));
    }

    // -- the canvas's selection -----------------------------------------------

    revealRow(token: Token): void {
        this.expandAncestors(token);
        this.pendingScroll = token;
        this.scrollPending();
    }

    scrollPending(): void {
        const token = this.pendingScroll;
        const el = token ? this.rowElOf(token) : null;
        if (el) {
            this.pendingScroll = null;
            el.scrollIntoView({ block: "nearest" });
        }
    }

    /**
     * The rows have been drawn again. A row asked for is scrolled to; the
     * focus, when it was on a row that the table swap took away -- it
     * fell to the body -- or on another row, goes to the one the path
     * names. Focus elsewhere in the console is left alone.
     */
    afterPatch(): void {
        this.scrollPending();
        if (!this.pendingFocus) {
            return;
        }
        const el = this.rowEl(this.focusKey);
        if (!el) {
            return;
        }
        this.pendingFocus = false;
        const active = document.activeElement;
        const list = this.listRef.el;
        if (
            active !== el &&
            (!active || active === document.body || (list && list.contains(active)))
        ) {
            el.focus();
        }
    }

    // -- the drag -------------------------------------------------------------

    registerDrag(): void {
        const list = this.listRef.el;
        if (!list) {
            return;
        }
        this.unregisterDrag();
        this.zoneLayer = new ZoneLayer(list);
        // Captured once: read straight back off `this.zoneLayer` here
        // would still be the same value, but a local avoids relying on
        // that (this migration's own house pattern for a field just
        // assigned above).
        const zoneLayer = this.zoneLayer;
        const provider: OutlineDragProvider = {
            el: list,
            layer: zoneLayer,
            rows: () => [...list.querySelectorAll<HTMLElement>(".o_studio_outline_row")],
            indentOf: (depth) => OUTLINE_PAD + depth * OUTLINE_INDENT,
            isCollapsed: (token) => this.isCollapsed(token),
            expand: (token) => this.expand(token),
        };
        this.model.outlineDrag = markRaw(provider);
    }

    unregisterDrag(): void {
        if (this.zoneLayer) {
            this.zoneLayer.destroy();
            this.zoneLayer = null;
        }
        if (this.model.outlineDrag) {
            this.model.outlineDrag = null;
        }
    }

    // -- the panel ------------------------------------------------------------

    toggleOpen(): void {
        this.state.open = !this.state.open;
        this.savePanel();
    }

    attachResizer(): void {
        const handle = this.dividerRef.el;
        if (!handle) {
            return;
        }
        this.detachResizer();
        // `onMounted`/the `useEffect` above only ever call `attachResizer`
        // once the panel is open and mounted, by which point the outer
        // `<div t-ref="root">` -- always rendered, not conditional on
        // `state.open` -- is guaranteed to exist; the same
        // always-mounted-by-here guarantee `canvas.ts`'s own `attach()`
        // relies on for `scrollRef.el`.
        const rootEl = this.rootRef.el as HTMLElement;
        this.resizer = attachVerticalResize(handle, {
            getHeight: () => rootEl.getBoundingClientRect().height,
            setHeight: (height) => {
                rootEl.style.height = `${height}px`;
            },
            getMax: () => this.maxHeight(),
            min: MIN_HEIGHT,
            onDone: (height) => {
                this.state.height = Math.round(height);
                this.savePanel();
            },
        });
    }

    detachResizer(): void {
        if (this.resizer) {
            this.resizer.destroy();
            this.resizer = null;
        }
    }

    maxHeight(): number {
        const inner = this.rootRef.el && this.rootRef.el.parentElement;
        return inner ? Math.max(MIN_HEIGHT, inner.clientHeight - KEEP_BELOW) : Infinity;
    }

    /** A smaller window must not bury the tabs under the outline. */
    clampHeight(): void {
        const max = this.maxHeight();
        if (this.state.open && this.state.height > max) {
            this.state.height = max;
        }
    }

    savePanel(): void {
        this.prefs.height = this.state.height;
        this.prefs.open = this.state.open;
        savePrefs(this.prefs);
    }

    saveFolds(): void {
        const viewId = this.model.viewId;
        if (!viewId) {
            return;
        }
        // `viewId` (a `number`) is coerced to its string form by hand
        // below, matching exactly what a plain-object key already does to
        // it implicitly at runtime -- made explicit so `collapsed`/
        // `entries`/`finalEntries` can all carry one honest `string` key
        // type instead of a `number | string` one.
        const viewKey = String(viewId);
        const collapsed: Record<string, string[]> = { ...(this.prefs.collapsed || {}) };
        delete collapsed[viewKey];
        const entries: [string, string[]][] = Object.entries(collapsed).slice(
            -(REMEMBERED_VIEWS - 1),
        );
        // Explicitly typed, not left to plain array-literal inference:
        // `[viewKey, [...this.collapsed]]` would otherwise widen to a
        // non-tuple `(string | string[])[]`, which `Object.fromEntries`
        // only accepts through its loose, untyped fallback overload (the
        // same class of gap already tracked for `outline_tree.test.ts`'s
        // own `Object.fromEntries` call, TYPING.md's "Implemented so
        // far").
        const finalEntries: [string, string[]][] = [...entries, [viewKey, [...this.collapsed]]];
        this.prefs.collapsed = Object.fromEntries(finalEntries);
        savePrefs(this.prefs);
    }
}
