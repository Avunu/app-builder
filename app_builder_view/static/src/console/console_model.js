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
 * ghost where it will land; the draft's payload -- what is pending, what
 * the reload will cost -- is held here as `draft`, and Apply, Discard and
 * the edits to a staged field all go through it.
 *
 * No Owl in here. Reactivity is the caller's business (`useState` on the
 * instance); this class is plain so it can be tested and ported as it is.
 */

import { markRaw } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import * as compat from "./compat";

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

/** How long Apply waits for a restarting server, and how it waits. */
export const RECONNECT_DELAYS_MS = [1000, 2000, 3000, 4000, 5000, 5000, 5000, 5000];

/**
 * Spec keys a field created live cannot carry: they are class attributes
 * with no `ir.model.fields` column (`manualfield.UNSUPPORTED_LIVE`), and
 * the editor never offers them in live mode. Stripped here too, so a
 * value that reached the payload some other way is not the whole drop's
 * refusal.
 */
const LIVE_UNSUPPORTED = ["default", "compute", "compute_body", "depends", "digits"];

export class ConsoleModel {
    /**
     * @param {Object} env the component env; `services.orm`,
     *   `services.notification` and `bus` are read.
     * @param {Object} params `{view_id, model|res_model, view_type,
     *   action_id, res_id}` -- the legacy and the console spellings both.
     */
    constructor(env, params) {
        this.env = env;
        this.orm = env.services.orm;
        this.notification = env.services.notification;
        this.params = {
            view_id: params.view_id || false,
            model: params.model || params.res_model || false,
            view_type: params.view_type || false,
            action_id: params.action_id || false,
            res_id: params.res_id || false,
        };

        this.context = null;
        this.canvas = null;
        this.selection = null;
        // Counts the times something was *selected* -- a click, a drop --
        // as opposed to carried across a remount; the sidebar opens the
        // properties on the former and not on the latter.
        this.selectionSerial = 0;
        this.hover = null;
        // `{label, caption}` while something is being dragged over the
        // canvas -- what the status pill says meanwhile -- else `null`.
        this.drag = null;
        // Where a Button tile was dropped: the tile needs an action before
        // anything is written, so the drop is held here and the palette
        // asks for the rest, then sends it to this spot. Held with the
        // version of the arch its token was minted on, like any descriptor:
        // the canvas may be replaced while the palette is still asking.
        this.buttonTarget = null;
        // Where a field tile that needs its definition first was dropped: a
        // relation without a model, a selection without values, is not a
        // field yet, so the drop is held here -- the same way, with the
        // same version -- while the field editor asks for the rest.
        this.fieldTarget = null;
        this.busy = false;
        this.status = "saved";
        this.statusError = "";
        this.showInvisible = false;
        // The notebook page the user is looking at, so a remount lands on it.
        this.activePage = null;
        this.palette = [];
        this.addable = [];
        this.fieldPlan = null;
        // The picker's entries for this model, each saying whether it can
        // be made live here and whether it needs the editor first.
        this.fieldTypes = [];
        // This user's draft on the model, as `studio.model.draft.load()`
        // returns it, when the model is Python-owned and one exists.
        this.draft = null;
        this.applying = false;
        // Bumped when the model's fields changed under an unchanged arch
        // -- a manual field renamed -- so the canvas remounts on it.
        this.renderSerial = 0;
        this.serverActions = [];
        this.search = null;
        // Bumped after every search-view edit: the host list previewing the
        // search view loads it the ordinary way and has to be remounted.
        this.searchSerial = 0;
        this.modelLabel = "";
        this.descriptions = markRaw({});
        this.packageId = false;
    }

    // -- reading ------------------------------------------------------------

    get view() {
        return (this.canvas && this.canvas.view) || (this.context && this.context.view) || {};
    }

    get viewId() {
        return this.view.id || this.params.view_id;
    }

    get viewType() {
        return this.view.type;
    }

    get modelName() {
        return this.view.model;
    }

    get editableAs() {
        return (this.canvas && this.canvas.editable_as) || "canvas";
    }

    get archVersion() {
        return this.canvas ? this.canvas.arch_version : null;
    }

    get nodes() {
        return (this.canvas && this.canvas.nodes) || {};
    }

    get root() {
        return this.canvas ? this.canvas.root : null;
    }

    get history() {
        return (this.canvas && this.canvas.history) || { undo: [], redo: [] };
    }

    get package() {
        return (this.canvas && this.canvas.package) || null;
    }

    /** Whether an edit can be recorded at all. */
    get canWrite() {
        return Boolean(this.packageId) && !this.busy && !this.applying;
    }

