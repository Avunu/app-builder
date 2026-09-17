import { _t } from "@web/core/l10n/translation";
import { DraftModel, messageOf } from "./draft_model";
import { paneAvailable, paneRegistry, resolvePane, warnLegacyTabs } from "./pane_registry";
const NEUTRAL_ACTIVITY = Object.freeze({
  busy: false,
  status: "saved",
  error: "",
  drag: null,
  applying: false
});
class StudioShell {
  env;
  orm;
  notification;
  hooks;
  params;
  packages;
  packageId;
  modelName;
  modelLabel;
  inventory;
  prefs;
  /** The Views pane's target; URL state, so held here. */
  view;
  pane;
  paneState;
  /** One model per pane key, kept while its scope holds. A plain
   * object, so a pane model read through the shell is reactive. */
  paneModels;
  loading;
  error;
  draft;
  /** What the editing context said last about the model in hand. */
  learned;
  entry;
  sidebarWidth;
  /** `{key, title, lines}` after a flow completes: shown once, under
   * the bar, until dismissed or the next flow. */
  callout;
  _changesTimer;
  constructor(env, params, hooks = {}) {
    this.env = env;
    this.orm = env.services.orm;
    this.notification = env.services.notification;
    this.hooks = hooks;
    this.params = params;
    this.packages = [];
    this.packageId = params.package_id || false;
    this.modelName = params.res_model || "";
    this.modelLabel = "";
    this.inventory = null;
    this.prefs = {};
    this.view = {
      view_id: params.view.view_id || false,
      view_type: params.view.view_type || false,
      res_id: params.view.res_id || false
    };
    this.pane = params.pane || "home";
    this.paneState = params.rec ? { rec: params.rec } : {};
    this.paneModels = {};
    this.loading = false;
    this.error = "";
    this.draft = new DraftModel(env, this);
    this.learned = { python_owned: false, python_owner_id: false };
    this.entry = params.entry || {};
    this.sidebarWidth = null;
    this.callout = null;
    warnLegacyTabs();
  }
  // -- reading ------------------------------------------------------------
  /** The chosen package's entry from `packages()`, or `null`. */
  get package() {
    return this.packages.find((p) => p.id === this.packageId) || null;
  }
  get packageWritable() {
    return Boolean(this.package && this.package.writable);
  }
  get pythonOwned() {
    return Boolean(this.learned.python_owned);
  }
  get activePane() {
    return paneRegistry.contains(this.pane) ? resolvePane(this.pane) : null;
  }
  get activeModel() {
    return this.paneModels[this.pane] || null;
  }
  /** What panes and tabs are told about the shell. */
  get paneContext() {
    return {
      packageId: this.packageId,
      package: this.package,
      modelName: this.modelName,
      view: this.view,
      pane: this.pane,
      inventory: this.inventory,
      pythonOwned: this.pythonOwned
    };
  }
  /** What the status pill reads, from the active pane or nothing. */
  get activity() {
    const model = this.activeModel;
    return model && model.activity || NEUTRAL_ACTIVITY;
  }
  /** The active pane's undo stack, when it has one. */
  get history() {
    const model = this.activeModel;
    return model && model.history || null;
  }
  get pendingCount() {
    return this.draft.pendingCount;
  }
  /** What the Changes badge counts: pending fields, drifted files, failed applies. */
  get changesCount() {
    const info = this.package;
    return this.pendingCount + (info ? info.drift_count || 0 : 0) + (info ? info.applies.failed || 0 : 0);
  }
  get restartRequired() {
    const info = this.package;
    return Boolean(info && info.applies && info.applies.awaiting_restart);
  }
  // -- loading ------------------------------------------------------------
  /**
   * What every pane needs before it opens: the packages, and which one
   * is in hand -- the URL's, else the one last used, else the suggested
   * one, else the only one.
   */
  async load() {
    const [packages, prefs] = await Promise.all([
      this.orm.call("studio.workspace", "packages", []),
      this.orm.call("studio.workspace", "user_prefs", [])
    ]);
    this.packages = packages;
    this.prefs = prefs || {};
    if (!this.packageId || !this.package) {
      const remembered = this.prefs.last_package_id;
      const candidates = [
        packages.find((p) => p.id === remembered),
        packages.find((p) => p.suggested),
        packages.find((p) => p.writable),
        packages[0]
      ];
      const chosen = candidates.find(Boolean);
      this.packageId = chosen ? chosen.id : false;
    }
    if (this.modelName) {
      await this._loadModelLabel();
    }
  }
  async refreshPackages() {
    this.packages = await this.orm.call("studio.workspace", "packages", []);
  }
  /**
   * The package's counters again, a moment after the last change:
   * several writes in a row ask once.
   */
  refreshChanges() {
    clearTimeout(this._changesTimer);
    this._changesTimer = setTimeout(() => {
      this.refreshPackages().catch(() => {
      });
    }, 800);
  }
  async _loadModelLabel() {
    if (!this.modelName) {
      this.modelLabel = "";
      return;
    }
    const names = await this.orm.call(
      "ir.model",
      "display_name_for",
      [[this.modelName]]
    );
    this.modelLabel = names[0]?.display_name || this.modelName;
  }
  async loadInventory() {
    if (!this.packageId) {
      this.inventory = null;
      return null;
    }
    this.inventory = await this.orm.call("studio.workspace", "inventory", [this.packageId]);
    return this.inventory;
  }
  /**
   * What a view's editing context says the shell should know: the model
   * the view is of, whether a package defines it in Python, the package
   * to suggest when none is chosen, and the draft that may exist.
   */
  async learnContext(context) {
    this.learned = {
      python_owned: Boolean(context.python_owned),
      python_owner_id: context.python_owner_id || false
    };
    if (context.python_owner_id && context.python_owner_id !== this.packageId) {
      this.packageId = context.python_owner_id;
    } else if (!this.packageId && context.suggested_package_id) {
      this.packageId = context.suggested_package_id;
    }
    const model = context.view && context.view.model;
    if (model && model !== this.modelName) {
      this.modelName = model;
      await this._loadModelLabel();
    }
    if (context.view && context.view.id) {
      this.view = {
        view_id: context.view.id,
        view_type: context.view.type || this.view.view_type,
        res_id: this.view.res_id
      };
    }
    this.draft.setHints(context);
    if (this.draft.draftId && !this.draft.draft) {
      await this.draft.load();
    }
  }
  // -- navigation ---------------------------------------------------------
  /**
   * Show a pane. Its model is made on first use and told to open or
   * reactivate; the URL follows; a refusal on the way -- a view that
   * does not resolve -- lands in `error` for this pane only, so the
   * bar and the other panes stay usable.
   */
  async openPane(key, patch = {}) {
    if (!paneRegistry.contains(key)) {
      key = "home";
    }
    const entry = resolvePane(key);
    if (!paneAvailable(entry, this.paneContext)) {
      key = "home";
    }
    this.pane = key;
    this.paneState = { ...patch };
    this.error = "";
    this.loading = true;
    try {
      const model = this.paneModel(key);
      if (model) {
        if (model.opened) {
          await model.reactivate?.();
        } else {
          await model.open(this.openTarget(key));
          model.opened = true;
        }
      }
    } catch (err) {
      if (!err?.data) {
        this.loading = false;
        throw err;
      }
      this.error = messageOf(err);
    }
    this.loading = false;
    this.pushUrl();
    this.setTitle();
  }
  /** What a pane model's `open` is handed. */
  openTarget(key) {
    if (key === "views") {
      return { ...this.view, model: this.modelName };
    }
    return { model: this.modelName, packageId: this.packageId, ...this.paneState };
  }
  /** The pane's model, made once and kept while its scope holds. */
  paneModel(key) {
    if (!this.paneModels[key]) {
      const entry = resolvePane(key);
      if (!entry.makeModel) {
        return null;
      }
      const model = entry.makeModel(this);
      model.opened = false;
      this.paneModels[key] = model;
    }
    return this.paneModels[key] || null;
  }
  /** Open a view of the model in hand on the Views pane. */
  async openView(target) {
    const model = target.model || target.res_model;
    if (model && model !== this.modelName) {
      await this.setModel(model, { open: false });
    }
    this.view = {
      view_id: target.view_id || false,
      view_type: target.view_type || false,
      res_id: target.res_id || false
    };
    const views = this.paneModels["views"];
    if (views) {
      views.opened = false;
    }
    await this.openPane("views");
  }
  /** Switch the package in the top bar; everything package-scoped starts over. */
  async setPackage(packageId) {
    if (packageId === this.packageId) {
      return;
    }
    this.packageId = packageId;
    this.inventory = null;
    this._dropPaneModels("package");
    await this.rememberPref("last_package_id", packageId);
    const entry = this.activePane;
    if (entry && paneAvailable(entry, this.paneContext)) {
      await this.openPane(this.pane, this.paneState);
    } else {
      await this.openPane("home");
    }
  }
  /**
   * Change the model on the crumb. Model-scoped pane models start over;
   * the pane in hand is re-opened on the new model, or Home when it
   * cannot be shown without one.
   */
  async setModel(modelName, { open = true } = {}) {
    if (modelName === this.modelName) {
      return;
    }
    this.modelName = modelName || "";
    this.learned = { python_owned: false, python_owner_id: false };
    this.draft.reset();
    this.view = { view_id: false, view_type: false, res_id: false };
    this._dropPaneModels("model");
    await this._loadModelLabel();
    if (modelName) {
      this.orm.call("studio.workspace", "remember_model", [modelName]).catch(() => {
      });
    }
    if (!open) {
      return;
    }
    const entry = this.activePane;
    if (entry && entry.scope === "model") {
      await this.openPane(this.pane);
    } else {
      this.pushUrl();
    }
  }
  _dropPaneModels(scope) {
    for (const key of Object.keys(this.paneModels)) {
      const entry = paneRegistry.contains(key) ? resolvePane(key) : null;
      const paneScope = entry ? entry.scope : "model";
      if (scope === "package" && paneScope === "package") {
        delete this.paneModels[key];
      }
      if (scope === "model" && paneScope !== "package") {
        delete this.paneModels[key];
      }
    }
  }
  /** Pane-local state that belongs in the URL: a selected record. */
  setPaneState(patch) {
    this.paneState = { ...this.paneState, ...patch };
    this.pushUrl();
  }
  // -- the url ------------------------------------------------------------
  /**
   * What the URL carries. `res_model` rather than `model`: the router
   * keeps `model` for a window action's path and drops it from a
   * client action's query. Keys absent from a pane are set to
   * `undefined`, which the router leaves out.
   */
  urlState() {
    const onViews = this.pane === "views";
    return {
      pane: this.pane,
      package_id: this.packageId || void 0,
      res_model: this.modelName || void 0,
      view_type: onViews && this.view.view_type || void 0,
      view_id: onViews && this.view.view_id || void 0,
      res_id: onViews && this.view.res_id || void 0,
      rec: this.paneState.rec || void 0
    };
  }
  pushUrl() {
    if (this.hooks.pushState) {
      this.hooks.pushState(this.urlState());
    }
  }
  setTitle() {
    if (!this.hooks.setTitle) {
      return;
    }
    const entry = this.activePane;
    const parts = [String(_t("Studio"))];
    if (this.modelLabel && entry && entry.scope !== "package") {
      parts.push(this.modelLabel);
    }
    if (entry && entry.key !== "views") {
      parts.push(entry.label);
    } else if (this.view.view_type) {
      parts.push(this.view.view_type);
    }
    this.hooks.setTitle(parts.join(" · "));
  }
  // -- the draft and the package -------------------------------------------
  /** Apply the draft, then let the active pane read everything again. */
  async apply(allowDestructive = false) {
    const result = await this.draft.apply(allowDestructive);
    if (result && result.ok) {
      const model = this.activeModel;
      if (model && model.afterApply) {
        await model.afterApply();
      }
      await this.refreshPackages();
    }
    return result;
  }
  /** Discard the draft, then let the active pane drop its ghosts. */
  async discard() {
    const result = await this.draft.discard();
    const model = this.activeModel;
    if (result !== void 0 && model && model.refresh) {
      await model.refresh();
    }
    return result;
  }
  async rememberPref(key, value) {
    this.prefs = { ...this.prefs, [key]: value };
    try {
      await this.orm.call("studio.workspace", "set_user_pref", [key, value]);
    } catch (err) {
      if (!err?.data) {
        throw err;
      }
    }
  }
  // -- entry ----------------------------------------------------------------
  /**
   * One shape for every way in: the cog, the systray, `action_compose`,
   * the report editor's alias, the Studio menu, and a reload of the
   * console's own URL (the router state comes back as `action.params`).
   */
  static fromParams(raw) {
    const params = raw || {};
    const view = {
      view_id: params["view_id"] || false,
      view_type: params["view_type"] || false,
      res_id: params["res_id"] || false
    };
    const pane = params["pane"] || (view.view_type || view.view_id ? "views" : "home");
    return {
      pane,
      package_id: params["package_id"] || false,
      res_model: params["res_model"] || params["model"] || "",
      view,
      rec: params["rec"] || false,
      entry: {
        opened_from: params["opened_from"] || "",
        previous_action: params["previous_action"] || null,
        previous_view_type: params["previous_view_type"] || false,
        action_id: params["action_id"] || false
      }
    };
  }
}
export {
  StudioShell
};
