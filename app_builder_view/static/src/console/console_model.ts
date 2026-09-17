/** @odoo-module **/
/**
 * What the console knows, and every call it makes.
 *
 * One object holds the editing context, the canvas payload, the selection
 * and the status pill, and every RPC the console makes goes through a
 * method here. The components render this and call it; none of them talks
 * to the server or keeps state of its own beyond what is on screen. That is
 * what lets the canvas, the sidebar and the top bar agree after every edit
 * without telling each other: they all read the one canvas.
 *
 * Three rules every mutation follows, in `_mutate`:
 *
 *  - **the version travels with the gesture.** Every descriptor sent is a
 *    token plus the version of the arch it was minted on, and every mutator
 *    is told the version it should find. A stale one comes back as
 *    `StudioStaleView`, which is not an error the user can act on: the
 *    canvas is reloaded silently and they are told to try again.
 *  - **the canvas is replaced, never patched.** A mutator that hands back
 *    a canvas is believed; one that does not is followed by `canvas()`.
 *    Either way the whole payload is swapped, and the selection is carried
 *    across by token, then by name, then dropped.
 *  - **a refusal is a sentence.** Anything else the server refuses is shown
 *    as the server said it, as a toast, and nothing here rethrows it: the
 *    caller has nothing to add.
 *
 * A new field takes one of two roads, and the model keeps both behind one
 * gesture. On a model no package defines in Python the field is an
 * `ir.model.fields` row, live the moment `drop_at` returns. On a
 * Python-owned model it is a class attribute waiting for an Apply, so the
 * drop stages it on this user's `studio.model.draft` and the canvas draws a
 * ghost where it will land. The draft itself -- what is pending, what the
 * reload will cost, Apply and Discard -- belongs to the shell
 * (`shell/draft_model.ts`): it is per model, and the pill that counts it
 * sits on every pane. The delegations here keep the sidebar's vocabulary
 * (`model.draft`, `model.updateStaged`...) and refresh the canvas after
 * each, which is this pane's business and not the draft's.
 *
 * This is the Views pane's model. The shell owns the package in the top
 * bar, the model on the crumb and the model's draft; this reads them
 * through `shell` and owns everything about one view: its canvas, its
 * selection, its history, its palette.
 *
 * No Owl in here. Reactivity is the caller's business (`useState` on the
 * instance); this class is plain so it can be tested and ported as it is.
 */

import { markRaw } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import * as compat from "./compat";
import { messageOf } from "./shell/draft_model";
import type { ApplyResult, DraftFieldWithPending, DraftModel } from "./shell/draft_model";
import type { OpenViewTarget } from "./shell/shell_model";
import type {
    CanvasPackageSummary,
    CanvasPayload,
    CanvasPendingEntry,
    DescribedTarget,
    DescribeNodeAnswer,
    DragPayload,
    DropSuccessResult,
    FieldDefinition,
    FieldService,
    HistoryEntry,
    NodeTable,
    NotificationService,
    OdooRpcError,
    OrmService,
    PaneActivity,
    PaneModel,
    StudioNode,
    Token,
    ZonePosition,
} from "./types";
import type {
    AddableFieldEntry,
    AddableViewTypeEntry,
    DraftFieldJSON,
    DraftPayload,
    EditingContext,
    FieldTypeEntry,
    FieldTypeRawEntry,
    InverseOptions,
    NewFieldPlan,
    OperationResult,
    PendingChangeJSON,
    ResolveRelatedResult,
    SearchElements,
    ViewOfEntry,
} from "./wire";

/**
 * Picker keys whose field cannot be made from a label alone, for a server
 * that does not say: a relation needs a model, a selection its values, a
 * related field its chain. `field_types_for` answers `needs_dialog` per
 * entry and wins when it is there.
 */
const DIALOG_TYPES = new Set([
    "many2one",
    "one2many",
    "many2many",
    "tags",
    "lines",
    "selection",
    "reference",
    "related",
]);

/**
 * Spec keys a field created live cannot carry: they are class attributes
 * with no `ir.model.fields` column (`manualfield.UNSUPPORTED_LIVE`), and
 * the editor never offers them in live mode. Stripped here too, so a
 * value that reached the payload some other way is not the whole drop's
 * refusal.
 */
const LIVE_UNSUPPORTED = ["default", "compute", "compute_body", "depends", "digits"];

/** `env.services`, plus the one bus method `_afterSearchChange` reaches
 * through `compat.clearViewCaches` -- the narrow facade this file itself
 * calls through (TYPING.md Phase 2c, `console/odoo.ts`, is where every
 * file's own facade like this one eventually merges). */
interface ConsoleEnv {
    services: {
        orm: OrmService;
        notification: NotificationService;
        field: FieldService;
    };
    bus: { trigger: (name: string) => void };
}

/**
 * What `ConsoleModel` reads off the shell it is handed: the package in the
 * top bar, the model's label on the crumb, the model's draft, and the one
 * call that hands the shell what the editing context learned. A narrow
 * interface rather than `StudioShell` itself, mirroring `DraftModelOwner`
 * (`shell/draft_model.ts`) -- this class's own docstring makes the same
 * promise DraftModel's does ("so it can be tested and ported as it is"),
 * which a constructor pinned to the real, thirty-member `StudioShell`
 * class would not keep: a unit test would have to stub every member
 * `ConsoleModel` never reads just to construct one. The real `StudioShell`
 * satisfies this structurally without any change on its side.
 */
export interface ConsoleModelOwner {
    packageId: number | false;
    modelLabel: string;
    draft: DraftModel;
    learnContext(context: EditingContext): Promise<void>;
}

/** `this.params`: what `open()` was told, filled in by the server where
 * it was not (`editing_context`). */
interface ConsoleViewParams {
    view_id: number | false;
    model: string | false;
    view_type: string | false;
    res_id: number | false;
}

/** `this.view`'s own answer -- `canvas().view`, `editing_context().view`,
 * or neither yet: every field only as certain as the least of the three. */
interface ViewSummary {
    id?: number;
    name?: string;
    type?: string;
    model?: string | false;
    mode?: string;
    js_class?: string | null;
}

/** The current selection: a token plus the node it named at the moment it
 * was selected (`select`, `_replaceCanvas`). */
interface Selection {
    token: Token;
    node: StudioNode;
}

/** What is being dragged over the canvas, for the status pill's caption. */
interface DragState {
    label: string;
    caption: string;
}

/**
 * A drop held for the palette to finish: a Button tile with no action yet,
 * or a field tile of a type that needs its definition first. One shape for
 * both -- `ttype`/`label` are only ever set on a field target -- so
 * `_carryTarget` can read and write `this.buttonTarget`/`this.fieldTarget`
 * through one key without TS needing two incompatible property types on
 * `this` (see `_carryTarget`'s own note).
 */
interface DropTarget {
    token: Token;
    position: ZonePosition;
    arch_version: string | null;
    serial: number;
    ttype?: string;
    label?: string;
}

/** `{kind: "node", token, arch_version}` -- what every mutator takes.
 * `token` is `Token | null` since `anchorToken` (the root's own fallback)
 * can be: nothing invents a guarantee the caller does not already have. */
interface NodeDescriptor {
    kind: "node";
    token: Token | null;
    arch_version: string | null;
}

type MutateOptions = { select?: Token | null; silent?: boolean; prefix?: string };

