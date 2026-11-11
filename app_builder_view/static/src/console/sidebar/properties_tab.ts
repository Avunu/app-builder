/** @odoo-module **/
/**
 * Properties: what the selected node is, and what can be changed about it.
 *
 * The rows come from the server's option catalogue, resolved against what
 * this browser has (`options.ts`); the node's current attributes and its
 * field come from `describe_node`, asked for on selection and cached until
 * the arch changes. A row that is edited writes a whole attribute map
 * through `set_attributes` -- a row targeting a widget option is changing
 * one key of the node's `options="{...}"` blob and has to hand the blob
 * back -- against the token the node was selected by, never against a
 * locator the browser worked out.
 *
 * Below the view's rows, the field's *definition*: what it is at the
 * model level, which the view can only dress. Three origins, three
 * treatments. A core field's definition is Python and is shown as facts.
 * A manual `x_` field's is a row of `ir.model.fields`, and its label,
 * help, flags and selection values are edited here through
 * `update_manual_field` -- including from the Label row above, which for
 * such a field writes the model's label rather than a view override, and
 * says so. A pending field's is staged on a draft and does not exist yet:
 * its ghost has no attributes to describe, so the panel shows what was
 * staged and opens the field editor on it, and can take it off the draft.
 *
 * Above the rows, the node's ancestors as a breadcrumb, so a field's group
 * and the group's tab are one click away; below them, Remove, which asks
 * first when the node has something in it.
 *
 * `this.props.model` is the real `ConsoleModel` (`../console_model`), the
 * same "hand the Owl component the real class" choice `canvas.ts` already
 * made for its own `model` prop -- unlike the narrow "owner" interfaces
 * (`ConsoleModelOwner`, `CanvasDragModel`) this migration uses for a
 * *plain* model class's own constructor, this is an Owl component reading
 * a large, already-real collaborator it was handed, not constructing one.
 */

import {Component, onWillDestroy, useEffect, useState} from "@odoo/owl";
import {_t} from "../l10n";
import type {ConsoleModel} from "../console_model";
import {ConfirmationDialog, useService} from "../odoo";
import type {DialogService} from "../odoo";
import {optionsFor, visibleRows, writeValue} from "../options";
import type {OptionsContext, ResolvedRow, RowValue} from "../options";
import {iconForType} from "../pending_widget";
import type {
  DescribedTarget,
  FieldDefinition,
  FieldEditorProps,
  SelectionOption,
  BuilderNode,
  Token,
} from "../types";
import type {
  DraftFieldJSON,
  EditingContext,
  PendingChangeJSON,
  SelectableGroupEntry,
} from "../wire";
import {useFieldEditor} from "./field_editor_fallback";
import {removeWithConfirm} from "./remove_flow";

interface Props {
  model: ConsoleModel;
}

/** One crumb of `crumbs`: an ancestor's token and the label its own
 * `tagFor` gives it. */
interface Crumb {
  token: Token;
  label: string;
}

/** One group of `panels`: `optionsFor`'s own `OptionGroupJSON` with its
 * `rows` resolved against the selection (`visibleRows`). */
interface PropertiesPanel {
  id: string;
  title: string;
  rows: ResolvedRow[];
}

/** One row of `facts`: always a `_t(...)`-labelled fact, `value` whatever
 * that fact actually is -- `ReturnType<typeof _t>` already includes plain
 * `string` (`_t`'s own JSDoc: `string|Markup|LazyTranslatedString`), the
 * same idiom `console_model.ts`'s own `KIND_LABELS` already uses for a
 * `Record` of translated values. */
interface FactRow {
  label: ReturnType<typeof _t>;
  value: ReturnType<typeof _t> | null | false;
}

/**
 * The keys `FieldDefinition.values` (`types.ts`) actually has that
 * `DEFINITION_ROWS` offers editing of -- a real subset (`ttype`/`relation`
 * are facts, never editable) named as a literal union rather than left as
 * `string`, so `values[row.name]` below is a real, typed property read
 * instead of an index-signature guess: `FieldDefinition.values` is a
 * plain named-property object, not an indexed one, so indexing it with a
 * bare `string` does not compile under `noPropertyAccessFromIndexSignature`
 * /strict indexed-access checking, the same class of fix
 * `outline_tree.test.ts`'s own `ByToken` union already established for an
 * unrelated `Object.fromEntries` lookup.
 */
