/** @odoo-module **/
/**
 * Add: the palette -- components, new fields, existing fields -- as tiles.
 *
 * Every tile is a thing that can be put into the view, two ways. Dragged,
 * it lands where it is dropped: the tile carries what it stands for in
 * its dataset -- `data-kind` and `data-key` -- and `drag.js` reads that
 * when it is picked up; nothing else about a drag lives here. Clicked (or
 * Enter, on a focused tile), it goes to the selection: inside a selected
 * container, after a selected leaf, at the end of the view when nothing
 * is selected -- the keyboard's way, and the one that needs no aim. A
 * disabled tile keeps its tooltip and is neither.
 *
 * The one tile a drop does not finish by itself is Button: it needs an
 * action before anything is written, so the drop hands the palette the
 * spot and the same inline form asks for the rest, then sends it there.
 *
 * Three sections, three sources. Components are a fixed list. New fields
 * come from the server's field-type catalogue for this model, which says
 * which are available and why not otherwise, and for each whether it can
 * be made live here and whether it needs its definition first. A tile of
 * a type a label suffices for -- Text, Decimal, Date -- creates at once,
 * as "New Text", and hands the cursor to the Label row; one that needs
 * more -- a relation, a selection -- opens the field editor before
 * anything is sent, so Cancel is no request. On a Python-owned model the
 * same tiles stage the field on a draft instead, and the canvas shows a
 * ghost where it will land. Existing fields are what the model has and
 * the view does not, searchable.
 *
 * A kanban has a fourth source, small and its own. A field declared at
 * the kanban's root -- `<field name="x"/>` above the templates -- loads
 * a value for the card and shows nothing, so the server counts it as
 * placed and keeps it out of the existing fields; yet dropping it into
 * the card is exactly what someone who wants to see it does, and the
 * server takes that drop. Those fields are listed here from the node
 * table, as tiles like any other existing field, under their own title.
 */

import {Component, useEffect, useRef, useState} from "@odoo/owl";
import {_t} from "../l10n";
import {focusLabelRow} from "../drag";
import {useService} from "../odoo";
import {iconForType} from "../pending_widget";
import {useFieldEditor} from "./field_editor_fallback";
import type {ConsoleModel} from "../console_model";
import type {
  DropSuccessResult,
  FieldEditorProps,
  NotificationService,
  BuilderModelFieldEntry,
} from "../types";
import type {AddableFieldEntry, FieldTypeEntry, NewFieldPlan} from "../wire";

/** One entry of the fixed Components list -- `label`/`icon` are the
 * tile's own, `tags` says which view types offer it (`components`
 * below). */
interface ComponentTile {
  component: string;
  label: ReturnType<typeof _t>;
  icon: string;
  tags: string[];
}

export const COMPONENTS: ComponentTile[] = [
  {component: "page", label: _t("Tabs"), icon: "fa fa-folder-o", tags: ["form"]},
  {component: "columns", label: _t("Columns"), icon: "fa fa-columns", tags: ["form"]},
  {component: "group", label: _t("Group"), icon: "fa fa-object-group", tags: ["form"]},
  {component: "separator", label: _t("Separator"), icon: "fa fa-minus", tags: ["form"]},
  {
    component: "button",
    label: _t("Button"),
    icon: "fa fa-hand-pointer-o",
    tags: ["form"],
  },
];

/** `fieldTypes`'s own tile: a `FieldTypeEntry` with `enabled`/`tooltip`
 * recomputed for this model's state and an `icon` added -- what the
 * template renders, not `ConsoleModel.fieldTypes` itself (that goes
 * straight into the field editor's own props, unmodified, in
 * `openEditor`). */
interface FieldTypeTile extends FieldTypeEntry {
  icon: string;
}

/** A Button tile's inline form -- `action_id` starts as the `<select>`'s
 * own string value and is coerced to a number only once, right before
 * it is sent (`addButton`). `dropped`/`sending` are set only by the
 * `buttonTarget` effect and `addButton` itself, never read before either
 * has run. */
interface NewButtonForm {
  string: string;
  action_id: string | number;
  dropped?: boolean;
  sending?: boolean;
}

interface AddTabState {
  search: string;
  newButton: NewButtonForm | null;
}

interface Props {
  model: ConsoleModel;
}

export class AddTab extends Component<Props> {
  static override template = "app_builder_view.AddTab";
  static override props = {model: Object};