/**
 * Fields `_mutate` itself inspects on a raw RPC result, regardless of what
 * its caller declares the settled type `T` to be -- every mutator's server
 * method may answer `{stale: true, canvas}` instead of its own documented
 * shape (`drop_at`'s own three return sites, `wire.ts`'s `DropSuccessResult`
 * doc), and `_mutate` strips that case out before its caller ever sees a
 * result, so `T` only has to describe what survives past it. Read through
 * a cast on the opaque `result: T`, never through `T` itself -- the one
 * place in this file that peeks at a shape wider than what it declares.
 */
interface RawMutateFields {
    stale?: boolean;
    canvas?: CanvasPayload;
    draft?: DraftPayload;
    created_name?: string;
    select?: Token;
}

export class ConsoleModel implements PaneModel {
    env: ConsoleEnv;
    orm: OrmService;
    notification: NotificationService;
    shell: ConsoleModelOwner;
    params: ConsoleViewParams;

    context: EditingContext | null;
    canvas: CanvasPayload | null;
    selection: Selection | null;
    /** Counts the times something was *selected* -- a click, a drop --
     * as opposed to carried across a remount; the sidebar opens the
     * properties on the former and not on the latter. */
    selectionSerial: number;
    hover: Token | null;
    /** Bumped by `reveal`: the canvas brings `revealToken` on screen --
     * its page switched to, its element scrolled to -- on the bump. */
    revealSerial: number;
    revealToken: Token | null;
    /** Set by the outline while it is mounted: how the drag reaches
     * its rows and its zone layer (`sidebar/outline.js`), read by
     * `drag.js` when a drag starts. `null` when there is no outline. */
    outlineDrag: unknown;
    drag: DragState | null;
    /** Where a Button tile was dropped: the tile needs an action before
     * anything is written, so the drop is held here and the palette
     * asks for the rest, then sends it to this spot. Held with the
     * version of the arch its token was minted on, like any descriptor:
     * the canvas may be replaced while the palette is still asking. */
    buttonTarget: DropTarget | null;
    /** Where a field tile that needs its definition first was dropped: a
     * relation without a model, a selection without values, is not a
     * field yet, so the drop is held here -- the same way, with the
     * same version -- while the field editor asks for the rest. */
    fieldTarget: DropTarget | null;
    busy: boolean;
    status: string;
    statusError: string;
    showInvisible: boolean;
    /** The notebook page the user is looking at, so a remount lands on it. */
    activePage: unknown;
    palette: AddableFieldEntry[];
    addable: AddableViewTypeEntry[];
    fieldPlan: NewFieldPlan | null;
    /** The picker's entries for this model, each saying whether it can
     * be made live here and whether it needs the editor first. */
    fieldTypes: FieldTypeEntry[];
    /** Bumped when the model's fields changed under an unchanged arch
     * -- a manual field renamed -- so the canvas remounts on it. */
    renderSerial: number;
    serverActions: { id: number; name: string }[];
    search: SearchElements | null;
    /** Bumped after every search-view edit: the host list previewing the
     * search view loads it the ordinary way and has to be remounted. */
    searchSerial: number;
    descriptions: Record<Token, DescribedTarget>;
    /** Set by the shell itself after the first `open()`. */
    opened: boolean;

    constructor(env: ConsoleEnv, shell: ConsoleModelOwner) {
        this.env = env;
        this.orm = env.services.orm;
        this.notification = env.services.notification;
        this.shell = shell;
        this.params = { view_id: false, model: false, view_type: false, res_id: false };
        this.opened = false;
        this.context = null;
        this.canvas = null;
        this.selection = null;
        this.selectionSerial = 0;
        this.hover = null;
        this.revealSerial = 0;
        this.revealToken = null;
        this.outlineDrag = null;
        this.drag = null;
        this.buttonTarget = null;
        this.fieldTarget = null;
        this.busy = false;
        this.status = "saved";
        this.statusError = "";
        this.showInvisible = false;
        this.activePage = null;
        this.palette = [];
        this.addable = [];
        this.fieldPlan = null;
        this.fieldTypes = [];
        this.renderSerial = 0;
        this.serverActions = [];
        this.search = null;
        this.searchSerial = 0;
        this.descriptions = markRaw({});
        this._reset();
    }

    /** Everything about one view, back to nothing: `open` starts here. */
    _reset(): void {
        this.context = null;
        this.canvas = null;
        this.selection = null;
        this.selectionSerial = 0;
        this.hover = null;
        this.revealSerial = 0;
        this.revealToken = null;
        this.outlineDrag = null;
        this.drag = null;
        this.buttonTarget = null;
        this.fieldTarget = null;
        this.busy = false;
        this.status = "saved";
        this.statusError = "";
        this.showInvisible = false;
        this.activePage = null;
        this.palette = [];
        this.addable = [];
        this.fieldPlan = null;
        this.fieldTypes = [];
        this.renderSerial = 0;
        this.serverActions = [];
        this.search = null;
        this.searchSerial = 0;
        this.descriptions = markRaw({});
    }

    // -- what the shell owns ----------------------------------------------

    /** The package edits are recorded into: the one in the top bar. */
    get packageId(): number | false {
        return this.shell.packageId;
    }

    get modelLabel(): string {
        return this.shell.modelLabel;
    }

    /** The shell's draft on this model; see `shell/draft_model.ts`. */
    get draftModel(): DraftModel {
        return this.shell.draft;
    }

    get draft(): DraftPayload | null {
        return this.draftModel.draft;
    }

    get applying(): boolean {
        return this.draftModel.applying;
    }

    /** What the status pill reads, whichever pane is on. */
    get activity(): PaneActivity {
        return {
            busy: this.busy,
            status: this.status,
            error: this.statusError,
            drag: this.drag,
            applying: this.applying,
        };
    }

    // -- reading ------------------------------------------------------------

    get view(): ViewSummary {
        return (this.canvas && this.canvas.view) || (this.context && this.context.view) || {};
    }

    get viewId(): number | false {
        return this.view.id || this.params.view_id;
    }

    get viewType(): string | false | undefined {
        return this.view.type;
    }

    get modelName(): string | false | undefined {
        return this.view.model;
    }

    get editableAs(): "canvas" | "report" | "search_lists" {
        return (this.canvas && this.canvas.editable_as) || "canvas";
    }

    get archVersion(): string | null {
        return this.canvas ? this.canvas.arch_version : null;
    }

    get nodes(): NodeTable {
        return (this.canvas && this.canvas.nodes) || {};
    }

    get root(): Token | null {
        return this.canvas ? this.canvas.root : null;
    }

    get history(): { undo: HistoryEntry[]; redo: HistoryEntry[] } {
        return (this.canvas && this.canvas.history) || { undo: [], redo: [] };
    }

    get package(): CanvasPackageSummary | null {
        return (this.canvas && this.canvas.package) || null;
    }

    /** Whether an edit can be recorded at all. */
    get canWrite(): boolean {
        return Boolean(this.packageId) && !this.busy && !this.applying;
    }

    get selectedNode(): StudioNode | null {
        if (!this.selection) {
            return null;
        }
        return this.nodes[this.selection.token] ?? null;
    }

    // -- the draft ----------------------------------------------------------

    /** Whether a new field here is a class attribute waiting for an Apply. */
    get pythonOwned(): boolean {
        return Boolean(this.context && this.context.python_owned);
    }

    /** The draft the console addresses, from whichever answer named it last. */
    get draftId(): number | false {
        return this.draftModel.draftId || (this.canvas && this.canvas.draft_id) || false;
    }

    /** The ghosts the canvas carries. */
    get pending(): CanvasPendingEntry[] {
        return (this.canvas && this.canvas.pending) || [];
    }

