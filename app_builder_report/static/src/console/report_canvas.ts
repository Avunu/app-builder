/** @odoo-module **/
/**
 * A report, previewed as the document it prints.
 *
 * A report template is a qweb view, and the web client has no qweb view
 * type to render it with; so the canvas is the report's own output,
 * rendered server-side with branding on, so the values it prints can be
 * clicked. Community brands `t-field` and nothing else, which is honest: a
 * value is a node the builder put there, the prose around it is not.
 *
 * The locators here are the one exception to "the browser never holds an
 * xpath": a rendered document carries no tokens, so `locate_expression`
 * and `body_anchor` answer with the locator, minted on the server against
 * the combined arch as everywhere else, and it is relayed as it came.
 *
 * This lives in the report addon and reaches the console through the
 * `app_builder.canvas` registry, under the `editable_as` the server answers
 * for a qweb view: the console renders whatever that registry maps
 * "report" to, and never imports this file. The `model` prop is the
 * console's `ConsoleModel`; `viewId`, `archVersion`, `busy` and
 * `applyOperation` are all that is read of it.
 */

import {Component, markup, onWillStart, useEffect, useRef, useState} from "@odoo/owl";
import {registry} from "@web/core/registry";
import {useService} from "@app_builder_view/console/odoo";
import type {ConsoleModel} from "@app_builder_view/console/console_model";
import type {OrmService} from "@app_builder_view/console/types";

/**
 * `preview_html`'s own two shapes (`builder_report_preview.py:preview_html`):
 * nothing to render (`html`/`reason`/`model` only, `res_id` absent -- no
 * record for this model yet, or no model at all) or a real render (`html`
 * the rendered document, `reason` the Python literal `False`, `res_id`
 * present). `model`/`reason` are `string | false` either way -- traced to
 * the real construction, not guessed: `model_name` is `report.model or
 * view.model`, both plain `Char` fields, and `reason` is `False` on the
 * success branch, a translated string otherwise.
 */
interface ReportPreviewResult {
  html: string;
  reason: string | false;
  model: string | false;
  res_id?: number;
}

/**
 * `printable_fields`'s own per-field entry (`builder_report_preview.py`):
 * a `values` row prints as a `t-field`, a `lists` row -- with its own
 * `columns`, the sub-model's own printable fields -- prints as a table.
 */
interface PrintableFieldEntry {
  name: string;
  string: string;
  type: string;
}

interface PrintableColumnEntry {
  name: string;
  string: string;
}

interface PrintableListEntry extends PrintableFieldEntry {
  columns: PrintableColumnEntry[];
}

interface PrintableFieldsResult {
  values: PrintableFieldEntry[];
  lists: PrintableListEntry[];
}

/** `locate_expression`'s own two shapes (`builder_report_preview.py`): the
 * arch node printing `expression`, as a locator, or why none was found. */
type LocateExpressionResult =
  | {found: true; xpath: string; expression: string; tag: string}
  | {found: false; reason: string};

/** `body_anchor`'s own found shape (`builder_report_preview.py`) -- always
 * `"inside"`, the one position every one of its three tried expressions
 * answers with. */
interface FoundBodyAnchor {
  found: true;
  xpath: string;
  position: "inside";
}

type BodyAnchorResult = FoundBodyAnchor | {found: false; reason: string};

/**
 * `state.report`, built up by `loadReport` from the three RPCs above and
 * held across edits so a re-select (after something moved) can read it
 * back. `values`/`lists` are the one part `setup()`'s own initial literal
 * below does not set -- `onWillStart` always fills them in before the
 * first render, but nothing makes that visible to the type checker, so
 * they stay optional here rather than asserted, the same way every real
 * reader (`columnChoices`, the template's own `t-foreach`) already reads
 * them defensively.
 */
interface ReportPreviewState {
  html: string | ReturnType<typeof markup>;
  reason: string | false;
  model: string;
  anchor: FoundBodyAnchor | null;
  anchorReason: string;
  values?: PrintableFieldEntry[];
  lists?: PrintableListEntry[];
}