  model!: ConsoleModel;
  notification!: NotificationService;
  rootRef!: {el: HTMLElement | null};
  editor!: ReturnType<typeof useFieldEditor>;
  state!: AddTabState;
  /** Whether the field editor currently open was opened for a drop
   * (`openEditor`'s own `Boolean(this.model.fieldTarget)`, read there)
   * -- set only inside `openEditor`, never during `setup()` itself, so
   * it is genuinely `undefined` until the first field editor this tab
   * opens. */
  editorForDrop: boolean | undefined;

  override setup(): void {
    this.model = useState(this.props.model);
    this.notification = useService("notification");
    this.rootRef = useRef("root");
    this.editor = useFieldEditor();
    this.state = useState<AddTabState>({
      search: "",
      newButton: null,
    });
    // A field tile dropped on the canvas whose type needs the editor
    // first: open it beside the tile, on the spot the model holds.
    // When the model lets that spot go -- the view changed under it
    // -- the editor is closed rather than left asking for a field
    // with nowhere to go.
    useEffect(
      (serial: number | null) => {
        const target = this.model.fieldTarget;
        if (serial && target) {
          // `drop()` (`console_model.ts`) only ever creates a
          // field target with `ttype`/`label` set to real
          // strings (defaulting to `""`), never `undefined` --
          // both are optional on the stored shape only because
          // it is shared with `buttonTarget`, which never sets
          // either.
          this.openEditor(this.tileFor(target.ttype), target.ttype!, target.label!);
        } else if (!target && this.editor.isOpen && this.editorForDrop) {
          this.editor.close();
        }
      },
      () => [this.model.fieldTarget && this.model.fieldTarget.serial]
    );
    // A Button tile dropped on the canvas: open the form for it. And
    // when the model lets the drop go -- the view changed under it --
    // a form that would still say "where it was dropped" is closed,
    // unless it is this tab sending that drop, which takes the target
    // out of the model itself and keeps the form for a refused retry.
    useEffect(
      (serial: number | null) => {
        const form = this.state.newButton;
        if (serial) {
          this.state.newButton = {string: "", action_id: "", dropped: true};
        } else if (form && form.dropped && !form.sending) {
          this.state.newButton = null;
        }
      },
      () => [this.model.buttonTarget && this.model.buttonTarget.serial]
    );
  }

  // -- what the palette offers ---------------------------------------------

  get components(): ComponentTile[] {
    const type = this.model.viewType;
    // `type` is `string | false | undefined` (`ConsoleModel.viewType`);
    // `Array<string>.includes` only takes a `string`, so the other two
    // are guarded out here rather than passed through -- both already
    // make `.includes` answer `false`, the same as before.
    return COMPONENTS.filter(
      (entry) => typeof type === "string" && entry.tags.includes(type)
    );
  }

  /**
   * The New Fields tiles. On a Python-owned model every available type
   * is offered, to be staged; elsewhere only what can be made live,
   * and a type that cannot keeps the server's reason as its tooltip.
   */
  get fieldTypes(): FieldTypeTile[] {
    const staged = this.model.pythonOwned;
    const plan = this.fieldPlan;
    return this.model.fieldTypes.map((entry) => {
      const enabled = Boolean(entry.enabled && (staged || entry.live));
      let tooltip = entry.tooltip || "";
      if (enabled) {
        tooltip = entry.needs_dialog
          ? String(_t("Opens the field editor first"))
          : staged
            ? String(_t("Staged until Apply"))
            : "";
      } else if (entry.enabled && !staged && plan && !plan.can_create) {
        tooltip = plan.reason || tooltip;
      } else if (entry.enabled && !enabled) {
        tooltip = tooltip || String(_t("Cannot be created live on this model"));
      }
      return {
        ...entry,
        enabled,
        tooltip,
        icon: iconForType(entry.value, entry.ttype),
      };
    });
  }

  get existingFields(): AddableFieldEntry[] {
    const needle = (this.state.search || "").toLowerCase();
    const fields = this.model.palette || [];
    if (!needle) {
      return fields;
    }
    return fields.filter(
      (f) =>
        f.string.toLowerCase().includes(needle) || f.name.toLowerCase().includes(needle)
    );
  }