type DefinitionRowName =
  | "field_description"
  | "help"
  | "required"
  | "readonly"
  | "index"
  | "translate"
  | "selection";

/**
 * The rows a manual field's definition can offer, in this order; which
 * of them appear is the server's word (`definition.editable`).
 */
interface DefinitionRowSpec {
  name: DefinitionRowName;
  label: ReturnType<typeof _t>;
  type: "text" | "toggle" | "selection";
}

/** One row of `definitionRows`: a `DefinitionRowSpec` plus the template
 * key and the value read off the definition (`definitionRows`). */
interface DefinitionRow extends DefinitionRowSpec {
  key: string;
  value: string | boolean | SelectionOption[];
}

const DEFINITION_ROWS: readonly DefinitionRowSpec[] = [
  {name: "field_description", label: _t("Label"), type: "text"},
  {name: "help", label: _t("Help"), type: "text"},
  {name: "required", label: _t("Required"), type: "toggle"},
  {name: "readonly", label: _t("Read-only"), type: "toggle"},
  {name: "index", label: _t("Indexed"), type: "toggle"},
  {name: "translate", label: _t("Translatable"), type: "toggle"},
  {name: "selection", label: _t("Values"), type: "selection"},
];

/** What the ghost stands for (`pendingField`): the node's own word, then
 * what the draft says, or `null` off anything but a pending ghost. */
interface PendingFieldSummary {
  name: string;
  string: string;
  ttype: string;
  typeLabel: string;
  resolved: boolean;
  staged: DraftFieldJSON | null;
}

interface PropertiesTabState {
  target: DescribedTarget | null;
  loading: boolean;
  selectionDraft: SelectionOption[] | null;
}

/**
 * What this file hands `this.editor.open(...)` -- `FieldEditorProps`
 * (`types.ts`) minus `close`. Every real opener of `useFieldEditor` in
 * this tree (this file's own `onEditOwned`/`onEditPending`, `view_tab.js`'s
 * `editorProps`, `add_tab.js`'s `openEditor`) omits `close` from what it
 * hands `.open()` -- confirmed by grepping every real call site, not an
 * oversight of this conversion. `usePopover`'s own `open(target, props)`
 * (`@web/core/popover/popover_hook.js`) forwards `props` to
 * `popoverService.add` unchanged, and neither that service nor `Popover`
 * itself (`popover.js`) injects a `close` into the *rendered* component's
 * own props (`Popover`'s `close` prop is for its own click-away/escape
 * chrome, not forwarded into `componentProps`) -- so `FieldEditorFallback`'s
 * `props.close` is genuinely `undefined` whenever this file opens it, even
 * though `field_editor_fallback.ts`'s own `onKeydown` calls
 * `this.props.close()` unconditionally on Escape. A real, pre-existing
 * gap across all three callers plus the fallback's own expectation --
 * flagged in this file's findings, not fixed here (rule: type-adding pass,
 * not a behavior change).
 */
type PropertiesEditorProps = Omit<FieldEditorProps, "close">;

/** `OptionsContext` (`options.ts`) built from the editing context's own
 * `catalogue`/`fields`/`options`. */
function optionsContextOf(context: EditingContext | null): OptionsContext {
  if (!context) {
    return {};
  }
  return {
    catalogue: context.catalogue,
    fields: context.fields,
    options: context.options,
  };
}

export class PropertiesTab extends Component<Props> {
  static override template = "app_builder_view.PropertiesTab";
  static override props = {model: Object};

  model!: ConsoleModel;
  dialog!: DialogService;
  editor!: ReturnType<typeof useFieldEditor>;
  state!: PropertiesTabState;