    get selectedNode() {
        return this.selection ? this.nodes[this.selection.token] : null;
    }

    // -- the draft ----------------------------------------------------------

    /** Whether a new field here is a class attribute waiting for an Apply. */
    get pythonOwned() {
        return Boolean(this.context && this.context.python_owned);
    }

    /** The draft the console addresses, from whichever answer named it last. */
    get draftId() {
        return (
            (this.draft && this.draft.id) ||
            (this.canvas && this.canvas.draft_id) ||
            (this.context && this.context.draft_id) ||
            false
        );
    }

    /** The ghosts the canvas carries: `{name, label, ttype, token, placed}`. */
    get pending() {
        return (this.canvas && this.canvas.pending) || [];
    }

    /**
     * What the pill counts. The draft's own count when it has been loaded
     * -- it knows about removals and edits the canvas has no ghost for --
     * else the ghosts on the canvas.
     */
    get pendingCount() {
        if (this.draft) {
            return this.draft.change_count || 0;
        }
        return this.pending.length;
    }

    /** The staged changes, as the draft lists them for its tray. */
    get pendingChanges() {
        return (this.draft && this.draft.pending) || [];
    }

    get draftErrors() {
        return (this.draft && this.draft.errors) || [];
    }

    /** `inproc`, `restart` or `manual`: what an Apply costs on this server. */
    get reloadMode() {
        return (
            (this.draft && this.draft.package && this.draft.package.reload_mode) ||
            (this.context && this.context.reload_mode) ||
            false
        );
    }

    /** Why Apply is not on offer right now, or `""` when it is. */
    get applyBlocker() {
        if (!this.pendingCount) {
            return _t("Nothing is pending.");
        }
        if (this.reloadMode === "manual") {
            return _t(
                "This server runs several workers, so it cannot reload in place. " +
                    "Staging works; applying needs a restart of the server."
            );
        }
        if (this.draft && this.draft.package && !this.draft.package.writable) {
            return _t("This package is read-only, so nothing can be applied.");
        }
        if (this.draftErrors.length) {
            return this.draftErrors.join("\n");
        }
        return "";
    }

    get canApply() {
        return !this.applying && !this.busy && !this.applyBlocker;
    }

    /** The staged definition of a pending field, from the draft. */
    stagedField(name) {
        const fields = (this.draft && this.draft.fields) || [];
        return fields.find((field) => field.name === name) || null;
    }

    /** The picker entry for a key such as `char` or `priority`. */
    fieldTypeEntry(key) {
        return this.fieldTypes.find((entry) => entry.value === key) || null;
    }

    /**
     * Whether a tile of this type opens the editor before anything is sent.
     * The server's word when it has one, else the list above.
     */
    needsDialog(key) {
        const entry = this.fieldTypeEntry(key);
        if (entry && entry.needs_dialog !== undefined) {
            return Boolean(entry.needs_dialog);
        }
        return DIALOG_TYPES.has(key);
    }

    /** The node a click-to-add lands on: the selection, else the root. */
    get anchorToken() {
        if (this.selection && this.nodes[this.selection.token]) {
            return this.selection.token;
        }
        return this.root;
    }

    /** `{kind: "node", token, arch_version}` -- what every mutator takes. */
    descriptor(token) {
        return { kind: "node", token, arch_version: this.archVersion };
    }

    /** The label the selection frame shows: "Field · Email", "Tab · Notes". */
    tagFor(token) {
        const node = this.nodes[token];
        if (!node) {
            return "";
        }
        const kind = KIND_LABELS[node.kind] || _t("Element");
        // The table falls back to the technical name when the arch gives
        // no string. A field's own label reads better than that, and a
        // generated group name -- `studio_group_a1b2` -- is not a name a
        // person gave, so a container without a string is just its kind.
        let name = node.string && node.string !== node.name ? node.string : null;
        if (!name && node.field) {
            name = node.field.string;
        }
        if (!name && node.pending) {
            name = node.pending.string || node.pending.name;
        }
        if (!name && NAMED_KINDS.includes(node.kind)) {
            name = node.name;
        }
        return name && node.kind !== "root" ? `${kind} · ${name}` : kind;
    }

    // -- loading ------------------------------------------------------------

    async load() {
        await this.loadContext();
        this.packageId = this.context.suggested_package_id || false;
        await this.refresh({ keepSelection: false });
        // The field plan is asked for every view, not only those with a
        // rendering: it is what says why a report cannot take a new field.
        const loads = [this._loadModelLabel(), this.loadFieldPlan(), this.loadDraft()];
        if (this.editableAs === "canvas" && this.modelName) {
            loads.push(
                this.loadPalette(),
                this.loadAddable(),
                this.loadServerActions(),
                this.loadFieldTypes()
            );
        } else if (this.editableAs === "search_lists") {
            loads.push(this.loadSearch(), this.loadAddable());
        }
        await Promise.all(loads);
    }

