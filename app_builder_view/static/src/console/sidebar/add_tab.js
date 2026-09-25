import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { _t } from "../l10n";
import { focusLabelRow } from "../drag";
import { useService } from "../odoo";
import { iconForType } from "../pending_widget";
import { useFieldEditor } from "./field_editor_fallback";
const COMPONENTS = [
  { component: "page", label: _t("Tabs"), icon: "fa fa-folder-o", tags: ["form"] },
  { component: "columns", label: _t("Columns"), icon: "fa fa-columns", tags: ["form"] },
  { component: "group", label: _t("Group"), icon: "fa fa-object-group", tags: ["form"] },
  { component: "separator", label: _t("Separator"), icon: "fa fa-minus", tags: ["form"] },
  { component: "button", label: _t("Button"), icon: "fa fa-hand-pointer-o", tags: ["form"] }
];
class AddTab extends Component {
  static template = "app_builder_view.AddTab";
  static props = { model: Object };
  model;
  notification;
  rootRef;
  editor;
  state;
  /** Whether the field editor currently open was opened for a drop
   * (`openEditor`'s own `Boolean(this.model.fieldTarget)`, read there)
   * -- set only inside `openEditor`, never during `setup()` itself, so
   * it is genuinely `undefined` until the first field editor this tab
   * opens. */
  editorForDrop;
  setup() {
    this.model = useState(this.props.model);
    this.notification = useService("notification");
    this.rootRef = useRef("root");
    this.editor = useFieldEditor();
    this.state = useState({
      search: "",
      newButton: null
    });
    useEffect(
      (serial) => {
        const target = this.model.fieldTarget;
        if (serial && target) {
          this.openEditor(this.tileFor(target.ttype), target.ttype, target.label);
        } else if (!target && this.editor.isOpen && this.editorForDrop) {
          this.editor.close();
        }
      },
      () => [this.model.fieldTarget && this.model.fieldTarget.serial]
    );
    useEffect(
      (serial) => {
        const form = this.state.newButton;
        if (serial) {
          this.state.newButton = { string: "", action_id: "", dropped: true };
        } else if (form && form.dropped && !form.sending) {
          this.state.newButton = null;
        }
      },
      () => [this.model.buttonTarget && this.model.buttonTarget.serial]
    );
  }
  // -- what the palette offers ---------------------------------------------
  get components() {
    const type = this.model.viewType;
    return COMPONENTS.filter((entry) => typeof type === "string" && entry.tags.includes(type));
  }
  /**
   * The New Fields tiles. On a Python-owned model every available type
   * is offered, to be staged; elsewhere only what can be made live,
   * and a type that cannot keeps the server's reason as its tooltip.
   */
  get fieldTypes() {
    const staged = this.model.pythonOwned;
    const plan = this.fieldPlan;
    return this.model.fieldTypes.map((entry) => {
      const enabled = Boolean(entry.enabled && (staged || entry.live));
      let tooltip = entry.tooltip || "";
      if (enabled) {
        tooltip = entry.needs_dialog ? String(_t("Opens the field editor first")) : staged ? String(_t("Staged until Apply")) : "";
      } else if (entry.enabled && !staged && plan && !plan.can_create) {
        tooltip = plan.reason || tooltip;
      } else if (entry.enabled && !enabled) {
        tooltip = tooltip || String(_t("Cannot be created live on this model"));
      }
      return {
        ...entry,
        enabled,
        tooltip,
        icon: iconForType(entry.value, entry.ttype)
      };
    });
  }
  get existingFields() {
    const needle = (this.state.search || "").toLowerCase();
    const fields = this.model.palette || [];
    if (!needle) {
      return fields;
    }
    return fields.filter(
      (f) => f.string.toLowerCase().includes(needle) || f.name.toLowerCase().includes(needle)
    );
  }
  /**
   * The fields a kanban declares at its root and shows in no card:
   * loaded for the template, invisible on the board, and not in the
   * existing fields since the arch already names them. Searchable
   * like those, and dropped the same way.
   */
  get declaredFields() {
    if (this.model.viewType !== "kanban") {
      return [];
    }
    const nodes = this.model.nodes;
    const root = this.model.root;
    const shown = /* @__PURE__ */ new Set();
    for (const node of Object.values(nodes)) {
      if (node.kind === "field" && node.dom && node.name) {
        shown.add(node.name);
      }
    }
    const needle = (this.state.search || "").toLowerCase();
    const fields = [];
    for (const node of Object.values(nodes)) {
      if (node.kind !== "field" || node.dom || node.parent !== root || !node.name) {
        continue;
      }
      const name = node.name;
      if (shown.has(name) || fields.some((f) => f.name === name)) {
        continue;
      }
      const info = node.field;
      const field = {
        name,
        string: info?.string || node.string || name,
        type: info?.type || "char"
      };
      if (!needle || field.string.toLowerCase().includes(needle) || field.name.toLowerCase().includes(needle)) {
        fields.push(field);
      }
    }
    return fields;
  }
  iconFor(field) {
    return iconForType(field.type, field.type);
  }
  /** What the current selection means for something added now. */
  get anchorNote() {
    const token = this.model.anchorToken;
    const node = token ? this.model.nodes[token] : void 0;
    if (!token || !node || node.kind === "root") {
      if (this.model.viewType === "kanban") {
        return String(_t("Select a place in a card first."));
      }
      return String(_t("Added at the end of the view."));
    }
    const what = this.model.tagFor(token);
    return node.container ? String(_t("Added inside %s.", what)) : String(_t("Added just after %s.", what));
  }
  /**
   * What to say above the tiles: that fields are staged here, or why
   * none can be made. The plan's handoff to the composer is not it any
   * more -- a Python-owned model stages in place -- so its reason is
   * shown only when there is no draft road either.
   */
  get fieldPlanNote() {
    if (this.model.pythonOwned) {
      return String(
        _t(
          "%s is defined in Python, so a new field is staged here and appears after Apply.",
          this.model.modelName
        )
      );
    }
    const plan = this.fieldPlan;
    return plan && !plan.can_create ? plan.reason || "" : "";
  }
  get fieldPlan() {
    return this.model.fieldPlan;
  }
  get canAdd() {
    return this.model.canWrite;
  }
  // -- adding ---------------------------------------------------------------
  async onComponent(entry) {
    if (!this.canAdd) {
      return;
    }
    if (entry.component === "button") {
      const open = Boolean(this.state.newButton);
      this.state.newButton = open ? null : { string: "", action_id: "" };
      if (open) {
        this.model.buttonTarget = null;
      }
      return;
    }
    await this.model.addComponent(entry.component);
  }
  async addButton() {
    const form = this.state.newButton;
    if (!form) {
      return;
    }
    const values = { string: form.string, action_id: form.action_id };
    if (!values.action_id) {
      this.notification.add(String(_t("Choose the action this button should run.")), {
        type: "warning"
      });
      return;
    }
    values.action_id = Number(values.action_id);
    form.sending = true;
    const result = await this.model.addButton(values);
    if (result !== void 0) {
      this.state.newButton = null;
    } else {
      form.sending = false;
    }
  }
  /**
   * A field tile clicked: the field goes to the selection. A type a
   * label suffices for is created at once as "New <Type>"; one that
   * needs more opens the editor beside the tile first.
   */
  async onFieldType(entry, ev) {
    if (!entry.enabled || !this.canAdd) {
      return;
    }
    const label = String(_t("New %s", entry.label));
    if (this.model.needsDialog(entry.value)) {
      this.model.fieldTarget = null;
      const anchor = ev.currentTarget instanceof HTMLElement ? ev.currentTarget : null;
      this.openEditor(anchor, entry.value, label);
      return;
    }
    await this.finishField({ ttype: entry.value, field_description: label });
  }
  /** The tile for a picker key, to anchor the editor on. */
  tileFor(ttype) {
    const root = this.rootRef.el;
    const tile = root && root.querySelector(`.o_studio_tile_new[data-type="${ttype}"]`);
    return tile || root;
  }
  /**
   * Open the field editor for a new field of `ttype`, beside `anchor`.
   * Its Done sends the field where the model says: the held drop
   * target when there is one, the selection otherwise.
   */
  openEditor(anchor, ttype, label) {
    if (this.editor.isOpen) {
      this.editor.close();
    }
    this.editorForDrop = Boolean(this.model.fieldTarget);
    const props = {
      field: null,
      initial: { ttype, string: label },
      mode: this.model.pythonOwned ? "staged" : "live",
      fieldTypes: this.model.fieldTypes,
      existingNames: this.existingNames,
      // `ConsoleModel.modelName` is `string | false | undefined`
      // (the view may be model-less, or not yet answered) --
      // `console_model.ts`'s own `resolveRelated` already asserts
      // the same thing at the one point it is reached only once a
      // real model is in hand, which is equally true here: the
      // field editor is never opened before a model has loaded.
      modelName: this.model.modelName,
      inverseOptions: (comodel) => this.model.inverseOptions(comodel),
      resolveRelated: (path) => this.model.resolveRelated(path),
      // `onSave` is `(values) => void` on `FieldEditorProps` (Owl's
      // own `close: Function` schema doesn't await it either); the
      // real handler is async, so it is fired and not returned,
      // the same `void`-prefixed shape `apply_dialog.ts`'s own
      // `ConfirmationDialog` `confirm` callback already uses for an
      // identical async-handler-behind-a-void-prop situation.
      onSave: (values) => {
        void this.onEditorSave(values);
      },
      onDelete: null
    };
    this.editor.open(anchor || this.rootRef.el, props);
  }
  /** Every name the model already has, so the editor picks another. */
  get existingNames() {
    const context = this.model.context;
    return (context?.fields ?? []).map((field) => field.name);
  }
  async onEditorSave(values) {
    this.editor.close();
    await this.finishField(values);
  }
  /** Send the field, then put the cursor where the next edit is. */
  async finishField(values) {
    const result = await this.model.addNewField(values);
    if (result && result.created_field) {
      const el = this.rootRef.el;
      const root = el && el.closest(".o_studio_console");
      focusLabelRow(root || document.body);
    }
    return result;
  }
  async onExistingField(field) {
    if (!this.canAdd) {
      return;
    }
    await this.model.addExistingField(field.name);
  }
}
export {
  AddTab,
  COMPONENTS
};