  /**
   * The fields a kanban declares at its root and shows in no card:
   * loaded for the template, invisible on the board, and not in the
   * existing fields since the arch already names them. Searchable
   * like those, and dropped the same way.
   */
  get declaredFields(): BuilderModelFieldEntry[] {
    if (this.model.viewType !== "kanban") {
      return [];
    }
    const nodes = this.model.nodes;
    const root = this.model.root;
    const shown = new Set<string>();
    for (const node of Object.values(nodes)) {
      if (node.kind === "field" && node.dom && node.name) {
        shown.add(node.name);
      }
    }
    const needle = (this.state.search || "").toLowerCase();
    const fields: BuilderModelFieldEntry[] = [];
    for (const node of Object.values(nodes)) {
      // Split from the original's single `||`-chained guard: the
      // `shown.has`/`fields.some` calls below are real function
      // calls, which lose `node.name`'s narrowing for every read
      // that follows them (TYPING.md's own "nullable field after a
      // null-check" trap) -- so the `!node.name` guard is checked
      // and `node.name` captured into `name` on its own, before
      // either call runs, and everything past this point reads
      // `name` instead of `node.name` again.
      if (node.kind !== "field" || node.dom || node.parent !== root || !node.name) {
        continue;
      }
      const name = node.name;
      if (shown.has(name) || fields.some((f) => f.name === name)) {
        continue;
      }
      const info = node.field;
      const field: BuilderModelFieldEntry = {
        name,
        string: info?.string || node.string || name,
        type: info?.type || "char",
      };
      if (
        !needle ||
        field.string.toLowerCase().includes(needle) ||
        field.name.toLowerCase().includes(needle)
      ) {
        fields.push(field);
      }
    }
    return fields;
  }

  iconFor(field: {type: string}): string {
    return iconForType(field.type, field.type);
  }

  /** What the current selection means for something added now. */
  get anchorNote(): string {
    const token = this.model.anchorToken;
    const node = token ? this.model.nodes[token] : undefined;
    // `!token ||` is redundant at runtime (`node` is already
    // `undefined` whenever `token` is `null`, from the ternary
    // above) but is what lets `token` narrow to non-null past this
    // guard, for `tagFor(token)` below.
    if (!token || !node || node.kind === "root") {
      if (this.model.viewType === "kanban") {
        // The board's root takes no field a person can see: a
        // click lands in the selected part of a card, or nowhere.
        return String(_t("Select a place in a card first."));
      }
      return String(_t("Added at the end of the view."));
    }
    const what = this.model.tagFor(token);
    return node.container
      ? String(_t("Added inside %s.", what))
      : String(_t("Added just after %s.", what));
  }

