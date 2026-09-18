import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { FormViewDialog as FormViewDialogImpl } from "@web/views/view_dialogs/form_view_dialog";
import * as compat from "../compat";
import { ConfirmationDialog, useService } from "../odoo";
import { setPaneResolver } from "../shell/pane_registry";
import { RecordPaneModel } from "./record_pane_model";
import { RowEditor } from "./row_editor";
const FormViewDialog = FormViewDialogImpl;
class RecordPane extends Component {
  static template = "app_builder_view.RecordPane";
  static components = { RowEditor };
  static props = { shell: Object, model: { type: Object, optional: true } };
  // Assigned in `setup()`, which Owl calls synchronously right after
  // construction and before the first render -- always set by the time
  // any getter or template read runs (TYPING.md's own "Known traps").
  shell;
  model;
  dialog;
  state;
  setup() {
    this.shell = useState(this.props.shell);
    this.model = useState(this.props.model);
    this.dialog = useService("dialog");
    this.state = useState({
      gate: { field: "", from: [], to: [], cancel: "" }
    });
  }
  get label() {
    return this.model.entry.label || _t("Records");
  }
  get modelLabel() {
    return this.shell.modelLabel || this.shell.modelName;
  }
  get rows() {
    return this.model.visibleRows;
  }
  get empty() {
    return !this.model.loading && !this.model.rows.length;
  }
  get templates() {
    return this.model.templates;
  }
  get canCreate() {
    const scoped = this.model.entry.scope === "package" || Boolean(this.shell.modelName);
    return this.shell.packageWritable && scoped && !this.gateClosed;
  }
  // -- the gate: a surface whose records need the model prepared first -----------
  /** `{on, title, help, consequence, state_fields, call}` or null. */
  get gate() {
    return this.model.extra["gate"] || null;
  }
  get gateClosed() {
    return Boolean(this.gate && !this.gate.on);
  }
  get gateField() {
    const gate = this.gate;
    if (!gate) {
      return null;
    }
    const fields = gate.state_fields || [];
    return fields.find((f) => f.name === this.state.gate.field) || fields[0] || null;
  }
  /** The values the chosen state field has, for the from/to pickers. */
  get gateValues() {
    const field = this.gateField;
    return field ? field.values : [];
  }
  onGateField(ev) {
    const target = ev.target;
    this.state.gate.field = target.value;
    this.state.gate.from = [];
    this.state.gate.to = [];
    this.state.gate.cancel = "";
  }
  onGateStates(key, ev) {
    const target = ev.target;
    this.state.gate[key] = [...target.selectedOptions].map((o) => o.value);
  }
  /** What the gate will say, before it is written. */
  get gateSentence() {
    const field = this.gateField;
    const { from, to } = this.state.gate;
    if (!field || !to.length) {
      return _t("Say which state needs approving into.");
    }
    const label = (value) => {
      const found = field.values.find((v) => v.value === value);
      return found ? found.label : value;
    };
    return _t(
      "Approval is asked for when %s goes from %s to %s.",
      field.string,
      from.length ? from.map(label).join(", ") : _t("any state"),
      to.map(label).join(", ")
    );
  }
  get gateReady() {
    return Boolean(this.gateField && this.state.gate.to.length && this.shell.packageWritable);
  }
  async onEnableGate() {
    const gate = this.gate;
    const field = this.gateField;
    if (!gate || !field || !this.gateReady) {
      return;
    }
    const { from, to, cancel } = this.state.gate;
    const result = await this.model.call(gate.call, [
      this.shell.packageId,
      this.shell.modelName,
      field.name,
      from.length ? from : false,
      to,
      cancel || false
    ]);
    if (result !== void 0) {
      compat.clearViewCaches(this.env);
      this.shell.refreshChanges();
    }
  }
  /** The empty state's words: the pane's own, else the plain ones. */
  get emptyState() {
    const empty = this.model.entry.empty || {};
    return {
      title: empty.title || _t("%s of %s", this.label, this.modelLabel),
      help: empty.help || _t("Nothing here yet.")
    };
  }
  /** Indentation for a row that came back with a depth (a tree). `depth`
   * is set only by the menu surface's own `rows()` override
   * (`app_builder_ui/models/studio_menu_surface.py`'s own `row["depth"] =
   * depth`) -- optional on `RecordRowJSON` since no other surface sends
   * it, but this generic component is the one real reader that needs it
   * regardless of which surface is in play. */
  rowStyle(row) {
    const depth = row.depth;
    return depth ? `padding-left: ${8 + depth * 18}px` : "";
  }
  /** What a card offers on hover: the pane's own actions, then the surface's. */
  actionsFor(row) {
    const actions = [];
    const rowActions = this.model.entry.rowActions || [];
    for (const action of rowActions) {
      if (!action.when || action.when(row)) {
        actions.push({ ...action, run: () => action.run(this.shell, row, this.model) });
      }
    }
    if (row.editable) {
      actions.push({
        key: "remove",
        label: _t("Remove"),
        icon: "fa fa-trash-o",
        danger: true,
        run: () => this.onRemove(row)
      });
    } else if (row.in_source && this.shell.packageWritable) {
      actions.push({
        key: "duplicate",
        label: _t("Duplicate into %s", this.shell.package ? this.shell.package.name : ""),
        icon: "fa fa-clone",
        run: () => {
          void this.model.duplicate(row.id);
        }
      });
    }
    return actions;
  }
  onSelect(row) {
    if (this.model.selectedId !== row.id) {
      void this.model.select(row.id);
    }
  }
  onRemove(row) {
    this.dialog.add(ConfirmationDialog, {
      title: _t("Remove"),
      body: _t("Remove %s? It is taken out of the package's files as well.", row.title),
      confirmLabel: _t("Remove"),
      confirm: () => {
        void this.model.remove(row.id, true);
      },
      cancel: () => {
      }
    });
  }
  // -- the inline New form ------------------------------------------------------
  get creating() {
    return this.model.creating;
  }
  /** The rows the inline form asks for, in catalogue order. */
  get createRows() {
    const creating = this.creating;
    if (!creating) {
      return [];
    }
    const byName = this.model.rowsByName;
    const names = [...creating.needs || []];
    for (const name of this.model.requiredRowNames()) {
      if (!names.includes(name)) {
        names.push(name);
      }
    }
    return names.map((name) => byName[name]).filter((row) => Boolean(row));
  }
  onCreateValue(row, value) {
    this.model.creating.values[row.name] = value;
  }
  async onCreate() {
    await this.model.create();
  }
  get rowContext() {
    return {
      resModel: this.shell.modelName,
      // `extra.groups` has never been a key any real `catalogue()`
      // implementation sets -- grepped every one in the tree
      // (`studio_record_surface.py`'s base and
      // `studio_approval_surface.py`'s gate override, the only two
      // that exist) and neither returns a top-level `"groups"` key.
      // Always `[]`, the same "typed to what it actually always
      // evaluates to" treatment cluster 1's `row.placeholder` and
      // `row_editor.ts`'s own `row.follow` already got.
      groups: this.model.extra["groups"] || []
    };
  }
}
class RecordSidebar extends Component {
  static template = "app_builder_view.RecordSidebar";
  static components = { RowEditor };
  static props = { shell: Object, model: { type: Object, optional: true } };
  shell;
  model;
  dialog;
  state;
  setup() {
    this.shell = useState(this.props.shell);
    this.model = useState(this.props.model);
    this.dialog = useService("dialog");
    this.state = useState({ openChild: false });
  }
  get record() {
    return this.model.record;
  }
  get row() {
    return this.record ? this.record.row : null;
  }
  get editable() {
    return Boolean(this.row && this.row.editable);
  }
  /** The sections that apply to the record's current values, with their rows. */
  get sections() {
    const record = this.record;
    if (!record) {
      return [];
    }
    return (record.sections || []).filter((section) => this.model.visible(section.visible_when, record.values)).map((section) => ({
      ...section,
      rows: section.rows.filter(
        (row) => this.model.visible(row.visible_when, record.values)
      )
    })).filter((section) => section.rows.length);
  }
  get actions() {
    return this.record && this.record.actions || [];
  }
  get notes() {
    return this.record && this.record.notes || [];
  }
  /** `{valid, count, total}` or `{valid: false, reason}` when the surface counts a condition. */
  get matches() {
    return this.record && this.record["matches"] || null;
  }
  get rowContext() {
    return {
      resModel: this.shell.modelName,
      // See `RecordPane.rowContext`'s own comment: always `[]`.
      groups: this.model.extra["groups"] || []
    };
  }
  onChange(row, value) {
    void this.model.write({ [row.name]: value });
  }
  // -- children -----------------------------------------------------------------
  get children() {
    return this.model.children;
  }
  /** A child's sections that apply to its values, with their rows. */
  childSections(child) {
    return (child.sections || []).filter((section) => this.model.visible(section.visible_when, child.values)).map((section) => ({
      ...section,
      rows: section.rows.filter(
        (row) => this.model.visible(row.visible_when, child.values)
      )
    })).filter((section) => section.rows.length);
  }
  /** The kinds a child can be added as, as objects: a pair is no key for a loop. */
  get childKinds() {
    const kinds = this.children && this.children.kinds || [];
    return kinds.map(([value, label]) => ({ value, label }));
  }
  childKindLabel(child) {
    const children = this.children;
    const value = child.values[children.kind_field];
    const kind = children.kinds.find((k) => k[0] === value);
    return kind ? kind[1] : value;
  }
  isOpen(child) {
    return this.state.openChild === child.row.id;
  }
  toggleChild(child) {
    this.state.openChild = this.isOpen(child) ? false : child.row.id;
  }
  onChildChange(child, row, value) {
    void this.model.writeChild(child.row.id, { [row.name]: value });
  }
  async onAddChild(ev) {
    const target = ev.target;
    const kind = target.value;
    target.value = "";
    if (!kind) {
      return;
    }
    const added = await this.model.addChild(kind);
    if (added && added.row) {
      this.state.openChild = added.row.id;
    }
  }
  /** Up: before the previous one. Down: before the one after the next, or last. */
  onMoveChild(child, direction) {
    const children = this.children;
    const items = children.items;
    const index = items.findIndex((item) => item.row.id === child.row.id);
    const target = direction < 0 ? items[index - 1] : items[index + 2];
    if (direction < 0 && index === 0) {
      return;
    }
    if (direction > 0 && index >= items.length - 1) {
      return;
    }
    void this.model.moveChild(child.row.id, target ? target.row.id : false);
  }
  onRemoveChild(child) {
    const children = this.children;
    this.dialog.add(ConfirmationDialog, {
      title: _t("Remove"),
      body: _t("Remove this %s? The rest stay as they are.", children.one),
      confirmLabel: _t("Remove"),
      confirm: () => {
        void this.model.removeChild(child.row.id);
      },
      cancel: () => {
      }
    });
  }
  onChildAction(child, action) {
    if (!action.enabled) {
      return;
    }
    void this.model.runChild(child.row.id, action.key);
  }
  onAction(action) {
    if (!action.enabled) {
      return;
    }
    void this.model.runAction(action.key);
  }
  /** Odoo's own form on the record, inside the console, capturing on save. */
  onAdvanced() {
    const record = this.record;
    const advanced = record.advanced;
    this.dialog.add(FormViewDialog, {
      resModel: advanced.res_model,
      resId: advanced.res_id,
      context: advanced.context || {},
      title: record.row.title,
      onRecordSaved: async () => {
        await this.model.loadRows();
        await this.model.describe();
        this.shell.refreshChanges();
      }
    });
  }
  onRemove() {
    const row = this.row;
    this.dialog.add(ConfirmationDialog, {
      title: _t("Remove"),
      body: _t("Remove %s? It is taken out of the package's files as well.", row.title),
      confirmLabel: _t("Remove"),
      confirm: () => {
        void this.model.remove(row.id, true);
      },
      cancel: () => {
      }
    });
  }
  onDuplicate() {
    const row = this.row;
    void this.model.duplicate(row.id);
  }
}
setPaneResolver("record", (entry) => ({
  Component: RecordPane,
  sidebar: RecordSidebar,
  // `entry` is `PaneEntry` here (`PaneResolver`'s own parameter type,
  // `shell/pane_registry.ts`); `resolvePane` only ever calls the
  // "record" resolver from its own `if (entry.surface)` branch, so
  // `entry.surface` is always set by the time this runs -- not an
  // invariant `tsc` can see across that module boundary, hence the cast
  // rather than a redundant guard. Through `unknown` rather than a
  // single `as`: `PaneEntry.surface` is optional and `RecordPaneEntry`'s
  // own index signature answers `unknown` rather than `string` for an
  // unnamed key, so neither type is assignable to the other and a
  // direct `entry as RecordPaneEntry` is refused ("neither type
  // sufficiently overlaps with the other") -- the same fix this
  // migration already uses for an unrelated pair of unrelated-looking
  // interfaces (`identity.test.ts`'s own finding on this exact
  // message). `shell` is cast with a single `as` since its own
  // contextual type is bare `unknown` (`PaneRegistration.makeModel`'s
  // signature), which any single `as` accepts -- the same cast
  // `flow.ts`'s identical "flow" resolver already does.
  makeModel: (shell) => new RecordPaneModel(shell, entry)
}));
export {
  RecordPane,
  RecordSidebar
};
