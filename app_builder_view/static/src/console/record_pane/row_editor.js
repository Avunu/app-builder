import { Component, useState } from "@odoo/owl";
import { CodeEditor } from "@web/core/code_editor/code_editor";
import { Domain } from "@web/core/domain";
import { DomainSelector } from "@web/core/domain_selector/domain_selector";
import { ModelFieldSelector } from "@web/core/model_field_selector/model_field_selector";
import { MultiRecordSelector } from "@web/core/record_selectors/multi_record_selector";
import { RecordSelector } from "@web/core/record_selectors/record_selector";
import * as compat from "../compat";
class RowEditor extends Component {
  static template = "app_builder_view.RowEditor";
  static components = {
    CodeEditor,
    DomainSelector,
    ModelFieldSelector,
    MultiRecordSelector,
    RecordSelector
  };
  static props = {
    row: Object,
    value: { optional: true },
    disabled: { type: Boolean, optional: true },
    // `{resModel, groups}`: the subject model, and the groups on offer.
    context: { type: Object, optional: true },
    onChange: Function
  };
  setup() {
    this.state = useState({ source: false });
  }
  get row() {
    return this.props.row;
  }
  get type() {
    return this.row.type;
  }
  get context() {
    return this.props.context || {};
  }
  get value() {
    return this.props.value;
  }
  get disabled() {
    return Boolean(this.props.disabled);
  }
  get text() {
    const value = this.value;
    return value === null || value === void 0 || value === false ? "" : String(value);
  }
  /** The id a record picker shows for a many2one value. */
  get recordId() {
    const value = this.value;
    return value && typeof value === "object" ? value.id : value || false;
  }
  /** The ids a picker shows for a many2many value. */
  get recordIds() {
    const value = this.value;
    return (value || []).map((v) => v && typeof v === "object" ? v.id : v);
  }
  /** A comodel domain the server filled in, as the picker takes it. */
  get comodelDomain() {
    const text = this.row.comodel_domain;
    if (!text) {
      return [];
    }
    try {
      return new Domain(text).toList({});
    } catch {
      return [];
    }
  }
  get fieldSelectorProps() {
    return {
      resModel: this.context.resModel,
      path: this.text,
      readonly: Boolean(this.props.disabled),
      update: (path) => this.props.onChange(path),
      // `row.follow` was never a real field: `Row`/`RowJSON`
      // (catalogue.py) have no such member, so this has always
      // resolved to `true`, unconditionally. Left as-is -- not this
      // migration's bug to fix behavior for -- typed to what it
      // actually always evaluates to instead of guessing a field
      // that does not exist.
      ...compat.fieldSelectorFollow(true)
    };
  }
  onText(ev) {
    this.props.onChange(ev.target.value);
  }
  onToggle(ev) {
    this.props.onChange(ev.target.checked);
  }
  onSelect(ev) {
    this.props.onChange(ev.target.value);
  }
  onGroups(ev) {
    this.props.onChange(
      [...ev.target.selectedOptions].map(
        (option) => Number(option.value)
      )
    );
  }
}
export {
  RowEditor
};
