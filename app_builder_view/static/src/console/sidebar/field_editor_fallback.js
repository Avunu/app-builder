import { Component, onMounted, useRef, useState } from "@odoo/owl";
import { _t } from "../l10n";
import { ModelFieldSelector } from "@web/core/model_field_selector/model_field_selector";
import { ModelSelector } from "@web/core/model_selector/model_selector";
import { usePopover } from "@web/core/popover/popover_hook";
import { registry } from "@web/core/registry";
const editorRegistry = registry.category("app_builder.field_editor");
const FIELD_EDITOR_PROPS = {
  field: { type: [Object, { value: null }], optional: true },
  initial: { type: Object, optional: true },
  mode: { type: String, optional: true },
  fieldTypes: Array,
  existingNames: Array,
  modelName: String,
  inverseOptions: Function,
  resolveRelated: Function,
  onSave: Function,
  onDelete: { type: [Function, { value: null }], optional: true },
  close: Function
};
function fieldEditorComponent() {
  const entries = editorRegistry.getEntries();
  return entries.length ? entries[0][1] : FieldEditorFallback;
}
const KEEPS_OPEN = [
  ".o_datetime_picker",
  ".o_model_field_selector_popover",
  ".o-autocomplete--dropdown-menu",
  ".o_domain_selector_dialog",
  ".o_select_menu_menu",
  ".o_popover",
  ".modal",
  ".o_tag_popover"
];
function useFieldEditor() {
  return usePopover(fieldEditorComponent(), {
    popoverClass: "o_studio_field_editor_popover",
    position: "right",
    closeOnClickAway: (target) => !KEEPS_OPEN.some((selector) => target.closest && target.closest(selector))
  });
}
function initialState(props) {
  if (props.field) {
    return { ...props.field };
  }
  const initial = props.initial || {};
  const entry = props.fieldTypes.find((t) => t.value === initial.ttype);
  return {
    ttype: initial.ttype || "char",
    string: initial.string || String(entry ? _t("New %s", entry.label) : _t("New field")),
    selection: []
  };
}
class FieldEditorFallback extends Component {
  static template = "app_builder_view.FieldEditorFallback";
  static components = { ModelSelector, ModelFieldSelector };
  static props = FIELD_EDITOR_PROPS;
  isNew;
  labelRef;
  state;
  setup() {
    this.isNew = !this.props.field;
    this.labelRef = useRef("label");
    this.state = useState({
      ...initialState(this.props),
      error: "",
      inverse: null,
      relatedInfo: null
    });
    onMounted(() => {
      if (this.state.ttype === "one2many" && this.state.comodel) {
        void this.loadInverseOptions(this.state.comodel);
      }
      const input = this.labelRef.el;
      if (input) {
        input.focus();
        if (this.isNew) {
          input.select();
        }
      }
    });
  }
  // -- what the type needs ------------------------------------------------
  get currentType() {
    return this.props.fieldTypes.find((t) => t.value === this.state.ttype) || {};
  }
  /** The picker entries that can be chosen here. */
  get typeChoices() {
    return this.props.fieldTypes.filter(
      (entry) => entry.enabled && (this.props.mode !== "live" || entry.live !== false)
    );
  }
  shows(param) {
    return (this.currentType.params || []).includes(param);
  }
  onTypeChange(value) {
    const entry = this.props.fieldTypes.find((t) => t.value === value);
    if (!entry || !entry.enabled) {
      return;
    }
    this.state.ttype = value;
    for (const param of ["comodel", "inverse_name", "related", "currency_field"]) {
      if (!entry.params.includes(param)) {
        delete this.state[param];
      }
    }
    if (!entry.params.includes("selection")) {
      this.state.selection = [];
    }
  }
  // -- relations ----------------------------------------------------------
  async onComodelSelected(model) {
    this.state.comodel = model.technical;
    if (this.state.ttype === "one2many" || this.state.ttype === "lines") {
      await this.loadInverseOptions(model.technical);
    }
  }
  async loadInverseOptions(comodel) {
    this.state.inverse = await this.props.inverseOptions(comodel);
    const { candidates, can_create: canCreate, suggested } = this.state.inverse;
    if (candidates.length) {
      this.state.create_inverse = false;
      this.state.inverse_name = candidates[0].name;
    } else if (canCreate) {
      this.state.create_inverse = true;
      this.state.inverse_name = suggested;
    }
  }
  get inverse() {
    return this.state.inverse || { candidates: [], can_create: false, suggested: "", reason: "" };
  }
  get needsInverse() {
    return ["one2many", "lines"].includes(this.state.ttype) && Boolean(this.state.comodel);
  }
  onInverseChange(value) {
    if (value === "__new__") {
      this.state.create_inverse = true;
      this.state.inverse_name = this.inverse.suggested;
    } else {
      this.state.create_inverse = false;
      this.state.inverse_name = value;
    }
  }
  // -- related ------------------------------------------------------------
  async onRelatedChange(path) {
    this.state.related = path;
    this.state.relatedInfo = await this.props.resolveRelated(path);
    if (this.state.relatedInfo.ok && this.isNew) {
      this.state.string = this.state.relatedInfo.string;
    }
  }
  // -- selection values ---------------------------------------------------
  get selectionRows() {
    return this.state.selection || [];
  }
  addSelectionRow() {
    this.state.selection = [
      ...this.selectionRows,
      { value: "", label: "", sequence: (this.selectionRows.length + 1) * 10 }
    ];
  }
  updateSelectionRow(index, key, value) {
    const rows = [...this.selectionRows];
    rows[index] = { ...rows[index], [key]: value };
    const updatedRow = rows[index];
    if (key === "label" && !updatedRow.value) {
      updatedRow.value = (value || "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
    }
    this.state.selection = rows;
  }
  removeSelectionRow(index) {
    this.state.selection = this.selectionRows.filter((_row, i) => i !== index);
  }
  // -- commit -------------------------------------------------------------
  validate() {
    if (!(this.state.string || "").trim()) {
      return String(_t("Give the field a label."));
    }
    if (this.shows("comodel") && !this.state.comodel) {
      return String(_t("Choose the model this points at."));
    }
    if (this.needsInverse && !this.state.inverse_name) {
      return String(_t("Choose how %s links back to this model.", this.state.comodel));
    }
    if (this.shows("selection") && !this.selectionRows.some((row) => row.value)) {
      return String(_t("A selection needs at least one value."));
    }
    if (this.shows("related")) {
      if (!this.state.related) {
        return String(_t("Choose the field this one follows."));
      }
      if (this.state.relatedInfo && !this.state.relatedInfo.ok) {
        return this.state.relatedInfo.reason;
      }
    }
    return "";
  }
  onSave() {
    const problem = this.validate();
    if (problem) {
      this.state.error = problem;
      return;
    }
    const { error, inverse, relatedInfo, ...values } = this.state;
    if (relatedInfo && relatedInfo.ok) {
      values.ttype = relatedInfo.ttype;
      values.comodel = relatedInfo.comodel || void 0;
    }
    values.selection = this.selectionRows.filter((row) => row.value);
    if (!values.selection.length) {
      delete values.selection;
    }
    this.props.onSave(values);
  }
  onKeydown(ev) {
    if (ev.key === "Enter" && !ev.shiftKey && ev.target.tagName !== "TEXTAREA") {
      ev.preventDefault();
      this.onSave();
    }
    if (ev.key === "Escape") {
      ev.preventDefault();
      this.props.close();
    }
  }
}
export {
  FIELD_EDITOR_PROPS,
  FieldEditorFallback,
  fieldEditorComponent,
  useFieldEditor
};