/**
 * What was last clicked (or re-resolved after an edit moved it) --
 * `select`'s own `{ kind: "report_field", expression, ...found }` spread,
 * `found` being `LocateExpressionResult` above (its own `expression`, on
 * the found branch, is the same value spread back in, not a second one).
 */
type ReportTarget =
  | {kind: "report_field"; expression: string; found: true; xpath: string; tag: string}
  | {kind: "report_field"; expression: string; found: false; reason: string};

interface ReportCanvasState {
  report: ReportPreviewState;
  target: ReportTarget | null;
  message: string;
  field: string;
  label: string;
  list: string;
  columns: string[];
}

/** The one prop the Views pane's `app_builder.canvas` registry ever hands
 * a registrant (`panes/views_pane.ts`'s own `BuilderCanvasProps`-shaped
 * `canvasProps`, TYPING.md's own note 8): `model`, the console's
 * `ConsoleModel`. `onRemove` -- the other half of that shared shape -- is
 * only ever set when the resolved component is `BuilderCanvas` itself
 * (`views_pane.ts`'s own `canvasProps` getter), never for this one, so it
 * is left off this file's own `Props` rather than declared and ignored. */
interface Props {
  model: ConsoleModel;
}

export class ReportCanvas extends Component<Props> {
  // Both need `override`: Owl's own `Component` base class declares
  // `static template`/`static props` by name directly on the class body
  // (TYPING.md's "Known traps" -- confirmed against
  // `component.d.ts`, not assumed from `template`'s own optionality).
  static override template = "app_builder_report.ReportCanvas";
  static override props = {model: Object};

  /**
   * `model` through `state` are all assigned unconditionally in
   * `setup()`, called synchronously right after construction and
   * before the first render -- `strictPropertyInitialization` only
   * ever inspects a real constructor, so it cannot see that, and each
   * carries the definite-assignment `!` to say so anyway (TYPING.md's
   * "Known traps"). `loadedVersion` is the one exception: it is first
   * assigned inside `loadReport()`, not `setup()` itself, so it is
   * typed `| undefined` instead, no assertion -- that genuinely is its
   * state before the first load completes.
   */
  model!: ConsoleModel;
  orm!: OrmService;
  previewRef!: {el: HTMLElement | null};
  state!: ReportCanvasState;
  loadedVersion: string | null | undefined;

  override setup(): void {
    this.model = useState(this.props.model);
    this.orm = useService("orm");
    this.previewRef = useRef("preview");
    this.state = useState<ReportCanvasState>({
      report: {html: "", reason: "", model: "", anchor: null, anchorReason: ""},
      target: null,
      message: "",
      field: "",
      label: "",
      list: "",
      columns: [],
    });
    onWillStart(() => this.loadReport());
    useEffect(
      (version: string | null) => {
        if (version && this.loadedVersion && version !== this.loadedVersion) {
          void this.loadReport();
        }
      },
      () => [this.model.archVersion]
    );
    useEffect(
      (el: HTMLElement | null) => {
        if (!el) {
          return;
        }
        const onClick = (ev: MouseEvent): void => {
          void this.onClick(ev);
        };
        el.addEventListener("click", onClick, true);
        return () => el.removeEventListener("click", onClick, true);
      },
      () => [this.previewRef.el]
    );
  }

  async loadReport(): Promise<void> {
    const viewId = this.model.viewId;
    const [preview, anchor] = await Promise.all([
      this.orm.call<ReportPreviewResult>("builder.report", "preview_html", [viewId]),
      this.orm.call<BodyAnchorResult>("builder.report", "body_anchor", [viewId]),
    ]);
    const printable = await this.orm.call<PrintableFieldsResult>(
      "builder.report",
      "printable_fields",
      [preview.model || false]
    );
    Object.assign(this.state.report, {
      html: markup(preview.html || ""),
      reason: preview.reason || "",
      model: preview.model || "",
      anchor: anchor.found ? anchor : null,
      anchorReason: anchor.found ? "" : anchor.reason,
      values: printable.values,
      lists: printable.lists,
    });
    this.loadedVersion = this.model.archVersion;
    // A selection is an expression, and its locator can move when
    // something is inserted above it: re-resolve rather than trust it.
    if (this.state.target && this.state.target.expression) {
      await this.select(this.state.target.expression);
    }
  }