    /**
     * What the pill counts. The draft's own count when it has been loaded
     * -- it knows about removals and edits the canvas has no ghost for --
     * else the ghosts on the canvas.
     */
    get pendingCount(): number {
        if (this.draft) {
            return this.draft.change_count || 0;
        }
        return this.pending.length;
    }

    /** The staged changes, as the draft lists them for its tray. */
    get pendingChanges(): PendingChangeJSON[] {
        return this.draftModel.pendingChanges;
    }

    get draftErrors(): string[] {
        return this.draftModel.errors;
    }

    /** `inproc` or `manual`: what an Apply costs on this server. */
    get reloadMode(): string | false {
        return this.draftModel.reloadMode || (this.context && this.context.reload_mode) || false;
    }

    /** Why Apply is not on offer right now, or `""` when it is. */
    get applyBlocker(): string {
        if (!this.pendingCount) {
            return String(_t("Nothing is pending."));
        }
        return this.draftModel.applyBlocker;
    }

    get canApply(): boolean {
        return !this.applying && !this.busy && !this.applyBlocker;
    }

    /** The staged definition of a pending field, from the draft. */
    stagedField(name: string): DraftFieldJSON | null {
        return this.draftModel.stagedField(name);
    }

    /** The picker entry for a key such as `char` or `priority`. */
    fieldTypeEntry(key: string | undefined): FieldTypeEntry | null {
        return this.fieldTypes.find((entry) => entry.value === key) || null;
    }

    /**
     * Whether a tile of this type opens the editor before anything is sent.
     * The server's word when it has one, else the list above.
     */
    needsDialog(key: string | undefined): boolean {
        const entry = this.fieldTypeEntry(key);
        if (entry && entry.needs_dialog !== undefined) {
            return Boolean(entry.needs_dialog);
        }
        return Boolean(key) && DIALOG_TYPES.has(key as string);
    }

    /** The node a click-to-add lands on: the selection, else the root. */
    get anchorToken(): Token | null {
        if (this.selection && this.nodes[this.selection.token]) {
            return this.selection.token;
        }
        return this.root;
    }

    /** `{kind: "node", token, arch_version}` -- what every mutator takes. */
    descriptor(token: Token | null): NodeDescriptor {
        return { kind: "node", token, arch_version: this.archVersion };
    }

    /** The label the selection frame shows: "Field · Email", "Tab · Notes". */
    tagFor(token: Token): string {
        const node = this.nodes[token];
        if (!node) {
            return "";
        }
        const kind = KIND_LABELS[node.kind] || _t("Element");
        // The table falls back to the technical name when the arch gives
        // no string. A field's own label reads better than that, and a
        // generated group name -- `studio_group_a1b2` -- is not a name a
        // person gave, so a container without a string is just its kind.
        let name: string | null = node.string && node.string !== node.name ? node.string : null;
        if (!name && node.field) {
            name = node.field.string;
        }
        if (!name && node.pending) {
            name = node.pending.string || node.pending.name;
        }
        if (!name && NAMED_KINDS.includes(node.kind)) {
            name = node.name;
        }
        return name && node.kind !== "root" ? `${kind} · ${name}` : String(kind);
    }

    // -- loading ------------------------------------------------------------

    /**
     * Open a view: `{view_id, model, view_type, res_id}`, any of which the
     * server fills in when missing. Everything about the previous view is
     * dropped first; the shell keeps the package, the model and the draft.
     */
    async open(target: OpenViewTarget = {}): Promise<void> {
        this._reset();
        this.params = {
            view_id: target.view_id || false,
            model: target.model || target.res_model || false,
            view_type: target.view_type || false,
            res_id: target.res_id || false,
        };
        return this.load();
    }

    /** The view again, after another pane may have changed the model. */
    async reactivate(): Promise<void> {
        if (!this.canvas) {
            return this.load();
        }
        await this.loadContext();
        await this.refresh({ keepSelection: true });
        await this.loadDraft();
        return undefined;
    }

    async load(): Promise<void> {
        await this.loadContext();
        await this.refresh({ keepSelection: false });
        // The field plan is asked for every view, not only those with a
        // rendering: it is what says why a report cannot take a new field.
        const loads: Promise<unknown>[] = [this.loadFieldPlan(), this.loadDraft()];
        if (this.editableAs === "canvas" && this.modelName) {
            loads.push(
                this.loadPalette(),
                this.loadAddable(),
                this.loadServerActions(),
                this.loadFieldTypes(),
            );
        } else if (this.editableAs === "search_lists") {
            loads.push(this.loadSearch(), this.loadAddable());
        }
        await Promise.all(loads);
    }

    async loadContext(): Promise<void> {
        this.context = markRaw(
            await this.orm.call<EditingContext>(
                "studio.view.editor",
                "editing_context",
                [this.viewId || this.params.view_id || false],
                { model: this.params.model, view_type: this.params.view_type },
            ),
        );
        // The shell learns the model, the package to suggest and the
        // draft that may exist from the same answer.
        await this.shell.learnContext(this.context);
    }

    /**
     * The picker's entries for this model, each with `live` and
     * `needs_dialog`. A server without `field_types_for` -- an older one
     * -- still sent the catalogue with the context, and the two flags are
     * then worked out here: live where nothing is Python-owned, the
     * editor for the types that cannot be made from a label alone.
     */
    async loadFieldTypes(): Promise<void> {
        if (!this.modelName) {
            this.fieldTypes = [];
            return;
        }
        let entries: FieldTypeRawEntry[];
        try {
            entries = await this.orm.call<FieldTypeRawEntry[]>(
                "studio.view.editor",
                "field_types_for",
                [this.modelName],
            );
        } catch (err) {
            if (!(err as OdooRpcError)?.data) {
                throw err;
            }
            entries = (this.context && this.context.field_types) || [];
        }
        const pythonOwned = this.pythonOwned;
        this.fieldTypes = markRaw(
            entries.map((entry) => ({
                ...entry,
                live: entry.live !== undefined ? entry.live : entry.enabled && !pythonOwned,
                needs_dialog:
                    entry.needs_dialog !== undefined
                        ? entry.needs_dialog
                        : DIALOG_TYPES.has(entry.value),
            })),
        );
    }

    /**
     * This user's draft on the model, when there is one -- the shell's,
     * read again. A canvas that named a draft the shell does not know of
     * yet hands the id over first.
     */
    async loadDraft(): Promise<DraftPayload | null> {
        if (!this.draftModel.draftId && this.canvas && this.canvas.draft_id) {
            this.draftModel.setHints({
                draft_id: this.canvas.draft_id,
                reload_mode: this.reloadMode,
            });
        }
        return this.draftModel.load();
    }

    _canvasOptions(): {
        show_invisible: boolean;
        res_id: number | false;
        package_id: number | false;
        draft_id: number | false;
    } {
        return {
            show_invisible: this.showInvisible,
            res_id: this.params.res_id || false,
            package_id: this.packageId || false,
            draft_id: (this.context && this.context.draft_id) || false,
        };
    }

    /**
     * Reload the canvas from the server and carry the selection across.
     *
     * `keepSelection: false` starts from nothing selected -- the first load,
     * a switch to another view.
     */
    async refresh({ keepSelection = true }: { keepSelection?: boolean } = {}): Promise<void> {
        const payload = await this._fetchCanvas();
        this._replaceCanvas(payload, { keepSelection });
    }

    _fetchCanvas(options: Record<string, unknown> = {}): Promise<CanvasPayload> {
        return this.orm.call<CanvasPayload>("studio.view.editor", "canvas", [
            this.viewId,
            { ...this._canvasOptions(), ...options },
        ]);
    }

