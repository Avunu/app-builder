import { markRaw } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import * as compat from "./compat";
import { messageOf } from "./shell/draft_model";
const DIALOG_TYPES = /* @__PURE__ */ new Set([
  "many2one",
  "one2many",
  "many2many",
  "tags",
  "lines",
  "selection",
  "reference",
  "related"
]);
const LIVE_UNSUPPORTED = ["default", "compute", "compute_body", "depends", "digits"];
class ConsoleModel {
  env;
  orm;
  notification;
  shell;
  params;
  context;
  canvas;
  selection;
  /** Counts the times something was *selected* -- a click, a drop --
   * as opposed to carried across a remount; the sidebar opens the
   * properties on the former and not on the latter. */
  selectionSerial;
  hover;
  /** Bumped by `reveal`: the canvas brings `revealToken` on screen --
   * its page switched to, its element scrolled to -- on the bump. */
  revealSerial;
  revealToken;
  /** Set by the outline while it is mounted: how the drag reaches
   * its rows and its zone layer (`sidebar/outline.js`), read by
   * `drag.js` when a drag starts. `null` when there is no outline. */
  outlineDrag;
  drag;
  /** Where a Button tile was dropped: the tile needs an action before
   * anything is written, so the drop is held here and the palette
   * asks for the rest, then sends it to this spot. Held with the
   * version of the arch its token was minted on, like any descriptor:
   * the canvas may be replaced while the palette is still asking. */
  buttonTarget;
  /** Where a field tile that needs its definition first was dropped: a
   * relation without a model, a selection without values, is not a
   * field yet, so the drop is held here -- the same way, with the
   * same version -- while the field editor asks for the rest. */
  fieldTarget;
  busy;
  status;
  statusError;
  showInvisible;
  /** The notebook page the user is looking at, so a remount lands on it.
   * `TabMemory | null`, not `unknown`: `rememberPage` (below) only ever
   * stores what `identity.ts:describeTab` builds, and `canvas.ts`'s
   * `onPatched` -- the first real reader -- reads it back as exactly
   * that shape. */
  activePage;
  palette;
  addable;
  fieldPlan;
  /** The picker's entries for this model, each saying whether it can
   * be made live here and whether it needs the editor first. */
  fieldTypes;
  /** Bumped when the model's fields changed under an unchanged arch
   * -- a manual field renamed -- so the canvas remounts on it. */
  renderSerial;
  serverActions;
  search;
  /** Bumped after every search-view edit: the host list previewing the
   * search view loads it the ordinary way and has to be remounted. */
  searchSerial;
  descriptions;
  /** Set by the shell itself after the first `open()`. */
  opened;
  constructor(env, shell) {
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
  _reset() {
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
  get packageId() {
    return this.shell.packageId;
  }
  get modelLabel() {
    return this.shell.modelLabel;
  }
  /** The shell's draft on this model; see `shell/draft_model.ts`. */
  get draftModel() {
    return this.shell.draft;
  }
  get draft() {
    return this.draftModel.draft;
  }
  get applying() {
    return this.draftModel.applying;
  }
  /** What the status pill reads, whichever pane is on. */
  get activity() {
    return {
      busy: this.busy,
      status: this.status,
      error: this.statusError,
      drag: this.drag,
      applying: this.applying
    };
  }
  // -- reading ------------------------------------------------------------
  get view() {
    return this.canvas && this.canvas.view || this.context && this.context.view || {};
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
    return this.canvas && this.canvas.editable_as || "canvas";
  }
  get archVersion() {
    return this.canvas ? this.canvas.arch_version : null;
  }
  get nodes() {
    return this.canvas && this.canvas.nodes || {};
  }
  get root() {
    return this.canvas ? this.canvas.root : null;
  }
  get history() {
    return this.canvas && this.canvas.history || { undo: [], redo: [] };
  }
  get package() {
    return this.canvas && this.canvas.package || null;
  }
  /** Whether an edit can be recorded at all. */
  get canWrite() {
    return Boolean(this.packageId) && !this.busy && !this.applying;
  }
  get selectedNode() {
    if (!this.selection) {
      return null;
    }
    return this.nodes[this.selection.token] ?? null;
  }
  // -- the draft ----------------------------------------------------------
  /** Whether a new field here is a class attribute waiting for an Apply. */
  get pythonOwned() {
    return Boolean(this.context && this.context.python_owned);
  }
  /** The draft the console addresses, from whichever answer named it last. */
  get draftId() {
    return this.draftModel.draftId || this.canvas && this.canvas.draft_id || false;
  }
  /** The ghosts the canvas carries. */
  get pending() {
    return this.canvas && this.canvas.pending || [];
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
    return this.draftModel.pendingChanges;
  }
  get draftErrors() {
    return this.draftModel.errors;
  }
  /** `inproc` or `manual`: what an Apply costs on this server. */
  get reloadMode() {
    return this.draftModel.reloadMode || this.context && this.context.reload_mode || false;
  }
  /** Why Apply is not on offer right now, or `""` when it is. */
  get applyBlocker() {
    if (!this.pendingCount) {
      return String(_t("Nothing is pending."));
    }
    return this.draftModel.applyBlocker;
  }
  get canApply() {
    return !this.applying && !this.busy && !this.applyBlocker;
  }
  /** The staged definition of a pending field, from the draft. */
  stagedField(name) {
    return this.draftModel.stagedField(name);
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
    if (entry && entry.needs_dialog !== void 0) {
      return Boolean(entry.needs_dialog);
    }
    return Boolean(key) && DIALOG_TYPES.has(key);
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
    return name && node.kind !== "root" ? `${kind} · ${name}` : String(kind);
  }
  // -- loading ------------------------------------------------------------
  /**
   * Open a view: `{view_id, model, view_type, res_id}`, any of which the
   * server fills in when missing. Everything about the previous view is
   * dropped first; the shell keeps the package, the model and the draft.
   */
  async open(target = {}) {
    this._reset();
    this.params = {
      view_id: target.view_id || false,
      model: target.model || target.res_model || false,
      view_type: target.view_type || false,
      res_id: target.res_id || false
    };
    return this.load();
  }
  /** The view again, after another pane may have changed the model. */
  async reactivate() {
    if (!this.canvas) {
      return this.load();
    }
    await this.loadContext();
    await this.refresh({ keepSelection: true });
    await this.loadDraft();
    return void 0;
  }
  async load() {
    await this.loadContext();
    await this.refresh({ keepSelection: false });
    const loads = [this.loadFieldPlan(), this.loadDraft()];
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
    await this.shell.learnContext(this.context);
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
      entries = await this.orm.call(
        "studio.view.editor",
        "field_types_for",
        [this.modelName]
      );
    } catch (err) {
      if (!err?.data) {
        throw err;
      }
      entries = this.context && this.context.field_types || [];
    }
    const pythonOwned = this.pythonOwned;
    this.fieldTypes = markRaw(
      entries.map((entry) => ({
        ...entry,
        live: entry.live !== void 0 ? entry.live : entry.enabled && !pythonOwned,
        needs_dialog: entry.needs_dialog !== void 0 ? entry.needs_dialog : DIALOG_TYPES.has(entry.value)
      }))
    );
  }
  /**
   * This user's draft on the model, when there is one -- the shell's,
   * read again. A canvas that named a draft the shell does not know of
   * yet hands the id over first.
   */
  async loadDraft() {
    if (!this.draftModel.draftId && this.canvas && this.canvas.draft_id) {
      this.draftModel.setHints({
        draft_id: this.canvas.draft_id,
        reload_mode: this.reloadMode
      });
    }
    return this.draftModel.load();
  }
  _canvasOptions() {
    return {
      show_invisible: this.showInvisible,
      res_id: this.params.res_id || false,
      package_id: this.packageId || false,
      draft_id: this.context && this.context.draft_id || false
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
      { ...this._canvasOptions(), ...options }
    ]);
  }
  _replaceCanvas(payload, {
    keepSelection = true,
    select = null
  } = {}) {
    const previousNodes = this.nodes;
    const previous = this.selectedNode;
    const oldToken = this.selection ? this.selection.token : null;
    const before = this.canvas;
    this.canvas = markRaw(payload);
    if (before && before.arch_version === payload.arch_version && before.arch !== payload.arch) {
      this.renderSerial += 1;
    }
    this.descriptions = markRaw({});
    this.hover = null;
    const selectNode = select ? this.nodes[select] : void 0;
    if (select && selectNode) {
      this.selection = null;
      this.select(select);
    } else if (keepSelection && previous) {
      const token = this._findAgain(previous, oldToken, previousNodes);
      const node = token ? this.nodes[token] : void 0;
      this.selection = token && node ? { token, node } : null;
    } else {
      this.selection = null;
    }
    this._carryTarget(
      "buttonTarget",
      previousNodes,
      String(_t("This view changed; drop the button again."))
    );
    this._carryTarget(
      "fieldTarget",
      previousNodes,
      String(_t("This view changed; drop the field again."))
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
    const alike = (node2, other) => Boolean(node2) === Boolean(other) && (!node2 || !other || node2.tag === other.tag && node2.name === other.name);
    const same = (node2) => alike(node2, previous) && alike(node2 && node2.parent ? this.nodes[node2.parent] : null, oldParent);
    if (previous.name) {
      const found = Object.entries(this.nodes).filter(([, node2]) => same(node2));
      return found.length === 1 ? found[0]?.[0] ?? null : null;
    }
    const node = this.nodes[oldToken];
    return same(node) && node && node.index === previous.index ? oldToken : null;
  }
  /**
   * The token a node has after a re-stamp: the same one when it still
   * names the same node, else the first node of the same tag and name,
   * else the node at the same place under a parent of the same name.
   */
  _findAgain(previous, oldToken, previousNodes) {
    const same = (node) => node ? node.tag === previous.tag : false;
    const nodes = this.nodes;
    const current = oldToken ? nodes[oldToken] : void 0;
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
      if (!oldParent && !parent || oldParent && parent && parent.tag === oldParent.tag && parent.name === oldParent.name) {
        return token;
      }
    }
    return null;
  }
  // -- selecting ----------------------------------------------------------
  select(token) {
    const node = token ? this.nodes[token] : void 0;
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
  clearSelection() {
    this.selection = null;
  }
  /**
   * Select `token` and ask the canvas to bring it on screen: the page
   * it is on switched to, its element scrolled into view. What the
   * outline does on a click, where the row may stand for something the
   * canvas is not showing.
   */
  reveal(token) {
    this.select(token);
    if (token && this.nodes[token]) {
      this.revealToken = token;
      this.revealSerial += 1;
    }
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
    if (payload === void 0) {
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
    const cached = this.descriptions[token];
    if (cached) {
      return cached;
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
        this.descriptor(token)
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
    const target = markRaw({
      kind: node.kind,
      name: node.name,
      token,
      ...found,
      field: found.found && found.field || node.field || null
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
        String(_t("Choose a studio package to record this change in first.")),
        { type: "warning" }
      );
      return void 0;
    }
    this.busy = true;
    this.status = "saving";
    this.statusError = "";
    try {
      const result = await run();
      const raw = result;
      if (raw && raw.stale) {
        this._replaceCanvas(raw.canvas);
        await this._afterChange();
        this._staleNotice();
        this.status = "saved";
        return void 0;
      }
      if (raw && raw.draft) {
        this.draftModel.draft = markRaw(raw.draft);
      }
      if (raw && raw.canvas) {
        this._replaceCanvas(raw.canvas, { select: select || raw.select || null });
      } else {
        await this.refresh();
        const created = raw && raw.created_name;
        const wanted = select || created && this._tokenNamed(created);
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
        return void 0;
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
      if (!err?.data) {
        throw err;
      }
      return void 0;
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
    this.notification.add(String(_t("This view changed; it was refreshed — try again.")), {
      type: "info"
    });
  }
  /** Run a read that may fail, showing the reason rather than dying. */
  async _guard(run) {
    try {
      return await run();
    } catch (err) {
      if (!err?.data) {
        throw err;
      }
      this.notification.add(messageOf(err), { type: "warning" });
      return void 0;
    }
  }
  /** `apply_at` with a token descriptor and the version it came with. */
  async applyAt(token, operation) {
    return this._mutate(
      () => this.orm.call("studio.view.editor", "apply_at", [
        this.viewId,
        this.packageId,
        this.descriptor(token),
        operation,
        this.archVersion
      ])
    );
  }
  /**
   * A raw operation, for the one canvas whose locators the server hands
   * out ready-made: a report's `locate_expression` and `body_anchor`
   * answer with the xpath, since a rendered document carries no tokens.
   */
  async applyOperation(operation) {
    return this._mutate(
      () => this.orm.call("studio.view.editor", "apply_operation", [
        this.viewId,
        this.packageId,
        operation,
        this.archVersion
      ])
    );
  }
  /** Write attributes on a node, as the properties rows do. */
  async setAttributes(token, attrs) {
    return this.applyAt(token, {
      type: "set_attributes",
      position: "attributes",
      attrs
    });
  }
  /**
   * Give a field the label the form would not draw for it: a `<label for>`
   * before it. Where the form draws the label itself -- a field in a
   * group -- the switch is the `nolabel` attribute and goes through
   * `setAttributes` instead; the panel knows which from `node.label`.
   */
  async showLabel(token) {
    return this._mutate(
      () => this.orm.call("studio.view.editor", "show_label_at", [
        this.viewId,
        this.packageId,
        this.descriptor(token),
        this.archVersion
      ])
    );
  }
  /**
   * Show or hide a form field's label, whichever way the form draws
   * it: `nolabel` where a group draws the label, a `<label for>` of its
   * own anywhere else. What the properties' switch and the outline's
   * menu both do; `node.label` says which way applies.
   */
  async setLabelShown(token, shown) {
    const node = this.nodes[token];
    const label = node && node.kind === "field" ? node.label : null;
    if (!label) {
      return void 0;
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
    return void 0;
  }
  /**
   * Take that label away again. `remove` on the label's own token, but
   * the field stays selected: the label was never what was selected.
   */
  async hideLabel(labelToken) {
    return this._mutate(
      () => this.orm.call("studio.view.editor", "remove_at", [
        this.viewId,
        this.packageId,
        this.descriptor(labelToken),
        this.archVersion,
        false
      ])
    );
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
      if (!force) {
        return {
          confirm: String(
            _t(
              "Remove the pending field %s? It has not been applied, so nothing is lost but its definition.",
              this.tagFor(token).replace(/^[^·]*· /, "")
            )
          ),
          context: void 0
        };
      }
      const result = await this.removePending(
        node.pending ? node.pending.name : node.name || ""
      );
      if (result !== void 0) {
        this.selection = null;
      }
      return result;
    }
    try {
      const result = await this._mutate(
        () => this.orm.call("studio.view.editor", "remove_at", [
          this.viewId,
          this.packageId,
          this.descriptor(token),
          this.archVersion,
          force
        ])
      );
      if (result !== void 0) {
        this.selection = null;
      }
      return result;
    } catch (err) {
      if (compat.isConfirmError(err)) {
        return { confirm: messageOf(err), context: err.data?.context };
      }
      throw err;
    }
  }
  /** One drop -- or one click-to-add -- at a token, one call. */
  async dropAt(token, position, payload, options = {}) {
    return this._mutate(
      () => this.orm.call("studio.view.editor", "drop_at", [
        this.viewId,
        this.packageId,
        { token, position },
        payload,
        this.archVersion,
        this._canvasOptions()
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
    const values = payload["values"];
    if (payload.kind === "component" && payload.component === "button" && !(values && values["action_id"])) {
      this.buttonTarget = {
        token,
        position,
        arch_version: this.archVersion,
        serial: Date.now()
      };
      return void 0;
    }
    if (payload.kind === "new_field" && !(values && values["defined"]) && this.needsDialog(values ? values["ttype"] : void 0)) {
      this.fieldTarget = {
        token,
        position,
        arch_version: this.archVersion,
        serial: Date.now(),
        ttype: values && values["ttype"] || "",
        label: values && values["field_description"] || ""
      };
      return void 0;
    }
    let sendPayload = payload;
    if (payload.kind === "new_field") {
      sendPayload = { ...payload, values: this.fieldValues(values) };
    }
    const result = await this.dropAt(token, position, sendPayload, {
      prefix: String(_t("Can't drop here: "))
    });
    if (result === void 0) {
      return void 0;
    }
    if (["existing_field", "new_field"].includes(payload.kind)) {
      void this.loadPalette();
    }
    return {
      ...result,
      created_field: Boolean(result.created),
      staged_field: Boolean(result.staged)
    };
  }
  /** Where a click-to-add goes: inside a container, after a leaf. */
  positionFor(token) {
    const node = token ? this.nodes[token] : void 0;
    return node && node.container ? "inside" : "after";
  }
  async addExistingField(name) {
    const token = this.anchorToken;
    const result = await this._mutate(
      () => this.orm.call("studio.view.editor", "drop_at", [
        this.viewId,
        this.packageId,
        { token, position: this.positionFor(token) },
        { kind: "existing_field", name },
        this.archVersion,
        this._canvasOptions()
      ])
    );
    void this.loadPalette();
    return result;
  }
  async addComponent(component, values = {}) {
    const token = this.anchorToken;
    if (component === "page") {
      return this._mutate(
        () => this.orm.call(
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
      values
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
        this.notification.add(String(_t("This view changed; drop the button again.")), {
          type: "info"
        });
        return void 0;
      }
      return this.drop(target.token, target.position, {
        kind: "component",
        component: "button",
        values
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
    const out = {
      ...rest,
      field_description: (typeof label === "string" ? label : "").trim()
    };
    if (!this.pythonOwned) {
      for (const key of LIVE_UNSUPPORTED) {
        delete out[key];
      }
    }
    const name = out["name"];
    if (!this.pythonOwned && typeof name === "string" && !name.startsWith("x_")) {
      delete out["name"];
    }
    if (Array.isArray(out["selection"])) {
      const rows = out["selection"];
      const cleaned = rows.filter((row) => row && row["value"]).map((row, index) => ({
        value: row["value"],
        label: row["label"] || row["value"],
        sequence: row["sequence"] || (index + 1) * 10
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
  async addNewField(values) {
    const target = this.fieldTarget;
    this.fieldTarget = null;
    const payload = { kind: "new_field", values: { ...values, defined: true } };
    if (target) {
      if (target.arch_version !== this.archVersion || !this.nodes[target.token]) {
        this.notification.add(String(_t("This view changed; drop the field again.")), {
          type: "info"
        });
        return void 0;
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
    const empty = {
      candidates: [],
      can_create: false,
      suggested: "",
      reason: ""
    };
    if (!comodel) {
      return empty;
    }
    if (this.pythonOwned) {
      const draft = await this._ensureDraft();
      if (!draft) {
        return empty;
      }
      return this.orm.call("studio.model.draft", "inverse_options", [
        [draft.id],
        comodel
      ]);
    }
    const fields = await this.env.services.field.loadFields(comodel, {
      attributes: ["type", "relation", "string"]
    });
    const candidates = Object.entries(fields).filter(([, def]) => def.type === "many2one" && def.relation === this.modelName).map(([name, def]) => ({ name, string: def.string || name })).sort((a, b) => a.name.localeCompare(b.name));
    return {
      ...empty,
      candidates,
      reason: candidates.length ? "" : String(
        _t(
          "%(comodel)s has no link to %(model)s yet. Add one there first, then pick it here.",
          { comodel, model: this.modelName }
        )
      )
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
        return { ok: false, reason: String(_t("No draft to resolve the path on.")) };
      }
      return this.orm.call("studio.model.draft", "resolve_related", [
        [draft.id],
        path
      ]);
    }
    const steps = (path || "").split(".").filter(Boolean);
    if (!steps.length) {
      return { ok: false, reason: String(_t("Choose a field to follow.")) };
    }
    const loaded = await this.env.services.field.loadPath(this.modelName, path);
    const lastStep = steps[steps.length - 1];
    const last = loaded.modelsInfo[loaded.modelsInfo.length - 1];
    const def = last ? last.fieldDefs[lastStep] : void 0;
    if (loaded.isInvalid || !def || loaded.modelsInfo.length !== steps.length) {
      return {
        ok: false,
        reason: String(_t("%s does not lead to a field of this model.", path))
      };
    }
    return {
      ok: true,
      ttype: def.type,
      comodel: def.relation || "",
      string: def.string || lastStep,
      stored: Boolean(def.store)
    };
  }
  /** The draft the editor's questions go to, opened when the model has
   * none yet; the shell's, opened on this model. */
  async _ensureDraft() {
    return this.draftModel.ensure();
  }
  /**
   * One call on the draft, then the tray and the canvas reloaded: the
   * ghosts follow what was staged.
   */
  async _onDraft(method, args, { silent = false } = {}) {
    this.busy = true;
    try {
      const result = await this.draftModel.call(method, args, { silent });
      if (result === void 0) {
        return void 0;
      }
      await this.refresh();
      return result;
    } finally {
      this.busy = false;
    }
  }
  /** Un-stage a field: its ghost goes with it. */
  async removePending(name) {
    return this._onDraft("remove_field", [name]);
  }
  /** Change a staged field's definition; the ghost follows the label. */
  async updateStaged(name, values) {
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
    const spec = { ...cleaned, string: cleaned["field_description"] };
    delete spec["field_description"];
    return this._onDraft("add_field", [spec]);
  }
  /** The model's fields in class order, with what the draft holds for each. */
  get modelFields() {
    return this.draftModel.modelFields;
  }
  /** Everything the draft has staged, thrown away; the ghosts go too. */
  async discardDraft() {
    return this._onDraft("action_discard", []);
  }
  /** The unified diff of what Apply would write, for the dialog. */
  async previewDiff() {
    return this.draftModel.previewDiff();
  }
  /**
   * Apply the draft through the shell, then read everything again: the
   * package was reloaded, so the context, the canvas and every list are
   * stale. `{ok, message, destructive, restartRequired}` as the draft
   * says it.
   */
  async applyDraft(allowDestructive = false) {
    const result = await this.draftModel.apply(allowDestructive);
    if (result && result.ok) {
      await this.afterApply();
    }
    return result;
  }
  /** Everything the console knows, read again after a reload. */
  async afterApply() {
    await this.loadContext();
    await this.refresh();
    await Promise.all([
      this.loadDraft(),
      this.loadPalette(),
      this.loadFieldPlan(),
      this.loadFieldTypes()
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
  async updateManualField(token, values) {
    const node = this.nodes[token];
    if (!node || !node.name || !this.packageId) {
      return void 0;
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
      if (!err?.data) {
        throw err;
      }
      this.status = "error";
      this.statusError = messageOf(err);
      this.notification.add(this.statusError, { type: "warning" });
      return void 0;
    } finally {
      this.busy = false;
    }
  }
  async undo() {
    const entry = this.history.undo[0];
    if (!entry) {
      return;
    }
    await this._mutate(
      () => this.orm.call("studio.view.edit", "action_undo", [[entry.id]], {
        expected_arch_version: this.archVersion
      })
    );
    void this.loadPalette();
  }
  async redo() {
    const entry = this.history.redo[0];
    if (!entry) {
      return;
    }
    await this._mutate(
      () => this.orm.call("studio.view.edit", "action_redo", [[entry.id]], {
        expected_arch_version: this.archVersion
      })
    );
    void this.loadPalette();
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
        this.viewId
      ])
    );
  }
  async loadAddable() {
    if (!this.modelName) {
      this.addable = [];
      return;
    }
    this.addable = markRaw(
      await this.orm.call(
        "studio.view.editor",
        "addable_view_types",
        [this.modelName]
      )
    );
  }
  async loadFieldPlan() {
    this.fieldPlan = markRaw(
      await this.orm.call("studio.view.editor", "new_field_plan", [
        this.viewId
      ])
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
      return void 0;
    }
    const dateField = entry.date_fields[0]?.name ?? null;
    const groupField = entry.group_fields[0]?.name ?? null;
    if (entry.type === "calendar" && !dateField) {
      return void 0;
    }
    if (entry.type === "timeline" && (!dateField || !groupField)) {
      return void 0;
    }
    this.busy = true;
    try {
      const result = await this._guard(
        () => this.orm.call("studio.view.editor", "add_view", [
          this.modelName,
          entry.type,
          this.packageId,
          dateField,
          groupField
        ])
      );
      if (result !== void 0) {
        this.notification.add(
          String(
            _t(
              "%s view created. It is now offered by this app's menu.",
              entry.label || entry.type
            )
          ),
          { type: "success" }
        );
        await this.loadAddable();
        this.context = markRaw({
          ...this.context,
          views: await this._viewsOf()
        });
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
      await this.orm.call("studio.view.editor", "search_elements", [
        this.viewId
      ])
    );
  }
  async addSearchElement(kind, values) {
    if (!values["field"]) {
      return void 0;
    }
    return this._mutate(
      () => this.orm.call("studio.view.editor", "add_search_element", [
        this.viewId,
        this.packageId,
        kind,
        values
      ])
    );
  }
  async removeSearchElement(kind, name) {
    return this._mutate(
      () => this.orm.call("studio.view.editor", "remove_search_element", [
        this.viewId,
        this.packageId,
        kind,
        name
      ])
    );
  }
  /** Called by `_afterChange` after every mutation of a search view. */
  async _afterSearchChange() {
    await this.loadSearch();
    compat.clearViewCaches(this.env);
    this.searchSerial += 1;
  }
}
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
  html: _t("Block")
};
export {
  ConsoleModel,
  messageOf
};
