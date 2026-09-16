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
 * `drag.js` reads `data-token` off a row and lays its zones over the
 * list (`outline_zones.js`) beside the canvas's, through the provider
 * this component leaves on the model while it is mounted. The keyboard
 * makes the same moves without aim -- Alt with an arrow puts the focused
 * row before its neighbour, after it, out of its container or into the
 * one above -- and a right-click offers them by name, with Remove and
 * the label switch.
 *
 * Nothing a person does to the tree is remembered by token: tokens are
 * ordinals and the whole table is minted anew on every edit. A folded
 * container and the focused row are kept by path (`outline_tree.js`),
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
import { useService } from "@web/core/utils/hooks";
import { focusLabelRow } from "../drag";
import {
    flatten,
    moveTarget,
    nextFocus,
    pathAfterMove,
    pathKey,
    visibleChildren,
} from "../outline_tree";
import { ZoneLayer } from "../overlay";
import { attachVerticalResize } from "../split";
import { removeWithConfirm } from "./remove_flow";

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

/** What this browser remembers of the outline, or nothing. */
export function loadPrefs() {
    try {
        return JSON.parse(browser.localStorage.getItem(PREF_KEY) || "{}") || {};
    } catch {
        return {};
    }
}

export function savePrefs(prefs) {
    try {
        browser.localStorage.setItem(PREF_KEY, JSON.stringify(prefs));
    } catch {
        // A private window, storage blocked: the outline forgets, and
        // works the same.
    }
}

/** The items of the right-click menu, and what picking one does. */
export class OutlineMenu extends Component {
    static template = "app_builder_view.OutlineMenu";
    static props = { items: Array, onPick: Function, close: Function };

    pick(item) {
        if (item.disabled) {
            return;
        }
        this.props.close();
        this.props.onPick(item.key);
    }
}

export class Outline extends Component {
    static template = "app_builder_view.Outline";
    static components = { OutlineMenu };
    static props = { model: Object };

    setup() {
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
        // The paths folded shut, outside the state: a plain Set, and the
        // serial is what the rows are recomputed on.
        this.collapsed = new Set();
        this.state = useState({
            collapseSerial: 0,
            filter: "",
            // The row the keyboard is on, by path; the selection's row,
            // then the first, when none.
            focusPath: null,
            height: Number(prefs.height) || DEFAULT_HEIGHT,
            open: prefs.open !== false,
        });
        this.rowsCache = null;
        this.rowsKey = null;
        // Whether the focused row is to be focused again once the rows
        // have been drawn -- after a key press, after a move.
        this.pendingFocus = false;
        this.pendingScroll = null;
        this.resizer = null;
        this.resizeObserver = null;

        // The folds of the view being edited, from what is remembered.
        useEffect(
            (viewId) => {
                const folds = (prefs.collapsed && prefs.collapsed[viewId]) || [];
                this.collapsed = new Set(folds);
                this.state.collapseSerial += 1;
                this.state.focusPath = null;
            },
            () => [this.model.viewId]
        );
        // The canvas's selection: the row is opened up to and scrolled to.
        useEffect(
            (token) => {
                if (token) {
                    this.revealRow(token);
                }
            },
            () => [this.model.selection && this.model.selection.token]
        );
        // The list exists while the panel is open: the drag's provider
        // and the divider come and go with it.
        useEffect(
            (open) => {
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
            () => [this.state.open]
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
            this.resizeObserver && this.resizeObserver.disconnect();
            this.unregisterDrag();
            this.detachResizer();
        });
    }

    // -- the rows -------------------------------------------------------------

