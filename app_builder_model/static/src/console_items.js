import { registry } from "@web/core/registry";
import { FieldPopover } from "./field_popover";
class ConsoleFieldEditor extends FieldPopover {
  static template = "app_builder_model.ConsoleFieldEditor";
  static props = {
    ...FieldPopover.props,
    initial: { type: Object, optional: true },
    mode: { type: String, optional: true }
  };
  setup() {
    super.setup();
    const initial = this.props.initial;
    if (this.isNew && initial) {
      const entry = this.props.fieldTypes.find((t) => t.value === initial.ttype);
      if (entry && entry.enabled) {
        this.onTypeChange(initial.ttype);
      }
      if (initial.string) {
        this.state.string = initial.string;
        this.state.name = this.suggestName(initial.string);
      }
    }
  }
  /** Whether the field is a class attribute waiting for an Apply. */
  get staged() {
    return this.props.mode !== "live";
  }
  /**
   * The types the console can make here: on a live model only what
   * the server said can be created as a row, so the picker does not
   * offer a computed field it would then refuse.
   */
  get typeGroups() {
    if (this.staged) {
      return super.typeGroups;
    }
    const groups = {};
    for (const entry of this.props.fieldTypes) {
      if (entry.live === false) {
        continue;
      }
      (groups[entry.group] ??= []).push(entry);
    }
    return Object.entries(groups).map(([name, choices]) => ({ name, choices }));
  }
}
registry.category("app_builder.field_editor").add("field_popover", ConsoleFieldEditor);
export {
  ConsoleFieldEditor
};