    _replaceCanvas(
        payload: CanvasPayload,
        {
            keepSelection = true,
            select = null,
        }: { keepSelection?: boolean; select?: Token | null } = {},
    ): void {
        const previousNodes = this.nodes;
        const previous = this.selectedNode;
        const oldToken = this.selection ? this.selection.token : null;
        const before = this.canvas;
        this.canvas = markRaw(payload);
        if (
            before &&
            before.arch_version === payload.arch_version &&
            before.arch !== payload.arch
        ) {
            // The version hashes the arch the server edits, and a ghost
            // is spliced into the copy it renders: a staged field comes
            // and goes under one version, and the canvas has to remount
            // on the arch it is actually given.
            this.renderSerial += 1;
        }
        this.descriptions = markRaw({});
        this.hover = null;
        const selectNode = select ? this.nodes[select] : undefined;
        if (select && selectNode) {
            this.selection = null;
            this.select(select);
        } else if (keepSelection && previous) {
            const token = this._findAgain(previous, oldToken, previousNodes);
            const node = token ? this.nodes[token] : undefined;
            this.selection = token && node ? { token, node } : null;
        } else {
            this.selection = null;
        }
        this._carryTarget(
            "buttonTarget",
            previousNodes,
            String(_t("This view changed; drop the button again.")),
        );
        this._carryTarget(
            "fieldTarget",
            previousNodes,
            String(_t("This view changed; drop the field again.")),
        );
    }

    /**
     * Keep a held drop across a replaced canvas, or let it go.
     *
     * The target names a node by a token minted on the canvas that was just
     * swapped out, and tokens are ordinals in document order: after another
     * drop, an undo, anyone's edit, the same token may name the node one
     * slot over. So the node is looked for again, and the target is kept
     * only when it is found with certainty; otherwise the drop is
     * forgotten and the user is told to make it again, rather than have it
     * land beside the wrong node with a version the server has no reason
     * to refuse. The Button tile's drop and a field tile's are held the
     * same way, under `key`.
     */
    _carryTarget(
        key: "buttonTarget" | "fieldTarget",
        previousNodes: NodeTable,
        notice: string,
    ): void {
        const target = this[key];
        if (!target || target.arch_version === this.archVersion) {
            return;
        }
        const previous = previousNodes[target.token];
        const token = previous ? this._placeOf(previous, target.token, previousNodes) : null;
        if (token) {
            this[key] = { ...target, token, arch_version: this.archVersion };
            return;
        }
        this[key] = null;
        this.notification.add(notice, { type: "info" });
    }

    /**
     * The token `previous` has on the current canvas, or `null` when that
     * is not certain. A named node is the one node of its tag and name
     * under a parent of the same tag and name -- a subview repeats the
     * names of the form it sits in, and its parent tells them apart. A
     * nameless node has nothing to be known by but its place, so it is
     * only itself again when its token still names a node of its tag at
     * its index under such a parent: nothing before it moved. Stricter
     * than `_findAgain`, whose guess is fine for a selection and would be
     * written here.
     */
    _placeOf(previous: StudioNode, oldToken: Token, previousNodes: NodeTable): Token | null {
        const oldParent = previous.parent ? previousNodes[previous.parent] : null;
        const alike = (
            node: StudioNode | null | undefined,
            other: StudioNode | null | undefined,
        ): boolean =>
            Boolean(node) === Boolean(other) &&
            (!node || !other || (node.tag === other.tag && node.name === other.name));
        const same = (node: StudioNode | null | undefined): boolean =>
            alike(node, previous) &&
            alike(node && node.parent ? this.nodes[node.parent] : null, oldParent);
        if (previous.name) {
            const found = Object.entries(this.nodes).filter(([, node]) => same(node));
            return found.length === 1 ? (found[0]?.[0] ?? null) : null;
        }
        const node = this.nodes[oldToken];
        return same(node) && node && node.index === previous.index ? oldToken : null;
    }

    /**
     * The token a node has after a re-stamp: the same one when it still
     * names the same node, else the first node of the same tag and name,
     * else the node at the same place under a parent of the same name.
     */
    _findAgain(
        previous: StudioNode,
        oldToken: Token | null,
        previousNodes: NodeTable,
    ): Token | null {
        const same = (node: StudioNode | undefined): node is StudioNode =>
            node ? node.tag === previous.tag : false;
        const nodes = this.nodes;
        const current = oldToken ? nodes[oldToken] : undefined;
        if (same(current) && current.name === previous.name) {
            return oldToken;
        }
        if (previous.name) {
            for (const [token, node] of Object.entries(nodes)) {
                if (same(node) && node.name === previous.name) {
                    return token;
                }
            }
        }
        const oldParent = previous.parent ? previousNodes[previous.parent] : null;
        for (const [token, node] of Object.entries(nodes)) {
            if (!same(node) || node.index !== previous.index) {
                continue;
            }
            const parent = node.parent ? nodes[node.parent] : null;
            if (
                (!oldParent && !parent) ||
                (oldParent &&
                    parent &&
                    parent.tag === oldParent.tag &&
                    parent.name === oldParent.name)
            ) {
                return token;
            }
        }
        return null;
    }

    // -- selecting ----------------------------------------------------------

    select(token: Token | null): void {
        const node = token ? this.nodes[token] : undefined;
        if (!token || !node) {
            this.selection = null;
            return;
        }
        if (this.selection && this.selection.token === token) {
            return;
        }
        this.selection = { token, node };
        this.selectionSerial += 1;
    }

    clearSelection(): void {
        this.selection = null;
    }

    /**
     * Select `token` and ask the canvas to bring it on screen: the page
     * it is on switched to, its element scrolled into view. What the
     * outline does on a click, where the row may stand for something the
     * canvas is not showing.
     */
    reveal(token: Token | null): void {
        this.select(token);
        if (token && this.nodes[token]) {
            this.revealToken = token;
            this.revealSerial += 1;
        }
    }

    hoverAt(token: Token | null): void {
        if (this.hover !== token) {
            this.hover = token || null;
        }
    }

    rememberPage(page: unknown): void {
        this.activePage = page;
    }

    // -- dragging -----------------------------------------------------------

    beginDrag(label: string): void {
        this.drag = { label: label || "", caption: "" };
    }

    setDragCaption(caption: string): void {
        if (this.drag && this.drag.caption !== caption) {
            this.drag.caption = caption || "";
        }
    }

    endDrag(): void {
        this.drag = null;
    }

    /**
     * Show or hide the invisible elements.
     *
     * The flag flips when the canvas rendered with it arrives, not before:
     * the two are one change to the canvas component, which remounts the
     * View on the flag and would otherwise remount it on the old arch --
     * and, the version being that of the arch alone, never on the new one.
     */
    async toggleInvisible(): Promise<void> {
        const wanted = !this.showInvisible;
        const payload = await this._guard(() => this._fetchCanvas({ show_invisible: wanted }));
        if (payload === undefined) {
            return;
        }
        this.showInvisible = wanted;
        this._replaceCanvas(payload);
    }

