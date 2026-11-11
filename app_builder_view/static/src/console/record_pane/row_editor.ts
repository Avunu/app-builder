/** @odoo-module **/
/**
 * One catalogue row, rendered as the control its type names.
 *
 * A row is data (`catalogue.Row`): a name, a label, a type and what the
 * type needs -- choices, a comodel, a domain -- and never a function. So
 * one component turns any row into its editor: the console's own inputs
 * for the plain types, and core's own components for the ones that have
 * one (a domain, a field path, code, a record picker). The value in and
 * the value out are the surface's shapes: a many2one is `{id,
 * display_name}` in and an id out, a many2many a list of those in and a
 * list of ids out, everything else as it is.
 *
 * The one version seam is the field selector's `followRelations` flag,
 * which master renamed; it goes through `compat.fieldSelectorFollow`.
 */

import {Component, useState} from "@odoo/owl";
import {CodeEditor} from "@web/core/code_editor/code_editor";
import {Domain} from "@web/core/domain";
import {DomainSelector} from "@web/core/domain_selector/domain_selector";
import {ModelFieldSelector} from "@web/core/model_field_selector/model_field_selector";
import {MultiRecordSelector} from "@web/core/record_selectors/multi_record_selector";
import {RecordSelector} from "@web/core/record_selectors/record_selector";
import * as compat from "../compat";
import type {RowJSON} from "../wire";

/**
 * A many2one/many2many value the way the surface's own wire contract
 * hands it in (module docstring above): `{id, display_name}`. Only `id`
 * is ever read here -- `display_name` is for the picker components
 * themselves (via `resId`/`resIds`, resolved through the name service),
 * never this file.
 */
interface RecordRefIn {
  id: number;
}

/**
 * One selectable group in a `"groups"` row, as `record_pane.js`'s own
 * `rowContext` getter builds it (`this.model.extra.groups`) -- that file
 * is still plain JS (a later cluster), so this is named narrowly here to
 * just the two fields this file's own template reads (`group.id` for the
 * `<option>`'s value, `group.name` for its label).
 */
interface RowEditorGroup {
  id: number;
  name: string;
}

/** `RowEditor`'s own `context` prop: `{resModel, groups}` -- the subject
 * model, and the groups on offer (the same comment the original JS carries
 * on `static props`, kept there too). */
interface RowEditorContext {
  resModel?: string;
  groups?: RowEditorGroup[];
}

interface Props {
  row: RowJSON;
  value?: unknown;
  disabled?: boolean;
  context?: RowEditorContext;
  onChange: (value: unknown) => void;
}

export class RowEditor extends Component<Props> {
  static override template = "app_builder_view.RowEditor";
  static components = {
    CodeEditor,
    DomainSelector,
    ModelFieldSelector,
    MultiRecordSelector,
    RecordSelector,
  };
  static override props = {
    row: Object,
    value: {optional: true},
    disabled: {type: Boolean, optional: true},
    // `{resModel, groups}`: the subject model, and the groups on offer.
    context: {type: Object, optional: true},
    onChange: Function,
  };

  // `declare`, not a plain field: with `target: es2022` (and so
  // `useDefineForClassFields` on), an ordinary `state!: ...;` field
  // declaration still emits `state;` in the compiled output, an own
  // property set to `undefined` in an implicit constructor that runs
  // before `setup()` -- harmless here (nothing reads `state` before
  // `setup()` assigns it), but a real emitted statement the original
  // untyped file never had, since it never declares `state` until
  // `setup()`'s own assignment. `declare` is pure erasure: no emitted
  // code at all, matching the original file's runtime exactly.
  declare state: {source: boolean};

  override setup() {
    this.state = useState({source: false});
  }

  get row(): RowJSON {
    return this.props.row;
  }

  get type(): string {
    return this.row.type;
  }

  get context(): RowEditorContext {
    return this.props.context || {};
  }

  get value(): unknown {
    return this.props.value;
  }

  get disabled(): boolean {
    return Boolean(this.props.disabled);
  }

  get text(): string {
    const value = this.value;
    // `value` is `unknown` (`RowJSON.value` -- whatever the row's own
    // type holds), so `tsc` cannot prove it has a meaningful
    // `toString`; unchanged from the original, which stringified the
    // same way with no such guarantee either -- the many2one/many2many
    // shapes `recordId`/`recordIds` exist for never reach here in
    // practice, this getter being the plain-scalar fallback.
    return value === null || value === undefined || value === false
      ? ""
      : // eslint-disable-next-line @typescript-eslint/no-base-to-string
        String(value);
  }

  /** The id a record picker shows for a many2one value. */
  get recordId(): number | false {
    const value = this.value;
    return value && typeof value === "object"
      ? (value as RecordRefIn).id
      : (value as number | false) || false;
  }

  /** The ids a picker shows for a many2many value. */
  get recordIds(): number[] {
    const value = this.value as (RecordRefIn | number)[] | false | null | undefined;
    return (value || []).map((v) => (v && typeof v === "object" ? v.id : v));
  }

  /** A comodel domain the server filled in, as the picker takes it. */
  get comodelDomain() {
    const text = this.row.comodel_domain;
    if (!text) {
      return [];
    }
    try {
      // `Domain.toList`'s own JSDoc names `context` as required
      // (`@param {Object} context`, no `[...]`), but plenty of real
      // vendor callers pass none at all (`field.js`, `utils.js`,
      // `search_model.js`) -- the same JSDoc-vs-runtime looseness
      // TYPING.md already tracks for `Registry.get`/`queryFirst`/
      // `useDragAndDrop`/`moveTo`. `{}` here matches `domain.js`'s
      // own `toJson()`, which evaluates "without context" the same
      // way.
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
      update: (path: string) => this.props.onChange(path),
      // `row.follow` was never a real field: `Row`/`RowJSON`
      // (catalogue.py) have no such member, so this has always
      // resolved to `true`, unconditionally. Left as-is -- not this
      // migration's bug to fix behavior for -- typed to what it
      // actually always evaluates to instead of guessing a field
      // that does not exist.
      ...compat.fieldSelectorFollow(true),
    };
  }

  onText(ev: Event): void {
    this.props.onChange((ev.target as HTMLInputElement | HTMLTextAreaElement).value);
  }

  onToggle(ev: Event): void {
    this.props.onChange((ev.target as HTMLInputElement).checked);
  }

  onSelect(ev: Event): void {
    this.props.onChange((ev.target as HTMLSelectElement).value);
  }

  onGroups(ev: Event): void {
    this.props.onChange(
      [...(ev.target as HTMLSelectElement).selectedOptions].map((option) =>
        Number(option.value)
      )
    );
  }
}
