import { Component, onWillDestroy, useEffect, useState } from "@odoo/owl";
import { _t } from "../l10n";
import { ConfirmationDialog, useService } from "../odoo";
import { optionsFor, visibleRows, writeValue } from "../options";
import { iconForType } from "../pending_widget";
import { useFieldEditor } from "./field_editor_fallback";
import { removeWithConfirm } from "./remove_flow";
const DEFINITION_ROWS = [
  { name: "field_description", label: _t("Label"), type: "text" },
  { name: "help", label: _t("Help"), type: "text" },
  { name: "required", label: _t("Required"), type: "toggle" },
  { name: "readonly", label: _t("Read-only"), type: "toggle" },
  { name: "index", label: _t("Indexed"), type: "toggle" },
  { name: "translate", label: _t("Translatable"), type: "toggle" },
  { name: "selection", label: _t("Values"), type: "selection" }
];
function optionsContextOf(context) {
  if (!context) {
    return {};
  }
  return {
    catalogue: context.catalogue,
    fields: context.fields,
    options: context.options
  };
}
class PropertiesTab extends Component {
  static template = "app_builder_view.PropertiesTab";
  static props = { model: Object };
  model;
  dialog;
  editor;
  state;
  setup() {
    this.model = useState(this.props.model);
    this.dialog = useService("dialog");
    this.editor = useFieldEditor();
    this.state = useState({
      target: null,
      loading: false,
      selectionDraft: null
    });
    let alive = true;
    onWillDestroy(() => {
      alive = false;
    });
    useEffect(
      (token, version) => {
        this.state.target = null;
        this.state.selectionDraft = null;
        if (!token || !version || this.isPending) {
          return;
        }
        this.state.loading = true;
        void this.model.describe(token).then((target) => {
          if (!alive || !this.model.selection || this.model.selection.token !== token) {
            return;
          }
          this.state.target = target;
          this.state.loading = false;
        });
      },
      () => [this.model.selection && this.model.selection.token, this.model.archVersion]
    );
  }
  get node() {
    return this.model.selectedNode;
  }
  get token() {
    return this.model.selection ? this.model.selection.token : null;
  }
  /** The selected node's ancestors, outermost first, as clickable crumbs. */
  get crumbs() {
    const nodes = this.model.nodes;
    const out = [];
    const startNode = this.node;
    let token = startNode ? startNode.parent : null;
    while (token) {
      const current = nodes[token];
      if (!current) {
        break;
      }
      out.unshift({ token, label: this.model.tagFor(token) });
      token = current.parent;
    }
    return out;
  }
  get panels() {
    const target = this.state.target;
    if (!target || !target.found) {
      return [];
    }
    const context = optionsContextOf(this.model.context);
    return optionsFor(context, target).map((group) => ({
      id: group.id,
      title: group.title,
      rows: visibleRows(group, target, context)
    }));
  }
  get groupChoices() {
    const context = this.model.context;
    return context && context.groups || [];
  }
  get canRemove() {
    return Boolean(this.node && this.node.removable && this.model.packageId);
  }
  // -- the definition -----------------------------------------------------
  get definition() {
    return this.state.target && this.state.target.definition || null;
  }
  get isManual() {
    return Boolean(this.definition && this.definition.origin === "manual");
  }
  /**
   * Whether the Label row above writes the model's label, not the
   * view's: for a manual field, unless this view already overrides the
   * label -- then the override is what is on screen, and the row edits
   * that, as it says.
   */
  labelWritesDefinition(row) {
    if (row.name !== "string" || row.target === "option" || !this.isManual) {
      return false;
    }
    const attrs = this.state.target?.attrs ?? {};
    return !attrs["string"];
  }
  /**
   * What the Label row writes, when that is not the obvious thing. A
   * manual field's row renames the field itself; a field this package
   * defines in Python has a definition of its own below, and the row
   * dresses this view only -- said here, or the two labels look like
   * one that did not take.
   */
  rowHint(row) {
    if (row.name !== "string" || row.target === "option") {
      return "";
    }
    if (this.labelWritesDefinition(row)) {
      return _t("Renames the field itself, on every view.");
    }
    if (this.isOwnedPython) {
      return _t("On this view only. Edit the definition below to rename the field itself.");
    }
    return "";
  }
  // -- the label ------------------------------------------------------------
  //
  // A form draws a field's label only in a group. Anywhere else -- on
  // the sheet, in a tab, in columns -- the field renders bare, and a
  // Label typed above changes the tag on the canvas and nothing on the
  // screen. The table says where a field's label comes from (`label`),
  // and the switch here turns it on the way core does: `<label for>`
  // before the field, or `nolabel` off again in a group.
  /** The label provenance of the selected field, or `null` off a form field. */
  get labelSwitch() {
    const node = this.node;
    return node && node.kind === "field" && node.label ? node.label : null;
  }
  get labelNote() {
    const label = this.labelSwitch;
    if (!label) {
      return "";
    }
    if (label.shown) {
      return label.by === "label" ? _t("Shown by a label of its own, just before it.") : "";
    }
    return label.in_group ? _t("Not shown: the label is switched off.") : _t("Not shown here: outside a group a field has no label unless it is given one.");
  }
  async onToggleLabel(ev) {
    const label = this.labelSwitch;
    const token = this.token;
    if (!label || !token) {
      return;
    }
    await this.model.setLabelShown(token, ev.target.checked);
  }
  /** The editable rows of a manual field's definition, with their values. */
  get definitionRows() {
    const definition = this.definition;
    if (!definition || !this.isManual) {
      return [];
    }
    const editable = definition.editable;
    const values = definition.values;
    const attrs = this.state.target?.attrs ?? {};
    const rows = DEFINITION_ROWS.filter(
      (row) => editable.includes(row.name) && (row.name !== "field_description" || attrs["string"])
    );
    return rows.map((row) => ({
      ...row,
      key: `def:${row.name}`,
      value: row.type === "toggle" ? Boolean(values[row.name]) : values[row.name] || ""
    }));
  }
  /** The read-only facts of any field's definition. */
  get facts() {
    const definition = this.definition;
    if (!definition) {
      return [];
    }
    const values = definition.values;
    const out = [
      { label: _t("Technical name"), value: this.node && this.node.name },
      { label: _t("Type"), value: values.ttype }
    ];
    if (values.relation) {
      out.push({ label: _t("Relation"), value: values.relation });
    }
    if (!this.isManual) {
      out.push(
        { label: _t("Label"), value: values.field_description },
        { label: _t("Required"), value: values.required ? _t("Yes") : _t("No") },
        { label: _t("Read-only"), value: values.readonly ? _t("Yes") : _t("No") }
      );
      if (values.help) {
        out.push({ label: _t("Help"), value: values.help });
      }
    }
    out.push({
      label: _t("Defined"),
      value: definition.origin === "manual" ? _t("in this database") : _t("in Python")
    });
    return out;
  }
  /** The selection values being edited, a copy until they are sent. */
  get selectionRows() {
    if (this.state.selectionDraft) {
      return this.state.selectionDraft;
    }
    return (this.definition?.values.selection || []).map((row) => ({ ...row }));
  }
  editSelectionRow(index, key, value) {
    const rows = this.selectionRows.map((row) => ({ ...row }));
    rows[index] = { ...rows[index], [key]: value };
    const updatedRow = rows[index];
    if (key === "label" && !updatedRow.value) {
      updatedRow.value = (value || "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
    }
    this.state.selectionDraft = rows;
  }
  addSelectionRow() {
    const rows = this.selectionRows.map((row) => ({ ...row }));
    rows.push({ value: "", label: "", sequence: (rows.length + 1) * 10 });
    this.state.selectionDraft = rows;
  }
  removeSelectionRow(index) {
    this.state.selectionDraft = this.selectionRows.filter((_row, i) => i !== index);
  }
  get selectionDirty() {
    return Boolean(this.state.selectionDraft);
  }
  async saveSelection() {
    const rows = this.selectionRows.filter((row) => row.value).map((row, index) => ({
      value: row.value,
      label: row.label || row.value,
      sequence: row.sequence || (index + 1) * 10
    }));
    if (!rows.length) {
      this.model.notification.add(String(_t("A selection needs at least one value.")), {
        type: "warning"
      });
      return;
    }
    await this.writeDefinition({ selection: rows });
  }
  /** One write to `ir.model.fields`, and the panel shows what it now says. */
  async writeDefinition(values) {
    if (!this.token || !this.state.target) {
      return;
    }
    const token = this.token;
    const definition = await this.model.updateManualField(token, values);
    const target = this.state.target;
    if (definition === void 0 || !target || this.token !== token) {
      return;
    }
    this.state.selectionDraft = null;
    this.state.target = {
      ...target,
      definition,
      field: target.field ? {
        ...target.field,
        // `definition.values` is always present
        // (`FieldDefinition.values` is required, not
        // optional) -- the original's own `(definition.values
        // || {})` fallback was always dead.
        string: definition.values.field_description
      } : target.field
    };
  }
  onDefinitionToggle(row, ev) {
    return this.writeDefinition({ [row.name]: ev.target.checked });
  }
  onDefinitionInput(row, ev) {
    return this.writeDefinition({
      [row.name]: ev.target.value
    });
  }
  // -- fields the package defines in Python ---------------------------------
  //
  // Their definition is a class attribute: editing it is staged on the
  // model's draft, exactly like a pending field's, and lands on Apply.
  // Three things the panel says about one: what the draft already holds
  // for it, how to edit it, and that a removal drops a column.
  /** A field node of a model this package defines in Python. */
  get isOwnedPython() {
    return Boolean(
      this.model.pythonOwned && this.node && this.node.kind === "field" && this.definition && this.definition.origin !== "manual"
    );
  }
  /** The change the draft holds for this field, or `null`. */
  get ownedPendingKind() {
    if (!this.isOwnedPython || !this.node) {
      return null;
    }
    const node = this.node;
    const entry = this.model.modelFields.find((f) => f.name === node.name);
    return entry && entry.pendingKind || null;
  }
  get ownedPendingNote() {
    switch (this.ownedPendingKind) {
      case "changed":
        return _t("Its definition has a staged edit; Apply writes it.");
      case "removed":
        return _t("Staged for removal; Apply drops the column and keeps its data aside.");
      case "added":
        return _t("Staged as a new field; Apply creates it.");
      default:
        return "";
    }
  }
  /** Open the field editor on the class attribute, staged on the draft. */
  async onEditOwned(ev) {
    const node = this.node;
    if (!node || !node.name) {
      return;
    }
    const name = node.name;
    const anchor = ev.currentTarget;
    const draft = await this.model._ensureDraft();
    const staged = draft && this.model.stagedField(name);
    if (!staged) {
      this.model.notification.add(
        String(_t("The class this field belongs to could not be read into a draft.")),
        { type: "warning" }
      );
      return;
    }
    const draftFields = this.model.draft && this.model.draft.fields || [];
    const editorProps = {
      field: { ...staged },
      mode: "staged",
      fieldTypes: this.model.fieldTypes,
      existingNames: draftFields.map((f) => f.name).filter((n) => n !== name),
      // Always a real model here -- editing an owned field's
      // definition only ever happens with a model loaded
      // (`isOwnedPython`) -- matching `resolveRelated`'s own
      // identical `this.modelName as string` cast (`console_model.ts`).
      modelName: this.model.modelName,
      inverseOptions: (comodel) => this.model.inverseOptions(comodel),
      resolveRelated: (path) => this.model.resolveRelated(path),
      onSave: (values) => {
        this.editor.close();
        void this.model.updateStaged(name, values);
      },
      onDelete: () => {
        this.editor.close();
        this.onRemoveOwned();
      }
    };
    this.editor.open(anchor, editorProps);
  }
  /** Stage the removal of a class attribute: a dropped column on Apply. */
  onRemoveOwned() {
    const node = this.node;
    if (!node || !node.name) {
      return;
    }
    const name = node.name;
    const label = this.definition?.values.field_description || name;
    this.dialog.add(ConfirmationDialog, {
      title: _t("Remove field from the model"),
      body: _t(
        "Remove %s from the model? Nothing changes until Apply; then its column is dropped and its data kept aside by a migration. Discard the pending changes to take it back before that.",
        label
      ),
      confirmLabel: _t("Stage the removal"),
      // `ConfirmationDialogProps.confirm` is `() => void`, so the
      // async body that needs `removePending`'s own result (to
      // decide whether to clear the selection) is pulled into its
      // own method instead of an inline `async` arrow -- the same
      // `no-misused-promises` finding `apply_dialog.ts`'s/
      // `view_tab.ts`'s own simpler fire-and-forget callbacks
      // already hit, just with a result to await here.
      confirm: () => {
        void this.finishRemoveOwned(name);
      },
      cancel: () => {
      }
    });
  }
  async finishRemoveOwned(name) {
    const result = await this.model.removePending(name);
    if (result !== void 0) {
      this.model.clearSelection();
    }
  }
  // -- pending fields -----------------------------------------------------
  get isPending() {
    return Boolean(this.node && this.node.kind === "pending");
  }
  /** What the ghost stands for: the node's word, then the draft's. */
  get pendingField() {
    const node = this.node;
    if (!node || !this.isPending) {
      return null;
    }
    const info = node.pending;
    const name = info?.name || node.name;
    const staged = this.model.stagedField(name);
    return {
      name,
      string: staged?.string || info?.string || name,
      ttype: staged?.ttype || info?.ttype || "",
      typeLabel: staged?.type_label || info?.ttype || "",
      resolved: info?.resolved !== false,
      staged
    };
  }
  get pendingIcon() {
    const field = this.pendingField;
    return field ? iconForType(field.ttype, field.ttype) : "";
  }
  /** Open the field editor on the staged definition, beside the button. */
  async onEditPending(ev) {
    const field = this.pendingField;
    if (!field) {
      return;
    }
    let staged = field.staged;
    if (!staged) {
      await this.model.loadDraft();
      staged = this.model.stagedField(field.name);
    }
    if (!staged) {
      this.model.notification.add(
        String(_t("The draft this field is staged on could not be read.")),
        { type: "warning" }
      );
      return;
    }
    const name = field.name;
    const anchor = ev.currentTarget;
    const draftFields = this.model.draft && this.model.draft.fields || [];
    const editorProps = {
      field: { ...staged },
      mode: "staged",
      fieldTypes: this.model.fieldTypes,
      existingNames: draftFields.map((f) => f.name).filter((n) => n !== name),
      modelName: this.model.modelName,
      inverseOptions: (comodel) => this.model.inverseOptions(comodel),
      resolveRelated: (path) => this.model.resolveRelated(path),
      onSave: (values) => {
        this.editor.close();
        void this.model.updateStaged(name, values);
      },
      onDelete: () => {
        this.editor.close();
        this.onRemovePending();
      }
    };
    this.editor.open(anchor, editorProps);
  }
  onRemovePending() {
    const field = this.pendingField;
    if (!field) {
      return;
    }
    this.dialog.add(ConfirmationDialog, {
      title: _t("Remove pending field"),
      body: _t(
        "Remove %s from the draft? It has not been applied, so nothing is lost but its definition.",
        field.string
      ),
      confirmLabel: _t("Remove"),
      confirm: () => {
        void this.finishRemoveOwned(field.name);
      },
      cancel: () => {
      }
    });
  }
  // -- writing ------------------------------------------------------------
  async onRowChange(row, rawValue) {
    const token = this.token;
    const target = this.state.target;
    if (!token || !target) {
      return;
    }
    if (this.labelWritesDefinition(row)) {
      await this.writeDefinition({ field_description: rawValue });
      return;
    }
    await this.model.setAttributes(token, writeValue(row, rawValue, target));
  }
  onToggle(row, ev) {
    return this.onRowChange(row, ev.target.checked);
  }
  onInput(row, ev) {
    return this.onRowChange(row, ev.target.value);
  }
  onMultiSelect(row, ev) {
    return this.onRowChange(
      row,
      [...ev.target.selectedOptions].map((option) => option.value)
    );
  }
  /** The Label row of a manual field shows the model's label, not the view's. */
  rowValue(row) {
    if (this.labelWritesDefinition(row) && !row.value) {
      return this.definition?.values.field_description || "";
    }
    return row.value;
  }
  async onRemove() {
    const token = this.token;
    if (!token) {
      return;
    }
    await removeWithConfirm({ model: this.model, dialog: this.dialog, token });
  }
}
export {
  PropertiesTab
};