  /**
   * A click in the rendered document, resolved through what qweb branded.
   */
  async onClick(ev: MouseEvent): Promise<void> {
    ev.preventDefault();
    ev.stopPropagation();
    // `ev.target` is `EventTarget | null` -- only `Element` has
    // `.closest`, which is what the original's own `target.closest &&
    // ...` duck check was really testing. Same narrowing `canvas.ts`'s
    // own `onClick` already established (TYPING.md's "Known traps").
    const target = ev.target instanceof Element ? ev.target : null;
    const node = target ? target.closest("[data-oe-expression]") : null;
    if (!node) {
      this.state.target = null;
      this.state.message = this.state.report.anchor
        ? ""
        : this.state.report.anchorReason;
      return;
    }
    // `node` matched the `[data-oe-expression]` selector, so the
    // attribute is present by construction -- a type-level cast, not
    // a runtime fallback, the same "trust the invariant that put the
    // node here" reasoning `canvas.ts`'s own `computeViewProps` casts
    // already document for a payload the server is trusted to have
    // shaped a given way.
    await this.select(node.getAttribute("data-oe-expression") as string);
  }

  async select(expression: string): Promise<void> {
    const found = await this.orm.call<LocateExpressionResult>(
      "builder.report",
      "locate_expression",
      [this.model.viewId, expression]
    );
    this.state.target = {kind: "report_field", expression, ...found};
    this.state.message = found.found ? "" : found.reason;
  }

  get columnChoices(): PrintableColumnEntry[] {
    const chosen = (this.state.report.lists || []).find(
      (e) => e.name === this.state.list
    );
    return chosen ? chosen.columns : [];
  }

  /**
   * Where an edit lands: beside the value that was clicked, or in the body.
   *
   * The two are different positions, not just different paths. Placing a
   * value while one is selected means "next to this one"; placing with
   * nothing selected means "in the document", and inside the page
   * container is the only answer that does not depend on what the
   * template happens to contain.
   */
  get target(): {xpath: string; position: "after" | "inside"} | null {
    if (this.state.target && this.state.target.found) {
      return {xpath: this.state.target.xpath, position: "after"};
    }
    const anchor = this.state.report.anchor;
    return anchor ? {xpath: anchor.xpath, position: anchor.position} : null;
  }

  async placeField(): Promise<void> {
    const target = this.target;
    if (!this.state.field || !target) {
      return;
    }
    const result = await this.model.applyOperation({
      type: "add_report_field",
      xpath: target.xpath,
      position: target.position,
      model: this.state.report.model,
      name: this.state.field,
      label: this.state.label || false,
    });
    if (result !== undefined) {
      this.state.label = "";
    }
  }

  async placeTable(): Promise<void> {
    const target = this.target;
    if (!this.state.list || !this.state.columns.length || !target) {
      return;
    }
    const result = await this.model.applyOperation({
      type: "add_report_table",
      xpath: target.xpath,
      position: target.position,
      model: this.state.report.model,
      name: this.state.list,
      columns: [...this.state.columns],
    });
    if (result !== undefined) {
      this.state.columns = [];
    }
  }

  /** Another list to print: the columns picked for the last one go. */
  onListChange(ev: Event): void {
    // The template's own `t-on-change` fires only on this file's own
    // `<select name="report_list">` -- the same "cast, not narrow"
    // idiom `search_lists_canvas.ts`'s own `onAddSearchField`/
    // `onAddGroupBy` already use for an identical change handler.
    this.state.list = (ev.target as HTMLSelectElement).value;
    this.state.columns = [];
  }

  toggleColumn(name: string): void {
    const chosen = this.state.columns;
    const at = chosen.indexOf(name);
    if (at === -1) {
      chosen.push(name);
    } else {
      chosen.splice(at, 1);
    }
  }
}

registry.category("app_builder.canvas").add("report", ReportCanvas);