    /**
     * What the properties panel shows for a node: `describe_node`, cached
     * per canvas since the answer only changes when the arch does.
     */
    async describe(token: Token): Promise<DescribedTarget | null> {
        const cached = this.descriptions[token];
        if (cached) {
            return cached;
        }
        const node = this.nodes[token];
        if (!node) {
            return null;
        }
        const version = this.archVersion;
        let found: DescribeNodeAnswer;
        try {
            found = await this.orm.call<DescribeNodeAnswer>("studio.view.editor", "describe_node", [
                this.viewId,
                this.descriptor(token),
            ]);
        } catch (err) {
            if (!compat.isStaleError(err)) {
                throw err;
            }
            await this._guard(() => this.refresh());
            this._staleNotice();
            return null;
        }
        if (this.archVersion !== version) {
            return null;
        }
        // Both halves: the table says what kind of thing it is, which the
        // option catalogue matches on; the server says what it currently
        // carries and what its field is.
        const target: DescribedTarget = markRaw({
            kind: node.kind,
            name: node.name,
            token,
            ...found,
            field: (found.found && found.field) || node.field || null,
        });
        this.descriptions[token] = target;
        return target;
    }

    // -- mutating -----------------------------------------------------------

    /**
     * One wrapper for every edit.
     *
     * Runs `run`, swaps in the canvas it returns or reloads one, and turns
     * the two refusals a client can act on into what the user should see:
     * a stale view reloads silently with a note, anything else is a warning
     * with the server's sentence. Returns the RPC result, or `undefined`
     * when it was refused.
     */
    async _mutate<T>(
        run: () => Promise<T>,
        { select = null, silent = false, prefix = "" }: MutateOptions = {},
    ): Promise<T | undefined> {
        if (!this.packageId) {
            this.notification.add(
                String(_t("Choose a studio package to record this change in first.")),
                { type: "warning" },
            );
            return undefined;
        }
        this.busy = true;
        this.status = "saving";
        this.statusError = "";
        try {
            const result = await run();
            const raw = result as RawMutateFields;
            if (raw && raw.stale) {
                this._replaceCanvas(raw.canvas as CanvasPayload);
                await this._afterChange();
                this._staleNotice();
                this.status = "saved";
                return undefined;
            }
            if (raw && raw.draft) {
                // A staged drop answers with the draft it staged on, so
                // the tray is current without a second round trip.
                this.draftModel.draft = markRaw(raw.draft);
            }
            if (raw && raw.canvas) {
                this._replaceCanvas(raw.canvas, { select: select || raw.select || null });
            } else {
                await this.refresh();
                // What the operation brought into being, by name, when it
                // named something: a new tab or group is selected so the
                // next click-to-add lands in it.
                const created = raw && raw.created_name;
                const wanted = select || (created && this._tokenNamed(created));
                if (wanted) {
                    this.select(wanted);
                }
            }
            await this._afterChange();
            this.status = "saved";
            return result;
        } catch (err) {
            if (compat.isStaleError(err)) {
                await this._guard(() => this.refresh());
                await this._afterChange();
                this._staleNotice();
                this.status = "saved";
                return undefined;
            }
            if (compat.isConfirmError(err)) {
                this.status = "saved";
                throw err;
            }
            this.status = "error";
            this.statusError = messageOf(err);
            if (!silent) {
                this.notification.add(prefix + this.statusError, { type: "warning" });
            }
            if (!(err as OdooRpcError)?.data) {
                throw err;
            }
            return undefined;
        } finally {
            this.busy = false;
        }
    }

    /**
     * What else has to follow a changed arch, whatever changed it.
     *
     * A search view is not rendered from the canvas but edited as lists
     * and previewed by a host list that loads it the ordinary way; both
     * have to be refreshed after an add, a remove, an undo or a redo alike,
     * so it is done here, on the one path every mutation takes.
     */
    async _afterChange(): Promise<void> {
        if (this.editableAs === "search_lists") {
            await this._afterSearchChange();
        }
    }

    /** The first selectable node called `name` in the current canvas. */
    _tokenNamed(name: string): Token | null {
        const found = Object.entries(this.nodes).find(
            ([, node]) => node.name === name && node.selectable,
        );
        return found ? found[0] : null;
    }

    _staleNotice(): void {
        this.notification.add(String(_t("This view changed; it was refreshed — try again.")), {
            type: "info",
        });
    }

    /** Run a read that may fail, showing the reason rather than dying. */
    async _guard<T>(run: () => Promise<T>): Promise<T | undefined> {
        try {
            return await run();
        } catch (err) {
            if (!(err as OdooRpcError)?.data) {
                throw err;
            }
            this.notification.add(messageOf(err), { type: "warning" });
            return undefined;
        }
    }

    /** `apply_at` with a token descriptor and the version it came with. */
    async applyAt(
        token: Token,
        operation: Record<string, unknown>,
    ): Promise<OperationResult | undefined> {
        return this._mutate(() =>
            this.orm.call<OperationResult>("studio.view.editor", "apply_at", [
                this.viewId,
                this.packageId,
                this.descriptor(token),
                operation,
                this.archVersion,
            ]),
        );
    }

    /**
     * A raw operation, for the one canvas whose locators the server hands
     * out ready-made: a report's `locate_expression` and `body_anchor`
     * answer with the xpath, since a rendered document carries no tokens.
     */
    async applyOperation(operation: Record<string, unknown>): Promise<OperationResult | undefined> {
        return this._mutate(() =>
            this.orm.call<OperationResult>("studio.view.editor", "apply_operation", [
                this.viewId,
                this.packageId,
                operation,
                this.archVersion,
            ]),
        );
    }

    /** Write attributes on a node, as the properties rows do. */
    async setAttributes(
        token: Token,
        attrs: Record<string, unknown>,
    ): Promise<OperationResult | undefined> {
        return this.applyAt(token, {
            type: "set_attributes",
            position: "attributes",
            attrs,
        });
    }

    /**
     * Give a field the label the form would not draw for it: a `<label for>`
     * before it. Where the form draws the label itself -- a field in a
     * group -- the switch is the `nolabel` attribute and goes through
     * `setAttributes` instead; the panel knows which from `node.label`.
     */
    async showLabel(token: Token): Promise<OperationResult | undefined> {
        return this._mutate(() =>
            this.orm.call<OperationResult>("studio.view.editor", "show_label_at", [
                this.viewId,
                this.packageId,
                this.descriptor(token),
                this.archVersion,
            ]),
        );
    }

    /**
     * Show or hide a form field's label, whichever way the form draws
     * it: `nolabel` where a group draws the label, a `<label for>` of its
     * own anywhere else. What the properties' switch and the outline's
     * menu both do; `node.label` says which way applies.
     */
    async setLabelShown(token: Token, shown: boolean): Promise<OperationResult | undefined> {
        const node = this.nodes[token];
        const label = node && node.kind === "field" ? node.label : null;
        if (!label) {
            return undefined;
        }
        if (label.in_group) {
            return this.setAttributes(token, { nolabel: shown ? null : "1" });
        }
        if (shown) {
            return this.showLabel(token);
        }
        if (label.token) {
            return this.hideLabel(label.token);
        }
        return undefined;
    }

    /**
     * Take that label away again. `remove` on the label's own token, but
     * the field stays selected: the label was never what was selected.
     */
    async hideLabel(labelToken: Token): Promise<OperationResult | undefined> {
        return this._mutate(() =>
            this.orm.call<OperationResult>("studio.view.editor", "remove_at", [
                this.viewId,
                this.packageId,
                this.descriptor(labelToken),
                this.archVersion,
                false,
            ]),
        );
    }

