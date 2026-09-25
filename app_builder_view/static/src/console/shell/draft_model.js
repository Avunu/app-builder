import { markRaw } from "@odoo/owl";
import { _t } from "../l10n";
function messageOf(err) {
  const rpcErr = err;
  if (rpcErr?.data?.message) {
    return rpcErr.data.message;
  }
  return rpcErr?.message || String(_t("Something went wrong."));
}
class DraftModel {
  env;
  orm;
  notification;
  owner;
  draft;
  applying;
  busy;
  /** What the editing context said about a draft not yet read. */
  hints;
  constructor(env, owner) {
    this.env = env;
    this.orm = env.services.orm;
    this.notification = env.services.notification;
    this.owner = owner;
    this.draft = null;
    this.applying = false;
    this.busy = false;
    this.hints = { draft_id: false, reload_mode: false };
  }
  // -- reading ------------------------------------------------------------
  get modelName() {
    return this.owner.modelName;
  }
  get pythonOwned() {
    return Boolean(this.owner.pythonOwned);
  }
  /** The draft addressed, from whichever answer named it last. */
  get draftId() {
    return this.draft?.id || this.hints.draft_id || false;
  }
  get pendingCount() {
    return this.draft?.change_count || 0;
  }
  /** The staged changes, as the draft lists them for its tray. */
  get pendingChanges() {
    return this.draft?.pending || [];
  }
  get errors() {
    return this.draft?.errors || [];
  }
  get package() {
    return this.draft?.package || null;
  }
  /** `inproc` or `manual`: what an Apply costs on this server. */
  get reloadMode() {
    return this.package?.reload_mode || this.hints.reload_mode || false;
  }
  /** Why Apply is not on offer right now, or `""` when it is. */
  get applyBlocker() {
    if (!this.pendingCount) {
      return String(_t("Nothing is pending."));
    }
    if (this.package && !this.package.writable) {
      return String(_t("This package is read-only, so nothing can be applied."));
    }
    if (this.errors.length) {
      return this.errors.join("\n");
    }
    return "";
  }
  get canApply() {
    return !this.applying && !this.busy && !this.applyBlocker;
  }
  /** The staged definition of a pending field, from the draft. */
  stagedField(name) {
    const fields = this.draft?.fields || [];
    return fields.find((field) => field.name === name) || null;
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
    const kinds = /* @__PURE__ */ new Map();
    for (const change of draft.pending || []) {
      if (change.name && change.kind !== "model" && !change.model) {
        kinds.set(change.name, change.kind);
      }
    }
    const listed = (draft.fields || []).map((field) => ({
      ...field,
      pendingKind: kinds.get(field.name) || null
    }));
    for (const change of draft.pending || []) {
      if (change.kind === "removed" && !change.model && !listed.some((f) => f.name === change.name)) {
        listed.push({ name: change.name, string: change.name, pendingKind: "removed" });
      }
    }
    return listed;
  }
  // -- loading ------------------------------------------------------------
  /** What the view's editing context said; read before `load`. */
  setHints({
    draft_id: draftId = false,
    reload_mode: reloadMode = false
  } = {}) {
    this.hints = {
      draft_id: draftId || false,
      reload_mode: reloadMode || false
    };
  }
  /** Forget the draft: the shell moved to another model. */
  reset() {
    this.draft = null;
    this.hints = { draft_id: false, reload_mode: false };
  }
  /**
   * This user's draft on the model, when there is one.
   *
   * Never created here: opening the console is not an edit, and the
   * first staged drop makes the draft. A draft that has gone -- vacuumed
   * after its idle window -- is not an error either: the id is dropped
   * so the next drop opens a fresh one.
   */
  async load() {
    const id = this.draftId;
    if (!id) {
      this.draft = null;
      return null;
    }
    try {
      this.draft = markRaw(
        await this.orm.call("studio.model.draft", "load", [[id]])
      );
    } catch (err) {
      if (!err?.data) {
        throw err;
      }
      this.draft = null;
      this.hints.draft_id = false;
    }
    return this.draft;
  }
  /**
   * The draft the editor's questions go to, opened when the model has
   * none yet: `inverse_options` and `resolve_related` are methods of a
   * draft, and a Python-owned model with nothing staged has no draft
   * until its first drop. Opening one for a question is not an edit --
   * a clean draft is nothing to apply -- and the drop that follows
   * stages on it.
   */
  async ensure() {
    if (this.draft) {
      return this.draft;
    }
    if (this.draftId) {
      await this.load();
      if (this.draft) {
        return this.draft;
      }
    }
    if (!this.modelName || !this.pythonOwned) {
      return null;
    }
    const payload = await this._guard(
      () => this.orm.call("studio.model.draft", "open_for_model", [this.modelName])
    );
    if (payload) {
      this.draft = markRaw(payload);
    }
    return this.draft;
  }
  // -- calls ----------------------------------------------------------------
  /**
   * One call on the draft, then the draft read again. The draft is
   * opened on demand: editing the definition of a field the class
   * already has is the first thing a Python-owned model may be asked,
   * and it has no draft until something is staged on it.
   */
  async call(method, args, { silent = false } = {}) {
    if (!this.draftId && this.pythonOwned) {
      await this.ensure();
    }
    const id = this.draftId;
    if (!id) {
      return void 0;
    }
    this.busy = true;
    try {
      const result = await this._guardDraft(
        () => this.orm.call("studio.model.draft", method, [[id], ...args]),
        silent
      );
      if (result === void 0) {
        return void 0;
      }
      await this.load();
      return result;
    } finally {
      this.busy = false;
    }
  }
  async _guardDraft(run, silent) {
    try {
      return await run();
    } catch (err) {
      if (!err?.data) {
        throw err;
      }
      if (!silent) {
        this.notification.add(messageOf(err), { type: "warning" });
      }
      return void 0;
    }
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
  /** Un-stage a field: its ghost goes with it. */
  async removePending(name) {
    return this.call("remove_field", [name]);
  }
  /** Change a staged field's definition; the ghost follows the label. */
  async updateStaged(name, values) {
    const { defined, error, inverse, relatedInfo, showCompute, ...rest } = values || {};
    if (rest["field_description"] && !rest["string"]) {
      rest["string"] = rest["field_description"];
    }
    delete rest["field_description"];
    return this.call("update_field", [name, rest]);
  }
  /**
   * Reorder the class: `name` goes before `before`, or last. Class
   * order is the order the fields are written to Python and the order a
   * scaffolded view shows them in, so this is a layout gesture too.
   */
  async moveField(name, before = null) {
    return this.call("move_field", [name, before]);
  }
  /** Stage a field with no place on any canvas; Apply places it. */
  async addModelField(spec) {
    return this.call("add_field", [spec]);
  }
  /** Everything the draft has staged, thrown away; the ghosts go too. */
  async discard() {
    return this.call("action_discard", []);
  }
  /** The unified diff of what Apply would write, for the dialog. */
  async previewDiff() {
    const id = this.draftId;
    if (!id) {
      return "";
    }
    const diff = await this._guard(
      () => this.orm.call("studio.model.draft", "preview_diff", [[id]])
    );
    return diff || "";
  }
  /**
   * Apply the draft: write the package, reload it, place what was
   * staged where it was dropped.
   *
   * Returns `{ok: true}` once it went through, `{ok: true,
   * restartRequired: true}` when the server wrote the files but cannot
   * reload in place -- the fields stay pending until it is restarted,
   * and `placePending` finishes the apply afterwards -- or `{ok: false,
   * message, destructive}` with the server's sentence when it refused;
   * `destructive` when it refused because data would go, so the dialog
   * can offer "Apply anyway".
   */
  async apply(allowDestructive = false) {
    const id = this.draftId;
    if (!id) {
      return {
        ok: false,
        message: String(_t("There is nothing to apply.")),
        destructive: false
      };
    }
    this.applying = true;
    try {
      let result;
      try {
        result = await this.orm.call("studio.model.draft", "action_apply", [
          [id],
          allowDestructive
        ]);
      } catch (err) {
        if (!err?.data) {
          throw err;
        }
        const message = messageOf(err);
        return {
          ok: false,
          message,
          destructive: !allowDestructive && /remove|drop|destructive|kept aside/i.test(message)
        };
      }
      await this.load();
      if (result?.restart_required) {
        this.notification.add(
          String(
            _t(
              "Written to disk. Restart the server to load it; the changes stay pending until then."
            )
          ),
          { type: "info", sticky: true }
        );
        return { ok: true, restartRequired: true };
      }
      this.notification.add(String(_t("Applied.")), { type: "success" });
      return { ok: true, restartRequired: false };
    } finally {
      this.applying = false;
    }
  }
  /**
   * The rest of an apply that was written without being loaded: the
   * placement and the baseline, from the anchors the draft still holds,
   * once the server has been restarted. `{placed, reason}` as the
   * server says it; a refusal is not thrown, since the caller has a
   * sentence of its own to put it in.
   */
  async placePending() {
    const id = this.draftId;
    if (!id) {
      return { placed: false, reason: "" };
    }
    try {
      const result = await this.orm.call("studio.model.draft", "place_pending", [
        [id]
      ]);
      await this.load();
      return result || { placed: false, reason: "" };
    } catch (err) {
      if (err?.data) {
        return { placed: false, reason: messageOf(err) };
      }
      throw err;
    }
  }
}
export {
  DraftModel,
  messageOf
};
