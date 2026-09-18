import { Component, useState } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog, useService } from "./odoo";
import { ApplyDialog } from "./apply_dialog";
import { paneTabs } from "./shell/pane_registry";
const VIEW_ICONS = {
  list: "oi oi-view-list",
  form: "fa fa-address-card",
  kanban: "oi oi-view-kanban",
  calendar: "fa fa-calendar",
  pivot: "oi oi-view-pivot",
  graph: "fa fa-area-chart",
  activity: "fa fa-clock-o",
  search: "oi oi-search",
  qweb: "fa fa-file-text-o"
};
const HEALTH_DOT = {
  read_only: "grey",
  missing: "red",
  failed_apply: "red",
  drifted: "red",
  restart_required: "amber",
  pending: "amber",
  pending_write: "amber",
  uncommitted: "amber",
  not_installed: "amber"
};
function healthDot(info) {
  const flags = info && info.health || [];
  if (flags.some((f) => HEALTH_DOT[f] === "red")) {
    return "red";
  }
  if (flags.includes("read_only")) {
    return "grey";
  }
  if (flags.some((f) => HEALTH_DOT[f] === "amber")) {
    return "amber";
  }
  return "green";
}
const EDITABLE_TARGET = ".ace_editor, input, textarea, select, [contenteditable]";
class TopBar extends Component {
  // `template`/`props` are both declared on Owl's own `Component` base
  // class, so `noImplicitOverride` requires `override` here; `components`
  // is not a `Component` class-body member (only of the separate
  // `StaticComponentProperties`/`ComponentConstructor` helper types), so
  // it takes no `override` (TYPING.md's own "Known traps").
  static template = "app_builder_view.TopBar";
  static components = { Dropdown, DropdownItem };
  static props = {
    shell: Object,
    onClose: Function
  };
  setup() {
    this.shell = useState(this.props.shell);
    this.dialog = useService("dialog");
    this.orm = useService("orm");
    this.state = useState({ modelSearch: "", modelMatches: [], picker: null });
    const guarded = (run) => (ev) => {
      const target = ev.target instanceof Element ? ev.target : null;
      if (target && target.closest(EDITABLE_TARGET)) {
        return;
      }
      run();
    };
    useHotkey(
      "control+z",
      guarded(() => this.onUndo())
    );
    useHotkey(
      "control+shift+z",
      guarded(() => this.onRedo())
    );
    useHotkey(
      "control+y",
      guarded(() => this.onRedo())
    );
  }
  // -- the package ---------------------------------------------------------
  get packages() {
    return this.shell.packages.map((info) => ({
      ...info,
      dot: healthDot(info),
      active: info.id === this.shell.packageId
    }));
  }
  get packageLabel() {
    const info = this.shell.package;
    return String(info ? info.name : _t("No package"));
  }
  get packageDot() {
    return this.shell.package ? healthDot(this.shell.package) : "grey";
  }
  /** A Python-owned model is edited in the package that defines it. */
  get packagePinned() {
    return Boolean(this.shell.learned.python_owner_id);
  }
  get packagePinnedReason() {
    return String(
      _t(
        "%s is defined by %s, so its fields can only change there. Pick another model to switch.",
        this.shell.modelLabel || this.shell.modelName,
        this.packageLabel
      )
    );
  }
  onPackage(info) {
    if (!info.active && !this.packagePinned) {
      void this.shell.setPackage(info.id);
    }
  }
  onNewPackage() {
    void this.shell.openPane("create_package");
  }
  // -- the model -----------------------------------------------------------
  get modelLabel() {
    return this.shell.modelLabel || this.shell.modelName || "";
  }
  /** The picker's lists, read when it opens. */
  async loadPicker() {
    this.state.picker = await this.orm.call(
      "studio.workspace",
      "models_for_picker",
      [this.shell.packageId || false]
    );
  }
  async onModelSearch(ev) {
    const term = (ev.target.value || "").trim();
    this.state.modelSearch = term;
    if (term.length < 2) {
      this.state.modelMatches = [];
      return;
    }
    const rows = await this.orm.searchRead(
      "ir.model",
      ["|", ["name", "ilike", term], ["model", "ilike", term], ["transient", "=", false]],
      ["model", "name"],
      { limit: 12 }
    );
    if (this.state.modelSearch === term) {
      this.state.modelMatches = rows.map((r) => ({ model: r.model, display_name: r.name }));
    }
  }
  async onModel(entry) {
    if (entry.model !== this.shell.modelName) {
      await this.shell.setModel(entry.model);
    }
    if (this.shell.pane === "home") {
      await this.shell.openView({ model: entry.model });
    }
  }
  onBuildApp() {
    void this.shell.openPane("build_app");
  }
  onAdoptModel() {
    void this.shell.openPane("adopt_model");
  }
  get canBuild() {
    return this.shell.packageWritable;
  }
  // -- the panes -----------------------------------------------------------
  get tabs() {
    return paneTabs(this.shell.paneContext).map((tab) => ({
      ...tab,
      active: tab.key === this.shell.pane
    }));
  }
  openTab(tab) {
    if (!tab.available || tab.active) {
      return;
    }
    void this.shell.openPane(tab.key);
  }
  get onViews() {
    return this.shell.pane === "views";
  }
  /**
   * The Views pane's own model, when it is on. `shell.activeModel` is
   * typed to the generic `PaneModel` contract every pane satisfies
   * (`shell_model.ts`); the real object it holds whenever
   * `pane === "views"` is always a `ConsoleModel` (`views_pane.js`'s own
   * registration is the one thing that ever puts something there under
   * that key) -- the identical downcast `apply_dialog.ts`'s own `views`
   * getter already makes for this same field.
   */
  get viewsModel() {
    return this.onViews ? this.shell.activeModel : null;
  }
  get viewTypeLabel() {
    const model = this.viewsModel;
    const type = model && model.viewType || this.shell.view.view_type || "";
    const known = (model && model.addable || []).find((entry) => entry.type === type);
    return String(known && known.label || VIEW_TYPE_LABELS[type] || type);
  }
  /** The model's views, then the types the builder could still add. */
  get switcher() {
    const model = this.viewsModel;
    if (!model || !model.context) {
      return [];
    }
    const context = model.context;
    const current = model.viewId;
    const addable = model.addable || [];
    const iconOf = (type) => {
      const entry = addable.find((e) => e.type === type);
      return entry && entry.icon || VIEW_ICONS[type] || "fa fa-square-o";
    };
    const existing = (context.views || []).map((view) => ({
      key: `view-${view.view_id}`,
      type: view.type,
      label: view.name,
      icon: iconOf(view.type),
      active: view.view_id === current,
      view
    }));
    const present = new Set(existing.map((entry) => entry.type));
    const creatable = addable.filter((entry) => entry.enabled && !present.has(entry.type)).map((entry) => ({
      key: `add-${entry.type}`,
      type: entry.type,
      label: String(_t("Add a %s view", entry.label || entry.type)),
      icon: iconOf(entry.type),
      add: entry
    }));
    return [...existing, ...creatable];
  }
  onSwitch(entry) {
    const model = this.viewsModel;
    if (entry.view) {
      if (!entry.active) {
        void this.shell.openView({
          view_id: entry.view.view_id,
          view_type: entry.view.type,
          res_id: this.shell.view.res_id
        });
      }
    } else if (entry.add && model) {
      void model.addView(entry.add);
    }
  }
  // -- undo / redo ----------------------------------------------------------
  /**
   * `StudioShell.history` is `unknown` (any pane model may or may not
   * have one); the only real shape a pane ever puts there is
   * `console_model.ts`'s own `{undo, redo}` getter (`HistoryEntry[]`
   * each) -- `record_pane_model.ts`'s own `history` getter returns
   * `null` instead of a differently-shaped object, never something this
   * downcast would misread. Same tracing-a-real-shape-through-`unknown`
   * reasoning as `status`'s own `drag`, below.
   */
  get history() {
    return this.shell.history;
  }
  get undoEntry() {
    const history = this.history;
    return history && history.undo[0] || null;
  }
  get redoEntry() {
    const history = this.history;
    return history && history.redo[0] || null;
  }
  get undoTooltip() {
    const entry = this.undoEntry;
    return String(
      entry ? _t("Undo: %(summary)s · by %(author)s", {
        summary: entry.summary,
        author: entry.author
      }) : _t("Nothing to undo")
    );
  }
  get redoTooltip() {
    const entry = this.redoEntry;
    return String(
      entry ? _t("Redo: %(summary)s · by %(author)s", {
        summary: entry.summary,
        author: entry.author
      }) : _t("Nothing to redo")
    );
  }
  get busy() {
    return this.shell.activity.busy;
  }
  onUndo() {
    const model = this.shell.activeModel;
    if (this.undoEntry && !this.busy && model && model.undo) {
      void model.undo();
    }
  }
  onRedo() {
    const model = this.shell.activeModel;
    if (this.redoEntry && !this.busy && model && model.redo) {
      void model.redo();
    }
  }
  // -- the draft: Apply and Discard ------------------------------------------
  get pendingCount() {
    return this.shell.pendingCount;
  }
  get applying() {
    return this.shell.draft.applying;
  }
  /** Why Apply is greyed out, for its tooltip; `""` when it is not. */
  get applyTooltip() {
    return this.shell.draft.applyBlocker;
  }
  get applyLabel() {
    return this.shell.draft.reloadMode === "manual" ? String(_t("Write & restart…")) : String(_t("Apply"));
  }
  openApply() {
    if (!this.pendingCount) {
      return;
    }
    this.dialog.add(ApplyDialog, { shell: this.props.shell, close: () => {
    } });
  }
  onDiscard() {
    if (!this.pendingCount || this.busy) {
      return;
    }
    this.dialog.add(ConfirmationDialog, {
      title: _t("Discard pending changes"),
      body: _t(
        "Throw away the %s staged change(s)? Nothing has been applied, so nothing else is lost.",
        this.pendingCount
      ),
      confirmLabel: _t("Discard"),
      confirm: () => {
        void this.shell.discard();
      },
      cancel: () => {
      }
    });
  }
  // -- the status pill ------------------------------------------------------
  get status() {
    const activity = this.shell.activity;
    const drag = activity.drag;
    if (drag) {
      const label = drag.caption ? _t("%(what)s → %(where)s", { what: drag.label, where: drag.caption }) : _t("Dragging %s", drag.label);
      return {
        cls: "dragging",
        label: String(label),
        tooltip: String(_t("Press any key to cancel"))
      };
    }
    if (activity.applying) {
      return { cls: "saving", label: String(_t("Applying…")), tooltip: "" };
    }
    if (activity.status === "saving") {
      return { cls: "saving", label: String(_t("Saving…")), tooltip: "" };
    }
    if (activity.status === "error") {
      return { cls: "error", label: String(_t("Not saved")), tooltip: activity.error };
    }
    if (this.pendingCount) {
      return {
        cls: "pending",
        label: String(_t("%s pending · %s", this.pendingCount, this.applyLabel)),
        tooltip: String(
          this.applyTooltip || _t("Staged on this model's draft; click to apply.")
        )
      };
    }
    if (this.shell.restartRequired) {
      return {
        cls: "pending",
        label: String(_t("Restart needed")),
        tooltip: String(
          _t("Something was written to disk that only a restart of the server can load.")
        )
      };
    }
    if (this.shell.package && !this.shell.packageWritable) {
      return { cls: "readonly", label: String(_t("Read-only")), tooltip: "" };
    }
    return { cls: "saved", label: String(_t("Saved")), tooltip: "" };
  }
  /** The pill is the way to Apply when something is pending. */
  onStatusClick() {
    if (this.status.cls === "pending" && this.pendingCount) {
      this.openApply();
    } else if (this.status.cls === "pending") {
      void this.shell.openPane("changes");
    }
  }
  // -- the changes badge ----------------------------------------------------
  get changesCount() {
    return this.shell.changesCount;
  }
  openChanges() {
    void this.shell.openPane("changes");
  }
}
const VIEW_TYPE_LABELS = {
  list: _t("List"),
  form: _t("Form"),
  kanban: _t("Kanban"),
  calendar: _t("Calendar"),
  pivot: _t("Pivot"),
  graph: _t("Graph"),
  search: _t("Search"),
  qweb: _t("Report"),
  activity: _t("Activity")
};
export {
  TopBar,
  healthDot
};