    /**
     * Take a node out of the view.
     *
     * A container with something in it is refused the first time, with the
     * question to ask; the answer comes back as `{confirm: sentence}` so the
     * panel can ask it and call again with `force`.
     */
    async remove(
        token: Token,
        force = false,
    ): Promise<OperationResult | { confirm: string; context: unknown } | undefined> {
        const node = this.nodes[token];
        if (node && node.kind === "pending") {
            // A ghost is not in the arch to be removed from it: taking it
            // off the canvas is un-staging the field, which is asked about
            // first the way a container with children is.
            if (!force) {
                return {
                    confirm: String(
                        _t(
                            "Remove the pending field %s? It has not been applied, so nothing is lost but its definition.",
                            this.tagFor(token).replace(/^[^·]*· /, ""),
                        ),
                    ),
                    context: undefined,
                };
            }
            const result = await this.removePending(
                node.pending ? node.pending.name : node.name || "",
            );
            if (result !== undefined) {
                this.selection = null;
            }
            return result as OperationResult | undefined;
        }
        try {
            const result = await this._mutate(() =>
                this.orm.call<OperationResult>("studio.view.editor", "remove_at", [
                    this.viewId,
                    this.packageId,
                    this.descriptor(token),
                    this.archVersion,
                    force,
                ]),
            );
            if (result !== undefined) {
                this.selection = null;
            }
            return result;
        } catch (err) {
            if (compat.isConfirmError(err)) {
                return { confirm: messageOf(err), context: (err as OdooRpcError).data?.context };
            }
            throw err;
        }
    }

    /** One drop -- or one click-to-add -- at a token, one call. */
    async dropAt(
        token: Token | null,
        position: ZonePosition,
        payload: DragPayload,
        options: MutateOptions = {},
    ): Promise<DropSuccessResult | undefined> {
        return this._mutate(
            () =>
                this.orm.call<DropSuccessResult>("studio.view.editor", "drop_at", [
                    this.viewId,
                    this.packageId,
                    { token, position },
                    payload,
                    this.archVersion,
                    this._canvasOptions(),
                ]),
            options,
        );
    }

    /**
     * What a drag ends in: the payload the tile or the node stood for,
     * put before, after or inside the node the zone named.
     *
     * One call, and the answer is believed: the canvas it carries is
     * swapped in and the node it names is selected, which opens the
     * properties. A refusal is the server's sentence behind "Can't drop
     * here", a stale canvas is reloaded with a note, as for any edit. Two
     * payloads are not sent as they are: a Button tile needs an action
     * first, and a field tile of a type that needs its definition first --
     * a relation, a selection -- needs the editor; either way the target
     * is held for the palette to finish the drop. Returns the server's
     * answer with `created_field` set when the drop brought a live field
     * into being and `staged_field` when it staged one, or `undefined`
     * when nothing was written.
     */
    async drop(
        token: Token | null,
        position: ZonePosition,
        payload: DragPayload,
    ): Promise<
        (DropSuccessResult & { created_field: boolean; staged_field: boolean }) | undefined
    > {
        const values = payload["values"] as Record<string, unknown> | undefined;
        if (
            payload.kind === "component" &&
            payload.component === "button" &&
            !(values && values["action_id"])
        ) {
            this.buttonTarget = {
                token: token as Token,
                position,
                arch_version: this.archVersion,
                serial: Date.now(),
            };
            return undefined;
        }
        if (
            payload.kind === "new_field" &&
            !(values && values["defined"]) &&
            this.needsDialog(values ? (values["ttype"] as string | undefined) : undefined)
        ) {
            this.fieldTarget = {
                token: token as Token,
                position,
                arch_version: this.archVersion,
                serial: Date.now(),
                ttype: (values && (values["ttype"] as string)) || "",
                label: (values && (values["field_description"] as string)) || "",
            };
            return undefined;
        }
        let sendPayload = payload;
        if (payload.kind === "new_field") {
            sendPayload = { ...payload, values: this.fieldValues(values) };
        }
        const result = await this.dropAt(token, position, sendPayload, {
            prefix: String(_t("Can't drop here: ")),
        });
        if (result === undefined) {
            return undefined;
        }
        if (["existing_field", "new_field"].includes(payload.kind)) {
            // The palette no longer offers a field the view now has.
            void this.loadPalette();
        }
        return {
            ...result,
            created_field: Boolean(result.created),
            staged_field: Boolean(result.staged),
        };
    }

    /** Where a click-to-add goes: inside a container, after a leaf. */
    positionFor(token: Token | null): ZonePosition {
        const node = token ? this.nodes[token] : undefined;
        return node && node.container ? "inside" : "after";
    }

    async addExistingField(name: string): Promise<DropSuccessResult | undefined> {
        const token = this.anchorToken;
        const result = await this._mutate(() =>
            this.orm.call<DropSuccessResult>("studio.view.editor", "drop_at", [
                this.viewId,
                this.packageId,
                { token, position: this.positionFor(token) },
                { kind: "existing_field", name },
                this.archVersion,
                this._canvasOptions(),
            ]),
        );
        void this.loadPalette();
        return result;
    }

    async addComponent(
        component: string,
        values: Record<string, unknown> = {},
    ): Promise<OperationResult | DropSuccessResult | undefined> {
        const token = this.anchorToken;
        if (component === "page") {
            // A tab has a rule of its own -- it lives in the notebook, and
            // the notebook may not exist yet -- which `add_container_at`
            // already knows.
            return this._mutate(() =>
                this.orm.call<OperationResult>(
                    "studio.view.editor",
                    "add_container_at",
                    [this.viewId, this.packageId, this.descriptor(token), "page"],
                    { expected_arch_version: this.archVersion },
                ),
            );
        }
        return this.dropAt(token, this.positionFor(token), {
            kind: "component",
            component,
            values,
        });
    }

    /**
     * Add a button, at the held drop target when a tile was dropped, at
     * the selection otherwise.
     *
     * The target is carried across every canvas replacement or let go of,
     * so one that is here was minted on the canvas on screen; a target
     * from another version would be a drop the server cannot check, and
     * is refused here rather than sent.
     */
    async addButton(
        values: Record<string, unknown>,
    ): Promise<
        | (DropSuccessResult & { created_field: boolean; staged_field: boolean })
        | OperationResult
        | DropSuccessResult
        | undefined
    > {
        const target = this.buttonTarget;
        this.buttonTarget = null;
        if (target) {
            if (target.arch_version !== this.archVersion || !this.nodes[target.token]) {
                this.notification.add(String(_t("This view changed; drop the button again.")), {
                    type: "info",
                });
                return undefined;
            }
            return this.drop(target.token, target.position, {
                kind: "component",
                component: "button",
                values,
            });
        }
        return this.addComponent("button", values);
    }

    /**
     * A new field's values as `drop_at` takes them.
     *
     * The field editor speaks the draft's spec -- `string` for the label,
     * and a few keys that are the editor's own -- and the drop takes
     * `field_description` plus what the type needs. Whatever the server
     * has no use for, it ignores; what it must not see is the panel's
     * bookkeeping -- nor, for a field created live, the class-level
     * attributes a manual row has no column for, which the server would
     * refuse by name rather than drop.
     */
    fieldValues(values: Record<string, unknown> | null | undefined): Record<string, unknown> {
        const {
            string,
            field_description,
            defined,
            error,
            inverse,
            relatedInfo,
            showCompute,
            type_label,
            ...rest
        } = values || {};
        const label = field_description || string;
        const out: Record<string, unknown> = {
            ...rest,
            field_description: (typeof label === "string" ? label : "").trim(),
        };
        if (!this.pythonOwned) {
            for (const key of LIVE_UNSUPPORTED) {
                delete out[key];
            }
        }
        const name = out["name"];
        if (!this.pythonOwned && typeof name === "string" && !name.startsWith("x_")) {
            // The editor slugs the label the way the draft names a class
            // attribute; a live field is an `x_` row, and the server
            // derives that from the label when no name is sent.
            delete out["name"];
        }
        if (Array.isArray(out["selection"])) {
            const rows = out["selection"] as Record<string, unknown>[];
            const cleaned = rows
                .filter((row) => row && row["value"])
                .map((row, index) => ({
                    value: row["value"],
                    label: row["label"] || row["value"],
                    sequence: row["sequence"] || (index + 1) * 10,
                }));
            if (cleaned.length) {
                out["selection"] = cleaned;
            } else {
                delete out["selection"];
            }
        }
        return out;
    }

