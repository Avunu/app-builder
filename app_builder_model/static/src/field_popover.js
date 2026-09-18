import { Component, useState, useRef, onMounted } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { CheckBox } from "@web/core/checkbox/checkbox";
import { ModelSelector } from "@web/core/model_selector/model_selector";
import { ModelFieldSelector } from "@web/core/model_field_selector/model_field_selector";
import { SelectMenu } from "@web/core/select_menu/select_menu";
const ONDELETE_CHOICES = [
  { value: "set null", label: _t("Leave empty") },
  { value: "restrict", label: _t("Prevent deletion") },
  { value: "cascade", label: _t("Delete this record too") }
];
class FieldPopover extends Component {
  static template = "app_builder_model.FieldPopover";
  static components = { CheckBox, ModelSelector, ModelFieldSelector, SelectMenu };
  static props = {
    field: { type: [Object, { value: null }], optional: true },
    fieldTypes: Array,
    existingNames: Array,
    modelName: String,
    onSave: Function,
    onDelete: { type: [Function, { value: null }], optional: true },
    inverseOptions: Function,
    resolveRelated: Function,
    close: Function
  };
  isNew;
  labelRef;
  state;
  setup() {
    const field = this.props.field;
    this.isNew = !field;
    this.labelRef = useRef("label");
    this.state = useState(
      field ? { ...field } : {
        // Created already valid, so the popover opens on something
        // editable rather than on a wall of required inputs.
        name: this.suggestName(String(_t("New field"))),
        ttype: "char",
        string: String(_t("New field"))
      }
    );
    this.state.error = "";
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
  // -- naming -----------------------------------------------------------
  /**
   * The technical name is derived once, from the first label, and then left
   * alone. Renaming a column is a migration, not a typing gesture.
   */
  suggestName(label) {
    const slug = (label || "").toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
    let candidate = slug || "field";
    if (/^[0-9]/.test(candidate)) {
      candidate = `f_${candidate}`;
    }
    let unique = candidate;
    let counter = 2;
    while (this.props.existingNames.includes(unique)) {
      unique = `${candidate}_${counter++}`;
    }
    return unique;
  }
  onLabelInput(ev) {
    this.state.string = ev.target.value;
    if (this.isNew) {
      this.state.name = this.suggestName(this.state.string);
    }
  }
  // -- types ------------------------------------------------------------
  get typeGroups() {
    const groups = {};
    for (const entry of this.props.fieldTypes) {
      (groups[entry.group] ||= []).push(entry);
    }
    return Object.entries(groups).map(([name, choices]) => ({ name, choices }));
  }
  get currentType() {
    return this.props.fieldTypes.find((t) => t.value === this.state.ttype) || {};
  }
  get params() {
    return this.currentType.params || [];
  }
  shows(param) {
    return this.params.includes(param);
  }
  get ondeleteChoices() {
    return ONDELETE_CHOICES;
  }
  // -- relationships ----------------------------------------------------
  /**
   * Odoo needs a many2one on the other side before a related list can exist.
   * Making the user go and build it there first is the gesture every studio
   * gets wrong, so the choice is offered inline: reuse a link that already
   * points back, or have one made in the same Apply.
   */
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
    return this.state.inverse || // The fallback was missing `suggested` (`InverseOptions`,
    // `wire.ts`, requires all four fields) -- the identical gap
    // `field_editor_fallback.ts`'s own `get inverse()` had and
    // fixed the same way (cluster 4 wave 1), unreachable today
    // since the branch that reads `suggested` is gated behind
    // `can_create`, which this same fallback also sets `false`.
    { candidates: [], can_create: false, suggested: "", reason: "" };
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
  async onComodelSelected(model) {
    this.state.comodel = model.technical;
    if (this.state.ttype === "one2many") {
      await this.loadInverseOptions(model.technical);
    }
  }
  // -- related ------------------------------------------------------------
  /**
   * A related field has no type of its own: `partner_id.email` is a char
   * because `email` is. So the chain is what the user picks, and the type
   * comes back from the server -- asking them to state it as well would be
   * asking them to be right about something the model already knows, where
   * being wrong is a registry error at load time rather than a message.
   */
  async onRelatedChange(path) {
    this.state.related = path;
    this.state.relatedInfo = await this.props.resolveRelated(path);
    const relatedInfo = this.state.relatedInfo;
    if (relatedInfo.ok) {
      this.state.error = "";
      if (!this.state.string || this.state.string === String(_t("New field"))) {
        this.state.string = relatedInfo.string;
        this.state.name = this.suggestName(this.state.string);
      }
    }
  }
  get relatedInfo() {
    return this.state.relatedInfo || null;
  }
  // -- computed ---------------------------------------------------------
  get computeOpen() {
    return Boolean(this.state.showCompute || this.state.compute_body);
  }
  toggleCompute() {
    this.state.showCompute = !this.computeOpen;
    if (!this.state.showCompute) {
      this.state.compute_body = "";
      this.state.depends = "";
    }
  }
  // -- placement --------------------------------------------------------
  /**
   * Placement is view intent, not part of the field definition, so it lives
   * beside the spec rather than in it. It is edited here anyway because
   * "where does this show up" is the question people ask *while* adding a
   * field, not on a separate screen afterwards.
   */
  get placement() {
    return this.state.placement || this.currentType.placement || {};
  }
  /**
   * Only ever called with one of the four boolean slots the template's
   * checkboxes cover (`form`/`list`/`search`/`group_by`) -- `widget` is
   * never set through here, only ever copied whole from a field type's
   * own placement (`onTypeChange`). The cast reflects that every real
   * `this.placement` is a full `PlacementJSON` (either a prior full
   * assignment, or a real field type's own catalogue entry) except the
   * defensive `{}` fallback the getter above falls back to when
   * `state.ttype` genuinely names no known type -- a case this method,
   * like that getter, does not newly invent a `widget` for.
   */
  setPlacement(slot, value) {
    this.state.placement = { ...this.placement, [slot]: value };
  }
  get canGroupBy() {
    return ["many2one", "selection", "date", "datetime", "boolean"].includes(this.state.ttype);
  }
  get wantsPage() {
    return ["one2many", "many2many", "html", "text"].includes(this.state.ttype);
  }
  onTypeChange(value) {
    const entry = this.props.fieldTypes.find((t) => t.value === value);
    if (!entry || !entry.enabled) {
      return;
    }
    this.state.ttype = value;
    this.state.placement = { ...entry.placement };
    for (const param of ["comodel", "inverse_name", "selection", "currency_field"]) {
      if (!entry.params.includes(param)) {
        delete this.state[param];
      }
    }
  }
  // -- selection values -------------------------------------------------
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
  // -- commit -----------------------------------------------------------
  validate() {
    if (!this.state.string?.trim()) {
      return String(_t("Give the field a label."));
    }
    if (this.shows("comodel") && !this.state.comodel) {
      return String(_t("Choose the model this points at."));
    }
    if (this.state.ttype === "one2many" && !this.state.inverse_name) {
      return String(
        _t(
          "Choose how %s links back to this model.",
          this.state.comodel || String(_t("the other model"))
        )
      );
    }
    if (["selection", "reference"].includes(this.state.ttype) && !this.selectionRows.filter((r) => r.value).length) {
      return String(_t("A selection needs at least one value."));
    }
    if (this.shows("related")) {
      if (!this.state.related) {
        return String(_t("Choose the field this one follows."));
      }
      const relatedInfo = this.relatedInfo;
      if (relatedInfo && !relatedInfo.ok) {
        return relatedInfo.reason;
      }
    }
    if (this.state.compute_body && !this.state.depends) {
      return String(
        _t("A computed field needs the fields it reads, so Odoo knows when to recompute.")
      );
    }
    return "";
  }
  onSave() {
    const problem = this.validate();
    if (problem) {
      this.state.error = problem;
      return;
    }
    const values = { ...this.state };
    delete values.error;
    delete values.type_label;
    delete values.inverse;
    delete values.showCompute;
    const relatedInfo = this.relatedInfo;
    if (relatedInfo && relatedInfo.ok) {
      values.ttype = relatedInfo.ttype;
      values.comodel = relatedInfo.comodel || void 0;
    }
    delete values.relatedInfo;
    values.placement = { ...this.placement };
    if (values.selection) {
      values.selection = this.selectionRows.filter((r) => r.value);
    }
    this.props.onSave(values);
  }
  onDelete() {
    this.props.onDelete?.();
  }
  onKeydown(ev) {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      this.onSave();
    }
  }
}
export {
  FieldPopover
};