  override setup(): void {
    this.model = useState(this.props.model);
    this.dialog = useService("dialog");
    this.editor = useFieldEditor();
    this.state = useState<PropertiesTabState>({
      target: null,
      loading: false,
      selectionDraft: null,
    });
    let alive = true;
    onWillDestroy(() => {
      alive = false;
    });
    useEffect(
      (token: Token | null, version: string | null) => {
        this.state.target = null;
        this.state.selectionDraft = null;
        if (!token || !version || this.isPending) {
          // A ghost is not in the arch: there is nothing to
          // describe, and its definition is on the draft.
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

  get node(): BuilderNode | null {
    return this.model.selectedNode;
  }

  get token(): Token | null {
    return this.model.selection ? this.model.selection.token : null;
  }

  /** The selected node's ancestors, outermost first, as clickable crumbs. */
  get crumbs(): Crumb[] {
    const nodes = this.model.nodes;
    const out: Crumb[] = [];
    const startNode = this.node;
    let token: Token | null = startNode ? startNode.parent : null;
    // `nodes[token]` read once per hop and captured, rather than
    // re-indexed by the same `token` a second time to walk to its
    // parent -- `noUncheckedIndexedAccess` does not remember the loop
    // condition's own read (the repeated-bracket-index trap,
    // TYPING.md).
    while (token) {
      const current = nodes[token];
      if (!current) {
        break;
      }
      out.unshift({token, label: this.model.tagFor(token)});
      token = current.parent;
    }
    return out;
  }

  get panels(): PropertiesPanel[] {
    const target = this.state.target;
    if (!target || !target.found) {
      return [];
    }
    const context = optionsContextOf(this.model.context);
    return optionsFor(context, target).map((group) => ({
      id: group.id,
      title: group.title,
      rows: visibleRows(group, target, context),
    }));
  }

  get groupChoices(): SelectableGroupEntry[] {
    const context = this.model.context;
    return (context && context.groups) || [];
  }

  get canRemove(): boolean {
    return Boolean(this.node && this.node.removable && this.model.packageId);
  }

  // -- the definition -----------------------------------------------------

  get definition(): FieldDefinition | null {
    return (this.state.target && this.state.target.definition) || null;
  }

  get isManual(): boolean {
    return Boolean(this.definition && this.definition.origin === "manual");
  }

  /**
   * Whether the Label row above writes the model's label, not the
   * view's: for a manual field, unless this view already overrides the
   * label -- then the override is what is on screen, and the row edits
   * that, as it says.
   */
  labelWritesDefinition(row: ResolvedRow): boolean {
    if (row.name !== "string" || row.target === "option" || !this.isManual) {
      return false;
    }
    const attrs = this.state.target?.attrs ?? {};
    // `attrs` is `Readonly<Record<string, string>>` -- bracket
    // notation, not `.string`, under `noPropertyAccessFromIndexSignature`.
    return !attrs["string"];
  }

  /**
   * What the Label row writes, when that is not the obvious thing. A
   * manual field's row renames the field itself; a field this package
   * defines in Python has a definition of its own below, and the row
   * dresses this view only -- said here, or the two labels look like
   * one that did not take.
   */
  rowHint(row: ResolvedRow): ReturnType<typeof _t> {
    if (row.name !== "string" || row.target === "option") {
      return "";
    }
    if (this.labelWritesDefinition(row)) {
      return _t("Renames the field itself, on every view.");
    }
    if (this.isOwnedPython) {
      return _t(
        "On this view only. Edit the definition below to rename the field itself."
      );
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

  get labelNote(): ReturnType<typeof _t> {
    const label = this.labelSwitch;
    if (!label) {
      return "";
    }
    if (label.shown) {
      return label.by === "label"
        ? _t("Shown by a label of its own, just before it.")
        : "";
    }
    return label.in_group
      ? _t("Not shown: the label is switched off.")
      : _t(
          "Not shown here: outside a group a field has no label unless it is given one."
        );
  }

  async onToggleLabel(ev: Event): Promise<void> {
    const label = this.labelSwitch;
    const token = this.token;
    if (!label || !token) {
      return;
    }
    await this.model.setLabelShown(token, (ev.target as HTMLInputElement).checked);
  }

  /** The editable rows of a manual field's definition, with their values. */
  get definitionRows(): DefinitionRow[] {
    const definition = this.definition;
    if (!definition || !this.isManual) {
      return [];
    }
    // `FieldDefinition.editable`/`.values` are both required fields on
    // that type, never absent -- the original's own `|| []`/`|| {}`
    // fallbacks were always dead, pre-existing JS looseness rather
    // than a real case; direct reads here instead of reintroducing an
    // unreachable branch.
    const editable = definition.editable;
    const values = definition.values;
    // The Label row of the view section already writes the model's
    // label when this view does not override it; one row for it.
    const attrs = this.state.target?.attrs ?? {};
    const rows = DEFINITION_ROWS.filter(
      (row) =>
        editable.includes(row.name) &&
        (row.name !== "field_description" || attrs["string"])
    );
    return rows.map(
      (row): DefinitionRow => ({
        ...row,
        key: `def:${row.name}`,
        value:
          row.type === "toggle" ? Boolean(values[row.name]) : values[row.name] || "",
      })
    );
  }

  /** The read-only facts of any field's definition. */
  get facts(): FactRow[] {
    const definition = this.definition;
    if (!definition) {
      return [];
    }
    const values = definition.values;
    const out: FactRow[] = [
      {label: _t("Technical name"), value: this.node && this.node.name},
      {label: _t("Type"), value: values.ttype},
    ];
    if (values.relation) {
      out.push({label: _t("Relation"), value: values.relation});
    }
    if (!this.isManual) {
      out.push(
        {label: _t("Label"), value: values.field_description},
        {label: _t("Required"), value: values.required ? _t("Yes") : _t("No")},
        {label: _t("Read-only"), value: values.readonly ? _t("Yes") : _t("No")}
      );
      if (values.help) {
        out.push({label: _t("Help"), value: values.help});
      }
    }
    out.push({
      label: _t("Defined"),
      value: definition.origin === "manual" ? _t("in this database") : _t("in Python"),
    });
    return out;
  }

  /** The selection values being edited, a copy until they are sent. */
  get selectionRows(): SelectionOption[] {
    if (this.state.selectionDraft) {
      return this.state.selectionDraft;
    }
    return (this.definition?.values.selection || []).map((row) => ({...row}));
  }

  editSelectionRow(index: number, key: "label" | "value", value: string): void {
    const rows = this.selectionRows.map((row) => ({...row}));
    // `index` always names a row the template itself just rendered
    // from `selectionRows`, an invariant `noUncheckedIndexedAccess`
    // cannot see from the signature alone -- the same asserted-index
    // idiom `field_editor_fallback.ts`'s own `updateSelectionRow` uses
    // for the identical situation.
    rows[index] = {...rows[index]!, [key]: value};
    const updatedRow = rows[index];
    if (key === "label" && !updatedRow.value) {
      updatedRow.value = (value || "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "");
    }
    this.state.selectionDraft = rows;
  }

  addSelectionRow(): void {
    const rows = this.selectionRows.map((row) => ({...row}));
    rows.push({value: "", label: "", sequence: (rows.length + 1) * 10});
    this.state.selectionDraft = rows;
  }

  removeSelectionRow(index: number): void {
    this.state.selectionDraft = this.selectionRows.filter((_row, i) => i !== index);
  }

  get selectionDirty(): boolean {
    return Boolean(this.state.selectionDraft);
  }

  async saveSelection(): Promise<void> {
    const rows = this.selectionRows
      .filter((row) => row.value)
      .map((row, index) => ({
        value: row.value,
        label: row.label || row.value,
        sequence: row.sequence || (index + 1) * 10,
      }));
    if (!rows.length) {
      this.model.notification.add(String(_t("A selection needs at least one value.")), {
        type: "warning",
      });
      return;
    }
    await this.writeDefinition({selection: rows});
  }

  /** One write to `ir.model.fields`, and the panel shows what it now says. */
  async writeDefinition(values: Record<string, unknown>): Promise<void> {
    if (!this.token || !this.state.target) {
      return;
    }
    const token = this.token;
    const definition = await this.model.updateManualField(token, values);
    // Read fresh, after the `await`: the selection (and so
    // `this.state.target`) may have moved on while the request was in
    // flight -- the guard below re-checks the current state rather
    // than trusting what was true before awaiting, then captures it
    // once for the rest of this method (the "capture right after the
    // check" fix for the nullable-`this.field`-after-a-call trap).
    const target = this.state.target;
    if (definition === undefined || !target || this.token !== token) {
      return;
    }
    this.state.selectionDraft = null;
    this.state.target = {
      ...target,
      definition,
      field: target.field
        ? {
            ...target.field,
            // `definition.values` is always present
            // (`FieldDefinition.values` is required, not
            // optional) -- the original's own `(definition.values
            // || {})` fallback was always dead.
            string: definition.values.field_description,
          }
        : target.field,
    };
  }

  onDefinitionToggle(row: DefinitionRow, ev: Event): Promise<void> {
    return this.writeDefinition({[row.name]: (ev.target as HTMLInputElement).checked});
  }

  onDefinitionInput(row: DefinitionRow, ev: Event): Promise<void> {
    return this.writeDefinition({
      [row.name]: (ev.target as HTMLInputElement).value,
    });
  }

  // -- fields the package defines in Python ---------------------------------
  //
  // Their definition is a class attribute: editing it is staged on the
  // model's draft, exactly like a pending field's, and lands on Apply.
  // Three things the panel says about one: what the draft already holds
  // for it, how to edit it, and that a removal drops a column.

  /** A field node of a model this package defines in Python. */
  get isOwnedPython(): boolean {
    return Boolean(
      this.model.pythonOwned &&
        this.node &&
        this.node.kind === "field" &&
        this.definition &&
        this.definition.origin !== "manual"
    );
  }

  /** The change the draft holds for this field, or `null`. */
  get ownedPendingKind(): PendingChangeJSON["kind"] | null {
    if (!this.isOwnedPython || !this.node) {
      return null;
    }
    const node = this.node;
    const entry = this.model.modelFields.find((f) => f.name === node.name);
    return (entry && entry.pendingKind) || null;
  }

  get ownedPendingNote(): ReturnType<typeof _t> {
    switch (this.ownedPendingKind) {
      case "changed":
        return _t("Its definition has a staged edit; Apply writes it.");
      case "removed":
        return _t(
          "Staged for removal; Apply drops the column and keeps its data aside."
        );
      case "added":
        return _t("Staged as a new field; Apply creates it.");
      default:
        return "";
    }
  }

  /** Open the field editor on the class attribute, staged on the draft. */
  async onEditOwned(ev: MouseEvent): Promise<void> {
    // `!node.name` matches `console_model.ts`'s own `updateManualField`
    // guard for the identical situation (`BuilderNode.name` is
    // `string | null` on the flat, non-`kind`-discriminated shape; a
    // `field`-kind node's `name` is always set in practice, but not
    // provably so from the type alone). Captured into a local right
    // after the check, rather than re-reading the `this.node` getter
    // again below, the same "capture right after the check" fix this
    // file applies everywhere else (TYPING.md's nullable-`this.field`
    // trap).
    const node = this.node;
    if (!node || !node.name) {
      return;
    }
    const name = node.name;
    const anchor = ev.currentTarget as HTMLElement;
    const draft = await this.model._ensureDraft();
    const staged = draft && this.model.stagedField(name);
    if (!staged) {
      this.model.notification.add(
        String(_t("The class this field belongs to could not be read into a draft.")),
        {type: "warning"}
      );
      return;
    }
    const draftFields = (this.model.draft && this.model.draft.fields) || [];
    const editorProps: PropertiesEditorProps = {
      field: {...staged},
      mode: "staged",
      fieldTypes: this.model.fieldTypes,
      existingNames: draftFields.map((f) => f.name).filter((n) => n !== name),
      // Always a real model here -- editing an owned field's
      // definition only ever happens with a model loaded
      // (`isOwnedPython`) -- matching `resolveRelated`'s own
      // identical `this.modelName as string` cast (`console_model.ts`).
      modelName: this.model.modelName as string,
      inverseOptions: (comodel: string) => this.model.inverseOptions(comodel),
      resolveRelated: (path: string) => this.model.resolveRelated(path),
      onSave: (values) => {
        this.editor.close();
        void this.model.updateStaged(name, values);
      },
      onDelete: () => {
        this.editor.close();
        this.onRemoveOwned();
      },
    };
    this.editor.open(anchor, editorProps);
  }

  /** Stage the removal of a class attribute: a dropped column on Apply. */
  onRemoveOwned(): void {
    const node = this.node;
    if (!node || !node.name) {
      return;
    }
    const name = node.name;
    const label = this.definition?.values.field_description || name;
    this.dialog.add(ConfirmationDialog, {
      title: _t("Remove field from the model"),
      body: _t(
        "Remove %s from the model? Nothing changes until Apply; then its " +
          "column is dropped and its data kept aside by a migration. " +
          "Discard the pending changes to take it back before that.",
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
      cancel: () => {},
    });
  }

  private async finishRemoveOwned(name: string): Promise<void> {
    const result = await this.model.removePending(name);
    if (result !== undefined) {
      this.model.clearSelection();
    }
  }

  // -- pending fields -----------------------------------------------------

  get isPending(): boolean {
    return Boolean(this.node && this.node.kind === "pending");
  }

  /** What the ghost stands for: the node's word, then the draft's. */
  get pendingField(): PendingFieldSummary | null {
    const node = this.node;
    if (!node || !this.isPending) {
      return null;
    }
    const info = node.pending;
    // A `kind: "pending"` ghost always carries `pending` with a real
    // `name` (`_stamp_pending`'s own construction,
    // `builder_view_canvas.py`) -- `BuilderNode` stays one flat shape
    // rather than a `kind`-discriminated union (`types.ts`'s own
    // note), so this is asserted rather than provably narrowed from
    // `node.kind === "pending"` alone.
    const name = (info?.name || node.name) as string;
    const staged = this.model.stagedField(name);
    return {
      name,
      string: staged?.string || info?.string || name,
      ttype: staged?.ttype || info?.ttype || "",
      typeLabel: staged?.type_label || info?.ttype || "",
      resolved: info?.resolved !== false,
      staged,
    };
  }

  get pendingIcon(): string {
    const field = this.pendingField;
    return field ? iconForType(field.ttype, field.ttype) : "";
  }

  /** Open the field editor on the staged definition, beside the button. */
  async onEditPending(ev: MouseEvent): Promise<void> {
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
        {type: "warning"}
      );
      return;
    }
    const name = field.name;
    const anchor = ev.currentTarget as HTMLElement;
    const draftFields = (this.model.draft && this.model.draft.fields) || [];
    const editorProps: PropertiesEditorProps = {
      field: {...staged},
      mode: "staged",
      fieldTypes: this.model.fieldTypes,
      existingNames: draftFields.map((f) => f.name).filter((n) => n !== name),
      modelName: this.model.modelName as string,
      inverseOptions: (comodel: string) => this.model.inverseOptions(comodel),
      resolveRelated: (path: string) => this.model.resolveRelated(path),
      onSave: (values) => {
        this.editor.close();
        void this.model.updateStaged(name, values);
      },
      onDelete: () => {
        this.editor.close();
        this.onRemovePending();
      },
    };
    this.editor.open(anchor, editorProps);
  }

  onRemovePending(): void {
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
      cancel: () => {},
    });
  }

  // -- writing ------------------------------------------------------------

  async onRowChange(row: ResolvedRow, rawValue: unknown): Promise<void> {
    const token = this.token;
    const target = this.state.target;
    if (!token || !target) {
      return;
    }
    if (this.labelWritesDefinition(row)) {
      // The label of a manual field is the model's, and renaming it
      // here renames it everywhere rather than on this view alone.
      await this.writeDefinition({field_description: rawValue});
      return;
    }
    await this.model.setAttributes(token, writeValue(row, rawValue, target));
  }

  onToggle(row: ResolvedRow, ev: Event): Promise<void> {
    return this.onRowChange(row, (ev.target as HTMLInputElement).checked);
  }

  onInput(row: ResolvedRow, ev: Event): Promise<void> {
    return this.onRowChange(
      row,
      (ev.target as HTMLInputElement | HTMLSelectElement).value
    );
  }

  onMultiSelect(row: ResolvedRow, ev: Event): Promise<void> {
    return this.onRowChange(
      row,
      [...(ev.target as HTMLSelectElement).selectedOptions].map(
        (option) => option.value
      )
    );
  }

  /** The Label row of a manual field shows the model's label, not the view's. */
  rowValue(row: ResolvedRow): RowValue {
    if (this.labelWritesDefinition(row) && !row.value) {
      return this.definition?.values.field_description || "";
    }
    return row.value;
  }

  async onRemove(): Promise<void> {
    const token = this.token;
    if (!token) {
      return;
    }
    await removeWithConfirm({model: this.model, dialog: this.dialog, token});
  }
}
