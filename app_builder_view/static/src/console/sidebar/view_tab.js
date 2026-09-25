import { Component, onWillDestroy, onWillStart, useEffect, useState } from "@odoo/owl";
import { _t } from "../l10n";
import { ConfirmationDialog, useService } from "../odoo";
import { optionsFor, visibleRows, writeValue } from "../options";
import { iconForType } from "../pending_widget";
import { useFieldEditor } from "./field_editor_fallback";
class ViewTab extends Component {
  static template = "app_builder_view.ViewTab";
  static props = { model: Object };
  // Every field below is assigned unconditionally in `setup()` --
  // Owl components initialize through that lifecycle hook, not a
  // constructor this class writes its own, so `strictPropertyInitialization`
  // (which only ever looks at a real constructor) cannot see it; the
  // definite-assignment assertion says so instead (TYPING.md's own
  // "Known traps").
  model;
  dialog;
  editor;
  state;
  setup() {
    this.model = useState(this.props.model);
    this.dialog = useService("dialog");
    this.editor = useFieldEditor();
    this.state = useState({ target: null });
    onWillStart(async () => {
      if (this.model.pythonOwned && !this.model.draft) {
        await this.model._ensureDraft();
      }
    });
    let alive = true;
    onWillDestroy(() => {
      alive = false;
    });
    useEffect(
      (root, version) => {
        this.state.target = null;
        if (!root || !version) {
          return;
        }
        void this.model.describe(root).then((target) => {
          if (alive && this.model.archVersion === version) {
            this.state.target = target;
          }
        });
      },
      () => [this.model.root, this.model.archVersion]
    );
  }
  get panels() {
    const target = this.state.target;
    if (!target || !target.found) {
      return [];
    }
    const raw = this.model.context;
    const context = raw ? { catalogue: raw.catalogue, fields: raw.fields, options: raw.options } : {};
    return optionsFor(context, target).map((group) => ({
      id: group.id,
      title: group.title,
      rows: visibleRows(group, target, context)
    }));
  }
  get source() {
    return this.model.canvas ? this.model.canvas.source : null;
  }
  get ownershipNote() {
    if (!this.model.context) {
      return "";
    }
    return this.model.context.owned ? _t("This package owns this view, so changes are written into it directly.") : _t(
      "This view belongs to another module. Changes become a separate inheriting view, so the original keeps working and upgrades cleanly."
    );
  }
  get recentChanges() {
    return this.model.history.undo || [];
  }
  // -- the model ------------------------------------------------------------
  get showsModel() {
    return Boolean(this.model.pythonOwned);
  }
  get modelFields() {
    return this.model.modelFields.map((field) => ({
      ...field,
      icon: iconForType(field.ttype, field.ttype),
      typeLabel: field.type_label || field.ttype || ""
    }));
  }
  pendingBadge(field) {
    switch (field.pendingKind) {
      case "added":
        return _t("new");
      case "changed":
        return _t("edited");
      case "removed":
        return _t("removed");
      default:
        return "";
    }
  }
  editorProps(anchorName, field) {
    const names = this.model.modelFields.map((f) => f.name).filter((n) => n !== anchorName);
    return {
      field: field ? { ...field } : null,
      mode: "staged",
      fieldTypes: this.model.fieldTypes,
      existingNames: names,
      modelName: this.model.modelName,
      inverseOptions: (comodel) => this.model.inverseOptions(comodel),
      resolveRelated: (path) => this.model.resolveRelated(path)
    };
  }
  // Not `async`: nothing in this method's own body is awaited (the
  // `await` lives inside the nested `onSave` callback, its own function
  // scope) -- `async` here would be a no-op wrapping an already-`void`
  // return in a `Promise`, exactly what `require-await` exists to catch.
  onEditModelField(ev, entry) {
    const staged = this.model.stagedField(entry.name);
    if (!staged) {
      return;
    }
    const name = entry.name;
    this.editor.open(ev.currentTarget, {
      ...this.editorProps(name, staged),
      onSave: async (values) => {
        this.editor.close();
        await this.model.updateStaged(name, values);
      },
      onDelete: () => {
        this.editor.close();
        this.onRemoveModelField(entry);
      }
    });
  }
  onRemoveModelField(entry) {
    this.dialog.add(ConfirmationDialog, {
      title: _t("Remove field from the model"),
      body: _t(
        "Remove %s from the model? Nothing changes until Apply; then its column is dropped and its data kept aside by a migration. Discard the pending changes to take it back before that.",
        entry.string || entry.name
      ),
      confirmLabel: _t("Stage the removal"),
      confirm: () => {
        void this.model.removePending(entry.name);
      },
      cancel: () => {
      }
    });
  }
  /** A new field with no place on this canvas: Apply places it. */
  onAddModelField(ev) {
    this.editor.open(ev.currentTarget, {
      ...this.editorProps(null, null),
      initial: { ttype: "char" },
      onSave: async (values) => {
        this.editor.close();
        await this.model.addModelField(values);
      },
      onDelete: null
    });
  }
  async onMoveUp(entry) {
    const names = this.model.modelFields.filter((f) => f.pendingKind !== "removed").map((f) => f.name);
    const index = names.indexOf(entry.name);
    if (index > 0) {
      await this.model.moveField(entry.name, names[index - 1]);
    }
  }
  async onMoveDown(entry) {
    const names = this.model.modelFields.filter((f) => f.pendingKind !== "removed").map((f) => f.name);
    const index = names.indexOf(entry.name);
    if (index >= 0 && index < names.length - 1) {
      await this.model.moveField(entry.name, names[index + 2] || null);
    }
  }
  async onRowChange(row, rawValue) {
    const root = this.model.root;
    const target = this.state.target;
    if (!root || !target) {
      return;
    }
    await this.model.setAttributes(root, writeValue(row, rawValue, target));
  }
  onToggle(row, ev) {
    return this.onRowChange(row, ev.target.checked);
  }
  onInput(row, ev) {
    return this.onRowChange(row, ev.target.value);
  }
}
export {
  ViewTab
};