    /**
     * Add a new field: at the held drop target when a tile was dropped and
     * the editor has just finished its definition, at the selection
     * otherwise -- the click-to-add path, and the editor's Done for a
     * clicked tile. `values` are the editor's, or a tile's `{ttype,
     * field_description}`. The target is carried across every canvas
     * replacement or let go of, like the button's.
     */
    async addNewField(
        values: Record<string, unknown>,
    ): Promise<
        (DropSuccessResult & { created_field: boolean; staged_field: boolean }) | undefined
    > {
        const target = this.fieldTarget;
        this.fieldTarget = null;
        const payload: DragPayload = { kind: "new_field", values: { ...values, defined: true } };
        if (target) {
            if (target.arch_version !== this.archVersion || !this.nodes[target.token]) {
                this.notification.add(String(_t("This view changed; drop the field again.")), {
                    type: "info",
                });
                return undefined;
            }
            return this.drop(target.token, target.position, payload);
        }
        const token = this.anchorToken;
        return this.drop(token, this.positionFor(token), payload);
    }

    // -- the draft: staged fields, Apply, Discard ---------------------------

    /**
     * What a relational field could be linked back by.
     *
     * The draft answers for a Python-owned model, since only it knows
     * what the package could write on the other side. On a live model
     * the answer is what the comodel already has: its many2ones pointing
     * here, and no offer to make one -- a manual field is created on the
     * spot, and the link back would be a second gesture on another model.
     */
    async inverseOptions(comodel: string | false): Promise<InverseOptions> {
        const empty: InverseOptions = {
            candidates: [],
            can_create: false,
            suggested: "",
            reason: "",
        };
        if (!comodel) {
            return empty;
        }
        if (this.pythonOwned) {
            const draft = await this._ensureDraft();
            if (!draft) {
                return empty;
            }
            return this.orm.call<InverseOptions>("studio.model.draft", "inverse_options", [
                [draft.id],
                comodel,
            ]);
        }
        const fields = await this.env.services.field.loadFields(comodel, {
            attributes: ["type", "relation", "string"],
        });
        const candidates = Object.entries(fields)
            .filter(([, def]) => def.type === "many2one" && def.relation === this.modelName)
            .map(([name, def]) => ({ name, string: def.string || name }))
            .sort((a, b) => a.name.localeCompare(b.name));
        return {
            ...empty,
            candidates,
            reason: candidates.length
                ? ""
                : String(
                      _t(
                          "%(comodel)s has no link to %(model)s yet. Add one there first, then pick it here.",
                          { comodel, model: this.modelName },
                      ),
                  ),
        };
    }

    /**
     * What a related path points at: its type, and so the new field's.
     * The draft walks the chain for a Python-owned model; for a live one
     * the field service does, from the same descriptions the views use.
     */
    async resolveRelated(path: string): Promise<ResolveRelatedResult> {
        if (this.pythonOwned) {
            const draft = await this._ensureDraft();
            if (!draft) {
                return { ok: false, reason: String(_t("No draft to resolve the path on.")) };
            }
            return this.orm.call<ResolveRelatedResult>("studio.model.draft", "resolve_related", [
                [draft.id],
                path,
            ]);
        }
        const steps = (path || "").split(".").filter(Boolean);
        if (!steps.length) {
            return { ok: false, reason: String(_t("Choose a field to follow.")) };
        }
        // A live-model path is only ever resolved once a model is on
        // screen -- `resolveRelated` is reached from the field editor,
        // which the picker does not open without one.
        const loaded = await this.env.services.field.loadPath(this.modelName as string, path);
        const lastStep = steps[steps.length - 1] as string;
        const last = loaded.modelsInfo[loaded.modelsInfo.length - 1];
        const def = last ? last.fieldDefs[lastStep] : undefined;
        if (loaded.isInvalid || !def || loaded.modelsInfo.length !== steps.length) {
            return {
                ok: false,
                reason: String(_t("%s does not lead to a field of this model.", path)),
            };
        }
        return {
            ok: true,
            ttype: def.type,
            comodel: def.relation || "",
            string: def.string || lastStep,
            stored: Boolean(def.store),
        };
    }

    /** The draft the editor's questions go to, opened when the model has
     * none yet; the shell's, opened on this model. */
    async _ensureDraft(): Promise<DraftPayload | null> {
        return this.draftModel.ensure();
    }

    /**
     * One call on the draft, then the tray and the canvas reloaded: the
     * ghosts follow what was staged.
     */
    async _onDraft<T = unknown>(
        method: string,
        args: unknown[],
        { silent = false }: { silent?: boolean } = {},
    ): Promise<T | undefined> {
        this.busy = true;
        try {
            const result = await this.draftModel.call<T>(method, args, { silent });
            if (result === undefined) {
                return undefined;
            }
            await this.refresh();
            return result;
        } finally {
            this.busy = false;
        }
    }

    /** Un-stage a field: its ghost goes with it. */
    async removePending(name: string): Promise<unknown> {
        return this._onDraft("remove_field", [name]);
    }

    /** Change a staged field's definition; the ghost follows the label. */
    async updateStaged(
        name: string,
        values: Record<string, unknown> | null | undefined,
    ): Promise<unknown> {
        const { defined, error, inverse, relatedInfo, showCompute, ...rest } = values || {};
        if (rest["field_description"] && !rest["string"]) {
            rest["string"] = rest["field_description"];
        }
        delete rest["field_description"];
        return this._onDraft("update_field", [name, rest]);
    }

    /**
     * Reorder the class: `name` goes before `before`, or last. Class
     * order is the order the fields are written to Python and the order a
     * scaffolded view shows them in, so this is a layout gesture too.
     */
    async moveField(name: string, before: string | null = null): Promise<unknown> {
        return this._onDraft("move_field", [name, before]);
    }

    /**
     * Stage a field on the model without a place on this canvas -- from
     * the model's own field list rather than a drop. Apply puts it where
     * the balanced rule says, and the tray says so.
     */
    async addModelField(values: Record<string, unknown>): Promise<unknown> {
        const cleaned = this.fieldValues(values);
        const spec: Record<string, unknown> = { ...cleaned, string: cleaned["field_description"] };
        delete spec["field_description"];
        return this._onDraft("add_field", [spec]);
    }

    /** The model's fields in class order, with what the draft holds for each. */
    get modelFields(): DraftFieldWithPending[] {
        return this.draftModel.modelFields;
    }

    /** Everything the draft has staged, thrown away; the ghosts go too. */
    async discardDraft(): Promise<unknown> {
        return this._onDraft("action_discard", []);
    }

    /** The unified diff of what Apply would write, for the dialog. */
    async previewDiff(): Promise<string> {
        return this.draftModel.previewDiff();
    }