    /** The rows, laid out again only when the table, the folds or the filter change. */
    get rows() {
        const canvas = toRaw(this.model.canvas);
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

    get selectedToken() {
        return this.model.selection ? this.model.selection.token : null;
    }

    get hoverToken() {
        return this.model.hover;
    }

    get canWrite() {
        return this.model.canWrite;
    }

    /** The path of the row that takes the Tab key: the focused, the selected, the first. */
    get focusKey() {
        const rows = this.rows;
        if (this.state.focusPath && rows.some((row) => row.key === this.state.focusPath)) {
            return this.state.focusPath;
        }
        const selected = this.selectedToken && rows.find((row) => row.token === this.selectedToken);
        if (selected) {
            return selected.key;
        }
        return rows.length ? rows[0].key : null;
    }

    get toggleTitle() {
        return this.state.open ? _t("Hide the outline") : _t("Show the outline");
    }

    caretLabel(entry) {
        return entry.expanded ? _t("Fold") : _t("Unfold");
    }

    hiddenTitle(entry) {
        return entry.badges.hidden === "groups"
            ? _t("Hidden for your groups")
            : _t("Invisible");
    }

    /** The row element at a path, or `null`. */
    rowEl(path) {
        const list = this.listRef.el;
        if (!list || !path) {
            return null;
        }
        return (
            [...list.querySelectorAll(".o_studio_outline_row")].find(
                (el) => el.dataset.path === path
            ) || null
        );
    }

    rowElOf(token) {
        const list = this.listRef.el;
        return list
            ? [...list.querySelectorAll(".o_studio_outline_row")].find(
                  (el) => el.dataset.token === token
              ) || null
            : null;
    }

    /** The row at a path, as laid out. */
    rowAt(path) {
        return this.rows.find((row) => row.key === path) || null;
    }

    // -- clicks ---------------------------------------------------------------

    /**
     * A click selects, and puts the keyboard on the row. The focus is
     * taken by hand: the drag hook prevents the default of a press on
     * anything it could pick up, and a row is one, so the browser gives
     * the row no focus of its own.
     */
    onRowClick(entry, ev) {
        this.state.focusPath = entry.key;
        if (ev && ev.currentTarget && ev.currentTarget.focus) {
            ev.currentTarget.focus();
        }
        this.model.reveal(entry.token);
    }

    onRowDblClick(entry) {
        this.model.reveal(entry.token);
        const root = this.rootRef.el && this.rootRef.el.closest(".o_studio_console");
        focusLabelRow(root || document.body);
    }

    onRowEnter(entry) {
        this.model.hoverAt(entry.token);
    }

    onRowLeave() {
        this.model.hoverAt(null);
    }

    onToggle(entry, ev) {
        ev.stopPropagation();
        this.toggleCollapsed(entry);
    }

    onContextMenu(entry, ev) {
        ev.preventDefault();
        ev.stopPropagation();
        this.state.focusPath = entry.key;
        if (ev.currentTarget && ev.currentTarget.focus) {
            ev.currentTarget.focus();
        }
        this.openMenu(entry, ev.currentTarget);
    }

    openMenu(entry, target) {
        if (this.menu.isOpen) {
            this.menu.close();
        }
        this.menu.open(target, {
            items: this.menuItems(entry),
            onPick: (key) => this.runMenu(entry, key),
        });
    }

    /** What the menu offers for a row, each item said to be possible or not. */
    menuItems(entry) {
        const nodes = this.model.nodes;
        const node = entry.node;
        const write = this.canWrite;
        const can = (direction) => Boolean(write && moveTarget(nodes, entry.token, direction));
        const siblings = node.parent ? visibleChildren(nodes, node.parent) : [];
        const above = siblings[siblings.indexOf(entry.token) - 1];
        const items = [
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

    async runMenu(entry, key) {
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
                return this.model.setLabelShown(entry.token, !entry.node.label.shown);
            case "reveal":
                return this.model.reveal(entry.token);
            case "remove":
                return this.remove(entry);
            default:
                return undefined;
        }
    }

    // -- the keyboard ---------------------------------------------------------

    onKeyDown(ev) {
        const rows = this.rows;
        // The row the key lands on is the one that has the focus, which
        // the roving index follows; the index alone when none has it.
        const focused = ev.target && ev.target.closest && ev.target.closest(".o_studio_outline_row");
        let index = focused ? rows.findIndex((row) => row.token === focused.dataset.token) : -1;
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
            const direction = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "out", ArrowRight: "in" }[
                ev.key
            ];
            this.move(entry, direction);
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
                this.remove(entry);
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

    onFilterKeyDown(ev) {
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
    focusRow(entry) {
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
    async move(entry, direction) {
        if (!this.canWrite) {
            return undefined;
        }
        const target = moveTarget(this.model.nodes, entry.token, direction);
        if (!target) {
            return undefined;
        }
        const node = entry.node;
        const payload =
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
    afterMove() {
        const row = this.rowAt(this.state.focusPath);
        const selected = this.selectedToken;
        if (row && selected && row.token !== selected) {
            const node = this.model.nodes[selected];
            if (node && node.tag === row.node.tag) {
                this.model.select(row.token);
            }
        }
    }

    async remove(entry) {
        if (!this.canWrite) {
            return undefined;
        }
        return removeWithConfirm({ model: this.model, dialog: this.dialog, token: entry.token });
    }

    // -- folds ----------------------------------------------------------------

    toggleCollapsed(entry) {
        this.setCollapsed(entry, !this.collapsed.has(entry.key));
    }

    setCollapsed(entry, collapsed) {
        if (collapsed) {
            this.collapsed.add(entry.key);
        } else {
            this.collapsed.delete(entry.key);
        }
        this.state.collapseSerial += 1;
        this.saveFolds();
    }

    /** Open every container above `token`; whether any was shut. */
    expandAncestors(token) {
        const nodes = this.model.nodes;
        let changed = false;
        for (let cursor = nodes[token] && nodes[token].parent; cursor && nodes[cursor]; ) {
            const key = pathKey(nodes, cursor);
            if (this.collapsed.delete(key)) {
                changed = true;
            }
            cursor = nodes[cursor].parent;
        }
        if (changed) {
            this.state.collapseSerial += 1;
            this.saveFolds();
        }
        return changed;
    }

    /** Open one container, for the drag resting on its row. */
    expand(token) {
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

    isCollapsed(token) {
        const nodes = this.model.nodes;
        return Boolean(nodes[token] && this.collapsed.has(pathKey(nodes, token)));
    }

    // -- the canvas's selection -----------------------------------------------

    revealRow(token) {
        this.expandAncestors(token);
        this.pendingScroll = token;
        this.scrollPending();
    }

    scrollPending() {
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
    afterPatch() {
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
        if (active !== el && (!active || active === document.body || (list && list.contains(active)))) {
            el.focus();
        }
    }

    // -- the drag -------------------------------------------------------------

    registerDrag() {
        const list = this.listRef.el;
        if (!list) {
            return;
        }
        this.unregisterDrag();
        this.zoneLayer = new ZoneLayer(list);
        this.model.outlineDrag = markRaw({
            el: list,
            layer: this.zoneLayer,
            rows: () => [...list.querySelectorAll(".o_studio_outline_row")],
            indentOf: (depth) => OUTLINE_PAD + depth * OUTLINE_INDENT,
            isCollapsed: (token) => this.isCollapsed(token),
            expand: (token) => this.expand(token),
        });
    }

    unregisterDrag() {
        if (this.zoneLayer) {
            this.zoneLayer.destroy();
            this.zoneLayer = null;
        }
        if (this.model.outlineDrag) {
            this.model.outlineDrag = null;
        }
    }

    // -- the panel ------------------------------------------------------------

    toggleOpen() {
        this.state.open = !this.state.open;
        this.savePanel();
    }

    attachResizer() {
        const handle = this.dividerRef.el;
        if (!handle) {
            return;
        }
        this.detachResizer();
        this.resizer = attachVerticalResize(handle, {
            getHeight: () => this.rootRef.el.getBoundingClientRect().height,
            setHeight: (height) => {
                this.rootRef.el.style.height = `${height}px`;
            },
            getMax: () => this.maxHeight(),
            min: MIN_HEIGHT,
            onDone: (height) => {
                this.state.height = Math.round(height);
                this.savePanel();
            },
        });
    }

    detachResizer() {
        if (this.resizer) {
            this.resizer.destroy();
            this.resizer = null;
        }
    }

    maxHeight() {
        const inner = this.rootRef.el && this.rootRef.el.parentElement;
        return inner ? Math.max(MIN_HEIGHT, inner.clientHeight - KEEP_BELOW) : Infinity;
    }

    /** A smaller window must not bury the tabs under the outline. */
    clampHeight() {
        const max = this.maxHeight();
        if (this.state.open && this.state.height > max) {
            this.state.height = max;
        }
    }

    savePanel() {
        this.prefs.height = this.state.height;
        this.prefs.open = this.state.open;
        savePrefs(this.prefs);
    }

    saveFolds() {
        const viewId = this.model.viewId;
        if (!viewId) {
            return;
        }
        const collapsed = { ...(this.prefs.collapsed || {}) };
        delete collapsed[viewId];
        const entries = Object.entries(collapsed).slice(-(REMEMBERED_VIEWS - 1));
        this.prefs.collapsed = Object.fromEntries([...entries, [viewId, [...this.collapsed]]]);
        savePrefs(this.prefs);
    }
}