    async loadContext() {
        this.context = markRaw(
            await this.orm.call(
                "studio.view.editor",
                "editing_context",
                [this.viewId || this.params.view_id || false],
                { model: this.params.model, view_type: this.params.view_type }
            )
        );
    }

    /**
     * The picker's entries for this model, each with `live` and
     * `needs_dialog`. A server without `field_types_for` -- an older one
     * -- still sent the catalogue with the context, and the two flags are
     * then worked out here: live where nothing is Python-owned, the
     * editor for the types that cannot be made from a label alone.
     */
    async loadFieldTypes() {
        if (!this.modelName) {
            this.fieldTypes = [];
            return;
        }
        let entries;
        try {
            entries = await this.orm.call("studio.view.editor", "field_types_for", [
                this.modelName,
            ]);
        } catch (err) {
            if (!(err && err.data)) {
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
            }))
        );
    }

    /**
     * This user's draft on the model, when there is one.
     *
     * Never created here: opening the console is not an edit, and the
     * first staged drop makes the draft. A draft that has gone -- vacuumed
     * after its idle window -- is not an error either: the context is
     * re-read so the next drop opens a fresh one.
     */
    async loadDraft() {
        const id = this.draftId;
        if (!id) {
            this.draft = null;
            return;
        }
        try {
            this.draft = markRaw(await this.orm.call("studio.model.draft", "load", [[id]]));
        } catch (err) {
            if (!(err && err.data)) {
                throw err;
            }
            this.draft = null;
            await this.loadContext();
            if (this.draftId && this.draftId !== id) {
                await this.loadDraft();
            }
        }
    }

    async _loadModelLabel() {
        if (!this.modelName) {
            return;
        }
        const names = await this.orm.call("ir.model", "display_name_for", [[this.modelName]]);
        this.modelLabel = (names[0] && names[0].display_name) || this.modelName;
    }

    _canvasOptions() {
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
    async refresh({ keepSelection = true } = {}) {
        const payload = await this._fetchCanvas();
        this._replaceCanvas(payload, { keepSelection });
    }

    _fetchCanvas(options = {}) {
        return this.orm.call("studio.view.editor", "canvas", [
            this.viewId,
            { ...this._canvasOptions(), ...options },
        ]);
    }

    _replaceCanvas(payload, { keepSelection = true, select = null } = {}) {
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
        if (select && this.nodes[select]) {
            this.selection = null;
            this.select(select);
        } else if (keepSelection && previous) {
            const token = this._findAgain(previous, oldToken, previousNodes);
            this.selection = token ? { token, node: this.nodes[token] } : null;
        } else {
            this.selection = null;
        }
        this._carryTarget("buttonTarget", previousNodes, _t("This view changed; drop the button again."));
        this._carryTarget("fieldTarget", previousNodes, _t("This view changed; drop the field again."));
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
    _carryTarget(key, previousNodes, notice) {
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
    _placeOf(previous, oldToken, previousNodes) {
        const oldParent = previous.parent ? previousNodes[previous.parent] : null;
        const alike = (node, other) =>
            Boolean(node) === Boolean(other) &&
            (!node || (node.tag === other.tag && node.name === other.name));
        const same = (node) =>
            alike(node, previous) && alike(node.parent ? this.nodes[node.parent] : null, oldParent);
        if (previous.name) {
            const found = Object.entries(this.nodes).filter(([, node]) => same(node));
            return found.length === 1 ? found[0][0] : null;
        }
        const node = this.nodes[oldToken];
        return same(node) && node.index === previous.index ? oldToken : null;
    }

    /**
     * The token a node has after a re-stamp: the same one when it still
     * names the same node, else the first node of the same tag and name,
     * else the node at the same place under a parent of the same name.
     */
    _findAgain(previous, oldToken, previousNodes) {
        const same = (node) => node && node.tag === previous.tag;
        const nodes = this.nodes;
        if (same(nodes[oldToken]) && nodes[oldToken].name === previous.name) {
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
                (oldParent && parent && parent.tag === oldParent.tag && parent.name === oldParent.name)
            ) {
                return token;
            }
        }
        return null;
    }

    // -- selecting ----------------------------------------------------------

    select(token) {
        if (!token || !this.nodes[token]) {
            this.selection = null;
            return;
        }
        if (this.selection && this.selection.token === token) {
            return;
        }
        this.selection = { token, node: this.nodes[token] };
        this.selectionSerial += 1;
    }

    clearSelection() {
        this.selection = null;
    }

    hoverAt(token) {
        if (this.hover !== token) {
            this.hover = token || null;
        }
    }

    rememberPage(page) {
        this.activePage = page;
    }

    // -- dragging -----------------------------------------------------------

    beginDrag(label) {
        this.drag = { label: label || "", caption: "" };
    }

    setDragCaption(caption) {
        if (this.drag && this.drag.caption !== caption) {
            this.drag.caption = caption || "";
        }
    }

    endDrag() {
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
    async toggleInvisible() {
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
    async describe(token) {
        if (this.descriptions[token]) {
            return this.descriptions[token];
        }
        const node = this.nodes[token];
        if (!node) {
            return null;
        }
        const version = this.archVersion;
        let found;
        try {
            found = await this.orm.call("studio.view.editor", "describe_node", [
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
        const target = markRaw({
            kind: node.kind,
            name: node.name,
            token,
            ...found,
            field: found.field || node.field || null,
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
    async _mutate(run, { select = null, silent = false, prefix = "" } = {}) {
        if (!this.packageId) {
            this.notification.add(
                _t("Choose a studio package to record this change in first."),
                { type: "warning" }
            );
            return undefined;
        }
        this.busy = true;
        this.status = "saving";
        this.statusError = "";
        try {
            const result = await run();
            if (result && result.stale) {
                this._replaceCanvas(result.canvas);
                await this._afterChange();
                this._staleNotice();
                this.status = "saved";
                return undefined;
            }
            if (result && result.draft) {
                // A staged drop answers with the draft it staged on, so
                // the tray is current without a second round trip.
                this.draft = markRaw(result.draft);
            }
            if (result && result.canvas) {
                this._replaceCanvas(result.canvas, { select: select || result.select });
            } else {
                await this.refresh();
                // What the operation brought into being, by name, when it
                // named something: a new tab or group is selected so the
                // next click-to-add lands in it.
                const created = result && result.created_name;
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
            if (!(err && err.data)) {
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
    async _afterChange() {
        if (this.editableAs === "search_lists") {
            await this._afterSearchChange();
        }
    }

    /** The first selectable node called `name` in the current canvas. */
    _tokenNamed(name) {
        const found = Object.entries(this.nodes).find(
            ([, node]) => node.name === name && node.selectable
        );
        return found ? found[0] : null;
    }

    _staleNotice() {
        this.notification.add(
            _t("This view changed; it was refreshed — try again."),
            { type: "info" }
        );
    }

    /** Run a read that may fail, showing the reason rather than dying. */
    async _guard(run) {
        try {
            return await run();
        } catch (err) {
            if (!(err && err.data)) {
                throw err;
            }
            this.notification.add(messageOf(err), { type: "warning" });
            return undefined;
        }
    }

    /** `apply_at` with a token descriptor and the version it came with. */
    async applyAt(token, operation) {
        return this._mutate(() =>
            this.orm.call("studio.view.editor", "apply_at", [
                this.viewId,
                this.packageId,
                this.descriptor(token),
                operation,
                this.archVersion,
            ])
        );
    }

    /**
     * A raw operation, for the one canvas whose locators the server hands
     * out ready-made: a report's `locate_expression` and `body_anchor`
     * answer with the xpath, since a rendered document carries no tokens.
     */
    async applyOperation(operation) {
        return this._mutate(() =>
            this.orm.call("studio.view.editor", "apply_operation", [
                this.viewId,
                this.packageId,
                operation,
                this.archVersion,
            ])
        );
    }

    /** Write attributes on a node, as the properties rows do. */
    async setAttributes(token, attrs) {
        return this.applyAt(token, {
            type: "set_attributes",
            position: "attributes",
            attrs,
        });
    }

    /**
     * Take a node out of the view.
     *
     * A container with something in it is refused the first time, with the
     * question to ask; the answer comes back as `{confirm: sentence}` so the
     * panel can ask it and call again with `force`.
     */
    async remove(token, force = false) {
        const node = this.nodes[token];
        if (node && node.kind === "pending") {
            // A ghost is not in the arch to be removed from it: taking it
            // off the canvas is un-staging the field, which is asked about
            // first the way a container with children is.
            if (!force) {
                return {
                    confirm: _t(
                        "Remove the pending field %s? It has not been applied, so nothing is lost but its definition.",
                        this.tagFor(token).replace(/^[^·]*· /, "")
                    ),
                };
            }
            const result = await this.removePending(node.pending ? node.pending.name : node.name);
            if (result !== undefined) {
                this.selection = null;
            }
            return result;
        }
        try {
            const result = await this._mutate(() =>
                this.orm.call("studio.view.editor", "remove_at", [
                    this.viewId,
                    this.packageId,
                    this.descriptor(token),
                    this.archVersion,
                    force,
                ])
            );
            if (result !== undefined) {
                this.selection = null;
            }
            return result;
        } catch (err) {
            if (compat.isConfirmError(err)) {
                return { confirm: messageOf(err), context: err.data.context };
            }
            throw err;
        }
    }

    /** One drop -- or one click-to-add -- at a token, one call. */
    async dropAt(token, position, payload, options = {}) {
        return this._mutate(
            () =>
                this.orm.call("studio.view.editor", "drop_at", [
                    this.viewId,
                    this.packageId,
                    { token, position },
                    payload,
                    this.archVersion,
                    this._canvasOptions(),
                ]),
            options
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
    async drop(token, position, payload) {
        if (
            payload.kind === "component" &&
            payload.component === "button" &&
            !(payload.values && payload.values.action_id)
        ) {
            this.buttonTarget = {
                token,
                position,
                arch_version: this.archVersion,
                serial: Date.now(),
            };
            return undefined;
        }
        if (
            payload.kind === "new_field" &&
            !(payload.values && payload.values.defined) &&
            this.needsDialog(payload.values && payload.values.ttype)
        ) {
            this.fieldTarget = {
                token,
                position,
                arch_version: this.archVersion,
                serial: Date.now(),
                ttype: payload.values.ttype,
                label: payload.values.field_description || "",
            };
            return undefined;
        }
        if (payload.kind === "new_field") {
            payload = { ...payload, values: this.fieldValues(payload.values) };
        }
        const result = await this.dropAt(token, position, payload, {
            prefix: _t("Can't drop here: "),
        });
        if (result === undefined) {
            return undefined;
        }
        if (["existing_field", "new_field"].includes(payload.kind)) {
            // The palette no longer offers a field the view now has.
            this.loadPalette();
        }
        return {
            ...result,
            created_field: Boolean(result.created),
            staged_field: Boolean(result.staged),
        };
    }

    /** Where a click-to-add goes: inside a container, after a leaf. */
    positionFor(token) {
        const node = this.nodes[token];
        return node && node.container ? "inside" : "after";
    }

    async addExistingField(name) {
        const token = this.anchorToken;
        return this._mutate(() =>
            this.orm.call("studio.view.editor", "drop_at", [
                this.viewId,
                this.packageId,
                { token, position: this.positionFor(token) },
                { kind: "existing_field", name },
                this.archVersion,
                this._canvasOptions(),
            ])
        ).then((result) => {
            this.loadPalette();
            return result;
        });
    }

    async addComponent(component, values = {}) {
        const token = this.anchorToken;
        if (component === "page") {
            // A tab has a rule of its own -- it lives in the notebook, and
            // the notebook may not exist yet -- which `add_container_at`
            // already knows.
            return this._mutate(() =>
                this.orm.call(
                    "studio.view.editor",
                    "add_container_at",
                    [this.viewId, this.packageId, this.descriptor(token), "page"],
                    { expected_arch_version: this.archVersion }
                )
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
    async addButton(values) {
        const target = this.buttonTarget;
        this.buttonTarget = null;
        if (target) {
            if (target.arch_version !== this.archVersion || !this.nodes[target.token]) {
                this.notification.add(_t("This view changed; drop the button again."), {
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
    fieldValues(values) {
        const {
            string,
            field_description: label,
            defined,
            error,
            inverse,
            relatedInfo,
            showCompute,
            type_label: typeLabel,
            ...rest
        } = values || {};
        const out = { ...rest, field_description: (label || string || "").trim() };
        if (!this.pythonOwned) {
            for (const key of LIVE_UNSUPPORTED) {
                delete out[key];
            }
        }
        if (!this.pythonOwned && out.name && !out.name.startsWith("x_")) {
            // The editor slugs the label the way the draft names a class
            // attribute; a live field is an `x_` row, and the server
            // derives that from the label when no name is sent.
            delete out.name;
        }
        if (Array.isArray(out.selection)) {
            out.selection = out.selection
                .filter((row) => row && row.value)
                .map((row, index) => ({
                    value: row.value,
                    label: row.label || row.value,
                    sequence: row.sequence || (index + 1) * 10,
                }));
            if (!out.selection.length) {
                delete out.selection;
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
    async addNewField(values) {
        const target = this.fieldTarget;
        this.fieldTarget = null;
        const payload = { kind: "new_field", values: { ...values, defined: true } };
        if (target) {
            if (target.arch_version !== this.archVersion || !this.nodes[target.token]) {
                this.notification.add(_t("This view changed; drop the field again."), {
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
    async inverseOptions(comodel) {
        const empty = { candidates: [], can_create: false, suggested: "", reason: "" };
        if (!comodel) {
            return empty;
        }
        if (this.pythonOwned) {
            const draft = await this._ensureDraft();
            if (!draft) {
                return empty;
            }
            return this.orm.call("studio.model.draft", "inverse_options", [[draft.id], comodel]);
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
                : _t(
                      "%(comodel)s has no link to %(model)s yet. Add one there first, then pick it here.",
                      { comodel, model: this.modelName }
                  ),
        };
    }

    /**
     * What a related path points at: its type, and so the new field's.
     * The draft walks the chain for a Python-owned model; for a live one
     * the field service does, from the same descriptions the views use.
     */
    async resolveRelated(path) {
        if (this.pythonOwned) {
            const draft = await this._ensureDraft();
            if (!draft) {
                return { ok: false, reason: _t("No draft to resolve the path on.") };
            }
            return this.orm.call("studio.model.draft", "resolve_related", [[draft.id], path]);
        }
        const steps = (path || "").split(".").filter(Boolean);
        if (!steps.length) {
            return { ok: false, reason: _t("Choose a field to follow.") };
        }
        const loaded = await this.env.services.field.loadPath(this.modelName, path);
        const last = loaded.modelsInfo[loaded.modelsInfo.length - 1];
        const def = last && last.fieldDefs[steps[steps.length - 1]];
        if (loaded.isInvalid || !def || loaded.modelsInfo.length !== steps.length) {
            return {
                ok: false,
                reason: _t("%s does not lead to a field of this model.", path),
            };
        }
        return {
            ok: true,
            ttype: def.type,
            comodel: def.relation || "",
            string: def.string || steps[steps.length - 1],
            stored: Boolean(def.store),
        };
    }

    /**
     * The draft the editor's questions go to, opened when the model has
     * none yet: `inverse_options` and `resolve_related` are methods of a
     * draft, and a Python-owned model with nothing staged has no draft
     * until its first drop. Opening one for a question is not an edit --
     * a clean draft is nothing to apply -- and the drop that follows
     * stages on it.
     */
    async _ensureDraft() {
        if (this.draft) {
            return this.draft;
        }
        if (this.draftId) {
            await this.loadDraft();
            if (this.draft) {
                return this.draft;
            }
        }
        const payload = await this._guard(() =>
            this.orm.call("studio.model.draft", "open_for_model", [this.modelName])
        );
        if (payload) {
            this.draft = markRaw(payload);
        }
        return this.draft;
    }

    /**
     * One call on the draft, then the tray and the canvas reloaded.
     *
     * The draft is opened on demand: editing the definition of a field the
     * class already has is the first thing a Python-owned model may be
     * asked, and it has no draft until something is staged on it.
     */
    async _onDraft(method, args, { silent = false } = {}) {
        if (!this.draftId && this.pythonOwned) {
            await this._ensureDraft();
        }
        const id = this.draftId;
        if (!id) {
            return undefined;
        }
        this.busy = true;
        try {
            const result = await this._guardDraft(
                () => this.orm.call("studio.model.draft", method, [[id], ...args]),
                silent
            );
            if (result === undefined) {
                return undefined;
            }
            await this.loadDraft();
            await this.refresh();
            return result;
        } finally {
            this.busy = false;
        }
    }

    async _guardDraft(run, silent) {
        try {
            return await run();
        } catch (err) {
            if (!(err && err.data)) {
                throw err;
            }
            if (!silent) {
                this.notification.add(messageOf(err), { type: "warning" });
            }
            return undefined;
        }
    }

    /** Un-stage a field: its ghost goes with it. */
    async removePending(name) {
        return this._onDraft("remove_field", [name]);
    }

    /** Change a staged field's definition; the ghost follows the label. */
    async updateStaged(name, values) {
        const { defined, error, inverse, relatedInfo, showCompute, ...rest } = values || {};
        if (rest.field_description && !rest.string) {
            rest.string = rest.field_description;
        }
        delete rest.field_description;
        return this._onDraft("update_field", [name, rest]);
    }

    /**
     * Reorder the class: `name` goes before `before`, or last. Class
     * order is the order the fields are written to Python and the order a
     * scaffolded view shows them in, so this is a layout gesture too.
     */
    async moveField(name, before = null) {
        return this._onDraft("move_field", [name, before]);
    }

    /**
     * Stage a field on the model without a place on this canvas -- from
     * the model's own field list rather than a drop. Apply puts it where
     * the balanced rule says, and the tray says so.
     */
    async addModelField(values) {
        const cleaned = this.fieldValues(values);
        const spec = { ...cleaned, string: cleaned.field_description };
        delete spec.field_description;
        return this._onDraft("add_field", [spec]);
    }

    /**
     * The model's fields in class order, each with the kind of change the
     * draft holds for it (`added`, `changed`, `removed`) or `null`. Fields
     * the draft has removed are listed still, marked, so the removal can
     * be seen and undone before Apply makes it a dropped column.
     */
    get modelFields() {
        const draft = this.draft;
        if (!draft) {
            return [];
        }
        const kinds = new Map();
        for (const change of draft.pending || []) {
            if (change.name && change.kind !== "model" && !change.model) {
                kinds.set(change.name, change.kind);
            }
        }
        const listed = (draft.fields || []).map((field) => ({
            ...field,
            pendingKind: kinds.get(field.name) || null,
        }));
        for (const change of draft.pending || []) {
            if (change.kind === "removed" && !change.model && !listed.some((f) => f.name === change.name)) {
                listed.push({ name: change.name, string: change.name, pendingKind: "removed" });
            }
        }
        return listed;
    }

    /** Everything the draft has staged, thrown away; the ghosts go too. */
    async discardDraft() {
        return this._onDraft("action_discard", []);
    }

    /** The unified diff of what Apply would write, for the dialog. */
    async previewDiff() {
        const id = this.draftId;
        if (!id) {
            return "";
        }
        const diff = await this._guard(() =>
            this.orm.call("studio.model.draft", "preview_diff", [[id]])
        );
        return diff || "";
    }

    /**
     * Apply the draft: write the package, reload it, place what was
     * staged where it was dropped.
     *
     * Returns `{ok: true}` once the console is current again, or `{ok:
     * false, message, destructive}` with the server's sentence when it
     * refused -- `destructive` when it refused because data would go, so
     * the dialog can offer "Apply anyway". Under a `restart` reload the
     * request itself may die with the server: that is not a refusal, and
     * the console waits for the server to come back, then reads the
     * draft to learn how far the apply got. The package may well have
     * been written and reloaded with the placement still to do -- that
     * part of the transaction died with the request -- and the draft
     * then still counts the fields as pending although the registry has
     * them; `place_pending` finishes that apply, and only when it cannot
     * is the apply reported as still pending.
     */
    async applyDraft(allowDestructive = false) {
        const id = this.draftId;
        if (!id) {
            return { ok: false, message: _t("There is nothing to apply."), destructive: false };
        }
        this.applying = true;
        try {
            try {
                await this.orm.call("studio.model.draft", "action_apply", [[id], allowDestructive]);
            } catch (err) {
                if (err && err.data) {
                    const message = messageOf(err);
                    return {
                        ok: false,
                        message,
                        destructive: !allowDestructive && /remove|drop|destructive|kept aside/i.test(message),
                    };
                }
                if (this.reloadMode !== "restart") {
                    throw err;
                }
                const back = await this._reconnect();
                if (!back) {
                    return {
                        ok: false,
                        message: _t("The server has not come back yet. Reload the page in a moment."),
                        destructive: false,
                    };
                }
            }
            await this._afterApply();
            if (this.pendingCount) {
                // The server came back with the draft still dirty: the
                // apply died before it committed, or after the package
                // was written and before the fields were placed.
                const finished = await this._placePending();
                if (!finished.placed) {
                    return {
                        ok: false,
                        message: finished.reason
                            ? _t(
                                  "The server restarted before the apply committed; it is still pending. %s",
                                  finished.reason
                              )
                            : _t("The server restarted before the apply committed; it is still pending."),
                        destructive: false,
                    };
                }
                await this._afterApply();
            }
            this.notification.add(_t("Applied."), { type: "success" });
            return { ok: true };
        } finally {
            this.applying = false;
        }
    }

    /**
     * The rest of an apply the server restarted in the middle of: the
     * placement and the baseline, from the anchors the draft still holds.
     * `{placed, reason}` as the server says it; a refusal is not thrown,
     * since the caller has a sentence of its own to put it in.
     */
    async _placePending() {
        const id = this.draftId;
        if (!id) {
            return { placed: false, reason: "" };
        }
        try {
            const result = await this.orm.call("studio.model.draft", "place_pending", [[id]]);
            return result || { placed: false, reason: "" };
        } catch (err) {
            if (err && err.data) {
                return { placed: false, reason: messageOf(err) };
            }
            throw err;
        }
    }

    /** Everything the console knows, read again after a reload. */
    async _afterApply() {
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

    /**
     * Wait for a restarting server: the canvas is asked for, with a
     * growing pause between tries, until it answers or the tries run
     * out. `true` when it answered.
     */
    async _reconnect(delays = RECONNECT_DELAYS_MS) {
        for (const delay of delays) {
            await new Promise((resolve) => setTimeout(resolve, delay));
            try {
                await this._fetchCanvas();
                return true;
            } catch (err) {
                if (err && err.data) {
                    // The server is up and refusing: it is back.
                    return true;
                }
            }
        }
        return false;
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
    async updateManualField(token, values) {
        const node = this.nodes[token];
        if (!node || !node.name || !this.packageId) {
            return undefined;
        }
        this.busy = true;
        this.status = "saving";
        try {
            const definition = await this.orm.call(
                "studio.view.editor",
                "update_manual_field",
                [this.modelName, node.name, values, this.packageId]
            );
            await this.refresh();
            this.renderSerial += 1;
            this.status = "saved";
            return definition;
        } catch (err) {
            if (!(err && err.data)) {
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

    async undo() {
        const entry = this.history.undo[0];
        if (!entry) {
            return;
        }
        await this._mutate(() =>
            this.orm.call("studio.view.edit", "action_undo", [[entry.id]], {
                expected_arch_version: this.archVersion,
            })
        );
        this.loadPalette();
    }

    async redo() {
        const entry = this.history.redo[0];
        if (!entry) {
            return;
        }
        await this._mutate(() =>
            this.orm.call("studio.view.edit", "action_redo", [[entry.id]], {
                expected_arch_version: this.archVersion,
            })
        );
        this.loadPalette();
    }

    // -- the sidebar's lists ----------------------------------------------

    async loadPalette() {
        if (!this.modelName || this.editableAs !== "canvas") {
            this.palette = [];
            return;
        }
        this.palette = markRaw(
            await this.orm.call("studio.view.editor", "get_addable_fields", [
                this.modelName,
                this.viewId,
            ])
        );
    }

    async loadAddable() {
        if (!this.modelName) {
            this.addable = [];
            return;
        }
        this.addable = markRaw(
            await this.orm.call("studio.view.editor", "addable_view_types", [
                this.modelName,
            ])
        );
    }

    async loadFieldPlan() {
        this.fieldPlan = markRaw(
            await this.orm.call("studio.view.editor", "new_field_plan", [this.viewId])
        );
    }

    async loadServerActions() {
        this.serverActions = markRaw(
            await this.orm.searchRead(
                "ir.actions.server",
                [["model_id.model", "=", this.modelName]],
                ["id", "name"],
                { limit: 200, order: "name" }
            )
        );
    }

    /** Create another kind of view for this model. */
    async addView(entry) {
        if (!entry.enabled || !this.packageId) {
            return undefined;
        }
        const dateField = (entry.date_fields || []).length ? entry.date_fields[0].name : null;
        const groupField = (entry.group_fields || []).length
            ? entry.group_fields[0].name
            : null;
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
                ])
            );
            if (result !== undefined) {
                this.notification.add(
                    _t("%s view created. It is now offered by this app's menu.", entry.label || entry.type),
                    { type: "success" }
                );
                await this.loadAddable();
                this.context = markRaw({ ...this.context, views: await this._viewsOf() });
            }
            return result;
        } finally {
            this.busy = false;
        }
    }

    async _viewsOf() {
        const context = await this.orm.call(
            "studio.view.editor",
            "editing_context",
            [this.viewId],
            {}
        );
        return context.views;
    }

    // -- search views: the three lists ------------------------------------

    async loadSearch() {
        this.search = markRaw(
            await this.orm.call("studio.view.editor", "search_elements", [this.viewId])
        );
    }

    async addSearchElement(kind, values) {
        if (!values.field) {
            return undefined;
        }
        return this._mutate(() =>
            this.orm.call("studio.view.editor", "add_search_element", [
                this.viewId,
                this.packageId,
                kind,
                values,
            ])
        );
    }

    async removeSearchElement(kind, name) {
        return this._mutate(() =>
            this.orm.call("studio.view.editor", "remove_search_element", [
                this.viewId,
                this.packageId,
                kind,
                name,
            ])
        );
    }

    /** Called by `_afterChange` after every mutation of a search view. */
    async _afterSearchChange() {
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

const KIND_LABELS = {
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

/** The sentence an RPC error carries for the user. */
export function messageOf(err) {
    if (err && err.data && err.data.message) {
        return err.data.message;
    }
    return (err && err.message) || _t("Something went wrong.");
}