    /**
     * Apply the draft through the shell, then read everything again: the
     * package was reloaded, so the context, the canvas and every list are
     * stale. `{ok, message, destructive, restartRequired}` as the draft
     * says it.
     */
    async applyDraft(allowDestructive = false): Promise<ApplyResult> {
        const result = await this.draftModel.apply(allowDestructive);
        if (result && result.ok) {
            await this.afterApply();
        }
        return result;
    }

    /** Everything the console knows, read again after a reload. */
    async afterApply(): Promise<void> {
        await this.loadContext();
        await this.refresh();
        await Promise.all([
            this.loadDraft(),
            this.loadPalette(),
            this.loadFieldPlan(),
            this.loadFieldTypes(),
        ]);
        this.renderSerial += 1;
    }

    // -- a manual field's definition ---------------------------------------

    /**
     * Change what a live `x_` field is -- its label, help, flags or
     * selection values -- in `ir.model.fields`, and show the result.
     *
     * The arch does not change, so its version does not; the canvas is
     * remounted on `renderSerial` instead, since a renamed field renders
     * under its new label only from a fresh description. Returns the
     * definition as the server now has it, for the panel to show; the
     * cached description is dropped with the canvas it belonged to.
     */
    async updateManualField(
        token: Token,
        values: Record<string, unknown>,
    ): Promise<FieldDefinition | undefined> {
        const node = this.nodes[token];
        if (!node || !node.name || !this.packageId) {
            return undefined;
        }
        this.busy = true;
        this.status = "saving";
        try {
            const definition = await this.orm.call<FieldDefinition>(
                "studio.view.editor",
                "update_manual_field",
                [this.modelName, node.name, values, this.packageId],
            );
            await this.refresh();
            this.renderSerial += 1;
            this.status = "saved";
            return definition;
        } catch (err) {
            if (!(err as OdooRpcError)?.data) {
                throw err;
            }
            this.status = "error";
            this.statusError = messageOf(err);
            this.notification.add(this.statusError, { type: "warning" });
            return undefined;
        } finally {
            this.busy = false;
        }
    }

    async undo(): Promise<void> {
        const entry = this.history.undo[0];
        if (!entry) {
            return;
        }
        await this._mutate(() =>
            this.orm.call<boolean>("studio.view.edit", "action_undo", [[entry.id]], {
                expected_arch_version: this.archVersion,
            }),
        );
        void this.loadPalette();
    }

    async redo(): Promise<void> {
        const entry = this.history.redo[0];
        if (!entry) {
            return;
        }
        await this._mutate(() =>
            this.orm.call<boolean>("studio.view.edit", "action_redo", [[entry.id]], {
                expected_arch_version: this.archVersion,
            }),
        );
        void this.loadPalette();
    }

    // -- the sidebar's lists ----------------------------------------------

    async loadPalette(): Promise<void> {
        if (!this.modelName || this.editableAs !== "canvas") {
            this.palette = [];
            return;
        }
        this.palette = markRaw(
            await this.orm.call<AddableFieldEntry[]>("studio.view.editor", "get_addable_fields", [
                this.modelName,
                this.viewId,
            ]),
        );
    }

    async loadAddable(): Promise<void> {
        if (!this.modelName) {
            this.addable = [];
            return;
        }
        this.addable = markRaw(
            await this.orm.call<AddableViewTypeEntry[]>(
                "studio.view.editor",
                "addable_view_types",
                [this.modelName],
            ),
        );
    }

    async loadFieldPlan(): Promise<void> {
        this.fieldPlan = markRaw(
            await this.orm.call<NewFieldPlan>("studio.view.editor", "new_field_plan", [
                this.viewId,
            ]),
        );
    }

    async loadServerActions(): Promise<void> {
        this.serverActions = markRaw(
            await this.orm.searchRead<{ id: number; name: string }>(
                "ir.actions.server",
                [["model_id.model", "=", this.modelName]],
                ["id", "name"],
                { limit: 200, order: "name" },
            ),
        );
    }

    /** Create another kind of view for this model. */
    async addView(entry: AddableViewTypeEntry): Promise<unknown> {
        if (!entry.enabled || !this.packageId) {
            return undefined;
        }
        const dateField = entry.date_fields[0]?.name ?? null;
        const groupField = entry.group_fields[0]?.name ?? null;
        if (entry.type === "calendar" && !dateField) {
            return undefined;
        }
        if (entry.type === "timeline" && (!dateField || !groupField)) {
            return undefined;
        }
        this.busy = true;
        try {
            const result = await this._guard(() =>
                this.orm.call("studio.view.editor", "add_view", [
                    this.modelName,
                    entry.type,
                    this.packageId,
                    dateField,
                    groupField,
                ]),
            );
            if (result !== undefined) {
                this.notification.add(
                    String(
                        _t(
                            "%s view created. It is now offered by this app's menu.",
                            entry.label || entry.type,
                        ),
                    ),
                    { type: "success" },
                );
                await this.loadAddable();
                // Only reachable once a view is already loaded, so the
                // context this spreads is never actually null; see this
                // getter's own docstring for the one other place that
                // relies on the same fact.
                this.context = markRaw({
                    ...(this.context as EditingContext),
                    views: await this._viewsOf(),
                });
            }
            return result;
        } finally {
            this.busy = false;
        }
    }

    async _viewsOf(): Promise<ViewOfEntry[]> {
        const context = await this.orm.call<EditingContext>(
            "studio.view.editor",
            "editing_context",
            [this.viewId],
            {},
        );
        return context.views;
    }

    // -- search views: the three lists ------------------------------------

    async loadSearch(): Promise<void> {
        this.search = markRaw(
            await this.orm.call<SearchElements>("studio.view.editor", "search_elements", [
                this.viewId,
            ]),
        );
    }

    async addSearchElement(
        kind: string,
        values: Record<string, unknown>,
    ): Promise<OperationResult | undefined> {
        if (!values["field"]) {
            return undefined;
        }
        return this._mutate(() =>
            this.orm.call<OperationResult>("studio.view.editor", "add_search_element", [
                this.viewId,
                this.packageId,
                kind,
                values,
            ]),
        );
    }

    async removeSearchElement(kind: string, name: string): Promise<OperationResult | undefined> {
        return this._mutate(() =>
            this.orm.call<OperationResult>("studio.view.editor", "remove_search_element", [
                this.viewId,
                this.packageId,
                kind,
                name,
            ]),
        );
    }

    /** Called by `_afterChange` after every mutation of a search view. */
    async _afterSearchChange(): Promise<void> {
        await this.loadSearch();
        // The host list loads its search view the ordinary way, through the
        // cache the real views share, so that has to go for the menus on
        // screen to be the ones just edited -- and the list remounted.
        compat.clearViewCaches(this.env);
        this.searchSerial += 1;
    }
}

// Kinds whose technical name still says something when there is no string.
const NAMED_KINDS = ["field", "column", "button", "page", "widget"];

const KIND_LABELS: Record<string, ReturnType<typeof _t>> = {
    root: _t("View"),
    field: _t("Field"),
    column: _t("Column"),
    button: _t("Button"),
    page: _t("Tab"),
    group: _t("Group"),
    notebook: _t("Notebook"),
    sheet: _t("Sheet"),
    header: _t("Header"),
    footer: _t("Footer"),
    separator: _t("Separator"),
    label: _t("Label"),
    widget: _t("Widget"),
    chatter: _t("Chatter"),
    button_box: _t("Button box"),
    card: _t("Card"),
    pending: _t("Pending"),
    main: _t("Card body"),
    aside: _t("Card side panel"),
    html: _t("Block"),
};

export { messageOf };