  /**
   * What to say above the tiles: that fields are staged here, or why
   * none can be made. The plan's handoff to the composer is not it any
   * more -- a Python-owned model stages in place -- so its reason is
   * shown only when there is no draft road either.
   */
  get fieldPlanNote(): string {
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

  get fieldPlan(): NewFieldPlan | null {
    return this.model.fieldPlan;
  }

  get canAdd(): boolean {
    return this.model.canWrite;
  }

  // -- adding ---------------------------------------------------------------

  async onComponent(entry: ComponentTile): Promise<void> {
    if (!this.canAdd) {
      return;
    }
    if (entry.component === "button") {
      // Closing the form forgets a dropped spot too; the next click
      // adds at the selection, as it says.
      const open = Boolean(this.state.newButton);
      this.state.newButton = open ? null : {string: "", action_id: ""};
      if (open) {
        this.model.buttonTarget = null;
      }
      return;
    }
    await this.model.addComponent(entry.component);
  }

  async addButton(): Promise<void> {
    const form = this.state.newButton;
    if (!form) {
      return;
    }
    const values = {string: form.string, action_id: form.action_id};
    if (!values.action_id) {
      this.notification.add(String(_t("Choose the action this button should run.")), {
        type: "warning",
      });
      return;
    }
    values.action_id = Number(values.action_id);
    form.sending = true;
    const result = await this.model.addButton(values);
    if (result !== undefined) {
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
  async onFieldType(entry: FieldTypeTile, ev: MouseEvent): Promise<void> {
    if (!entry.enabled || !this.canAdd) {
      return;
    }
    const label = String(_t("New %s", entry.label));
    if (this.model.needsDialog(entry.value)) {
      // A click is not a drop: whatever spot a drop was holding is
      // let go of, so the editor's Done goes to the selection.
      this.model.fieldTarget = null;
      // `ev.currentTarget` is `EventTarget | null` in the DOM lib,
      // not `HTMLElement` -- narrowed the same way this migration's
      // own `ev.target instanceof Element` trap already does, just
      // against `HTMLElement` since that is what `openEditor`'s own
      // anchor needs.
      const anchor = ev.currentTarget instanceof HTMLElement ? ev.currentTarget : null;
      this.openEditor(anchor, entry.value, label);
      return;
    }
    await this.finishField({ttype: entry.value, field_description: label});
  }

  /** The tile for a picker key, to anchor the editor on. */
  tileFor(ttype: string | undefined): HTMLElement | null {
    const root = this.rootRef.el;
    const tile =
      root &&
      root.querySelector<HTMLElement>(`.o_builder_tile_new[data-type="${ttype}"]`);
    return tile || root;
  }

  /**
   * Open the field editor for a new field of `ttype`, beside `anchor`.
   * Its Done sends the field where the model says: the held drop
   * target when there is one, the selection otherwise.
   */
  openEditor(anchor: HTMLElement | null, ttype: string, label: string): void {
    if (this.editor.isOpen) {
      this.editor.close();
    }
    this.editorForDrop = Boolean(this.model.fieldTarget);
    // `Omit<FieldEditorProps, "close">`, not the full shape: `usePopover`'s
    // own `open(target, props)` (`@web/core/popover/popover_hook.js`)
    // forwards `props` unchanged and never injects a `close` into it,
    // and no real opener of `useFieldEditor` in this tree (this
    // file's own `openEditor`, `properties_tab.ts`'s
    // `onEditOwned`/`onEditPending`, `view_tab.ts`'s `editorProps`)
    // ever supplies one -- confirmed by grepping every real call
    // site, not an oversight here. A real, pre-existing gap against
    // `field_editor_fallback.ts`'s own `onKeydown`, which calls
    // `this.props.close()` unconditionally on Escape (so `props.close`
    // is genuinely `undefined` there today) -- flagged, not fixed,
    // per this migration's "type-adding pass, not a behavior change"
    // rule; see `sidebar/properties_tab.ts`'s own
    // `PropertiesEditorProps` for the fuller writeup.
    const props: Omit<FieldEditorProps, "close"> = {
      field: null,
      initial: {ttype, string: label},
      mode: this.model.pythonOwned ? "staged" : "live",
      fieldTypes: this.model.fieldTypes,
      existingNames: this.existingNames,
      // `ConsoleModel.modelName` is `string | false | undefined`
      // (the view may be model-less, or not yet answered) --
      // `console_model.ts`'s own `resolveRelated` already asserts
      // the same thing at the one point it is reached only once a
      // real model is in hand, which is equally true here: the
      // field editor is never opened before a model has loaded.
      modelName: this.model.modelName as string,
      inverseOptions: (comodel: string) => this.model.inverseOptions(comodel),
      resolveRelated: (path: string) => this.model.resolveRelated(path),
      // `onSave` is `(values) => void` on `FieldEditorProps` (Owl's
      // own `close: Function` schema doesn't await it either); the
      // real handler is async, so it is fired and not returned,
      // the same `void`-prefixed shape `apply_dialog.ts`'s own
      // `ConfirmationDialog` `confirm` callback already uses for an
      // identical async-handler-behind-a-void-prop situation.
      onSave: (values: Record<string, unknown>) => {
        void this.onEditorSave(values);
      },
      onDelete: null,
    };
    // `rootRef.el` is always populated by the time this runs: every
    // caller is a click handler or the mount-triggered `fieldTarget`
    // effect above, both reachable only after the first render.
    this.editor.open((anchor || this.rootRef.el) as HTMLElement, props);
  }

  /** Every name the model already has, so the editor picks another. */
  get existingNames(): string[] {
    const context = this.model.context;
    return (context?.fields ?? []).map((field) => field.name);
  }

  async onEditorSave(values: Record<string, unknown>): Promise<void> {
    this.editor.close();
    await this.finishField(values);
  }

  /** Send the field, then put the cursor where the next edit is. */
  async finishField(
    values: Record<string, unknown>
  ): Promise<
    (DropSuccessResult & {created_field: boolean; staged_field: boolean}) | undefined
  > {
    const result = await this.model.addNewField(values);
    if (result && result.created_field) {
      const el = this.rootRef.el;
      const root = el && el.closest<HTMLElement>(".o_builder_console");
      focusLabelRow(root || document.body);
    }
    return result;
  }

  async onExistingField(field: {name: string}): Promise<void> {
    if (!this.canAdd) {
      return;
    }
    await this.model.addExistingField(field.name);
  }
}
