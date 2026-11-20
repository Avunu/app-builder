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
 * That output is a whole document -- a generated report calls
 * `web.html_container`, so it comes with its own `<head>`, stylesheets
 * and scripts -- and it is shown in an `<iframe srcdoc>`, never inserted
 * into the console's own DOM: there its stylesheets would restyle the
 * builder and the web client around it, and an inline handler in an
 * edited template would run as the backend page. The frame is sandboxed
 * with `allow-same-origin` and nothing else, which runs no script in it
 * and still lets this component reach its document to hear the clicks.
 *
 * A template that does not render is the state the editor most needs to
 * survive: it is what a template looks like halfway through an edit. So
 * no load here can reject the component's start; a failure is said in
 * the preview's place, with a way to try again, and the tools stay up.
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

import {Component, onWillStart, status, useEffect, useRef, useState} from "@odoo/owl";
import {registry} from "@web/core/registry";
import {_t} from "@app_builder_view/console/l10n";
import {useService} from "@app_builder_view/console/odoo";
import {messageOf} from "@app_builder_view/console/shell/draft_model";
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
  /** The rendered document, as the frame's `srcdoc`. */
  html: string;
  reason: string | false;
  /** Why the report could not be loaded or rendered, when it could not:
   * shown in the preview's place, with Retry. */
  error: string;
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

/** What the frame's own document is given on top of the report's: the
 * values that can be picked look and behave as such, and the one picked
 * shows. Scoped to the frame by being in it. */
const FRAME_STYLE = `
[data-oe-expression] { cursor: pointer; }
[data-oe-expression]:hover,
[data-oe-expression]:focus { outline: 1px dashed #714b67; outline-offset: 1px; }
[data-oe-expression].o_builder_report_selected { outline: 2px solid #714b67; outline-offset: 1px; }
`;

/**
 * The rendered report, made fit for the frame: its scripts are taken out.
 * The sandbox would not run them anyway; removed, the browser does not
 * log a refusal for each, and nothing depends on the sandbox alone.
 */
export function frameDocument(html: string): string {
  if (!html) {
    return "";
  }
  const doc = new DOMParser().parseFromString(html, "text/html");
  for (const script of [...doc.querySelectorAll("script")]) {
    script.remove();
  }
  return `<!DOCTYPE html>${doc.documentElement.outerHTML}`;
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
  frameRef!: {el: HTMLIFrameElement | null};
  state!: ReportCanvasState;
  loadedVersion: string | null | undefined;
  /** Counts the loads started: an answer that is not the last one's is
   * for a document no longer wanted, and is dropped. */
  loadSerial = 0;
  /** The documents `prepareFrame` has already been through. */
  prepared = new WeakSet<Document>();
  /** The document the frame held when `srcdoc` last changed. */
  outgoing: Document | null = null;

  override setup(): void {
    this.model = useState(this.props.model);
    this.orm = useService("orm");
    this.frameRef = useRef<HTMLIFrameElement>("frame");
    this.state = useState<ReportCanvasState>({
      report: {
        html: "",
        reason: "",
        error: "",
        model: "",
        anchor: null,
        anchorReason: "",
      },
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
    // Another document in the frame: it is not ready until prepared.
    useEffect(
      (_html: string, frame: HTMLIFrameElement | null) => {
        if (frame) {
          // The document on show until the new one replaces it: still
          // there for a moment, already prepared, and not the one
          // being waited for.
          this.outgoing = this.frameDoc;
          frame.removeAttribute("data-ready");
          this.watchFrame();
        }
      },
      () => [this.state.report.html, this.frameRef.el]
    );
    // The selection, shown on the document: after a pick, and again
    // whenever the frame holds a new one (`prepareFrame`).
    useEffect(
      () => this.markSelection(),
      () => [this.state.target && this.state.target.expression]
    );
  }

  /** Whether this component is still the one on screen. */
  get alive(): boolean {
    return status(this) !== "destroyed";
  }

  /**
   * Read the report again: what it renders to, where a value goes when
   * nothing is selected, and what the model can print.
   *
   * Never rejects. Each of the three answers is taken on its own: a
   * template that does not render still has an arch to place a value in
   * and a model with fields, so the tools keep what could be read and the
   * preview says what could not. An answer that arrives after a newer
   * load has started, or after the canvas has gone, is dropped.
   */
  async loadReport(): Promise<void> {
    const serial = ++this.loadSerial;
    const viewId = this.model.viewId;
    const version = this.model.archVersion;
    const current = (): boolean => this.alive && serial === this.loadSerial;
    const [preview, anchor] = await Promise.allSettled([
      this.orm.call<ReportPreviewResult>("builder.report", "preview_html", [viewId]),
      this.orm.call<BodyAnchorResult>("builder.report", "body_anchor", [viewId]),
    ]);
    if (!current()) {
      return;
    }
    const report = this.state.report;
    if (preview.status === "fulfilled") {
      report.html = frameDocument(preview.value.html || "");
      report.reason = preview.value.reason || "";
      report.model = preview.value.model || report.model;
      report.error = "";
    } else {
      // The document from before is not kept on show: it is not what
      // the template now says.
      report.html = "";
      report.reason = "";
      report.error = messageOf(preview.reason);
    }
    if (anchor.status === "fulfilled") {
      report.anchor = anchor.value.found ? anchor.value : null;
      report.anchorReason = anchor.value.found ? "" : anchor.value.reason;
    } else {
      report.anchor = null;
      report.anchorReason = messageOf(anchor.reason);
    }
    // The version this answer is for, whether or not it rendered: a
    // failure is not asked for again until something changes, or Retry.
    this.loadedVersion = version;
    if (preview.status === "fulfilled") {
      try {
        const printable = await this.orm.call<PrintableFieldsResult>(
          "builder.report",
          "printable_fields",
          [preview.value.model || false]
        );
        if (!current()) {
          return;
        }
        report.values = printable.values;
        report.lists = printable.lists;
      } catch (err) {
        if (!current()) {
          return;
        }
        this.state.message = messageOf(err);
      }
    }
    // A selection is an expression, and its locator can move when
    // something is inserted above it: re-resolve rather than trust it.
    if (this.state.target && this.state.target.expression) {
      await this.select(this.state.target.expression);
    }
  }

  /** Retry, from the preview's own error. */
  retry(): void {
    void this.loadReport();
  }

  // -- the frame --------------------------------------------------------------

  /** The frame's document, once it has one. */
  get frameDoc(): Document | null {
    const frame = this.frameRef.el;
    try {
      return frame ? frame.contentDocument : null;
    } catch {
      return null;
    }
  }

  /**
   * The frame is showing another document, or is about to: make it ready
   * as soon as it can be, without waiting for `load`.
   *
   * `load` fires once every stylesheet and image of the report has
   * arrived, which can be a while; until the document is prepared a click
   * in it selects nothing, and a click on a link would be followed. So
   * the document is looked for on each frame from the moment `srcdoc`
   * changes, and prepared the moment it has been parsed. `load` still
   * calls `prepareFrame` (the template), for a document slower than the
   * watch is patient.
   */
  watchFrame(tries = 180): void {
    if (!this.alive || this.prepareFrame() || tries <= 0) {
      return;
    }
    requestAnimationFrame(() => this.watchFrame(tries - 1));
  }

  /**
   * Prepare the document the frame holds, once: the listeners (each
   * document is a new `Document`, and the old ones went with the old
   * one), the picking style, and every value that can be picked made
   * reachable by Tab. Answers whether the frame's document is ready --
   * `false` while it is still the empty one a frame starts with, or still
   * being parsed.
   *
   * `data-ready` on the frame says so to whoever cannot ask: a tour, a
   * test. It is taken off when `srcdoc` changes (`setup`'s effect).
   */
  prepareFrame(): boolean {
    const frame = this.frameRef.el;
    const doc = this.frameDoc;
    if (!frame || !doc || !doc.body || doc.readyState === "loading") {
      return false;
    }
    if (doc.URL !== "about:srcdoc" || doc === this.outgoing) {
      // The blank document every frame has before its own, or the one
      // `srcdoc` has just been changed away from.
      return false;
    }
    if (this.prepared.has(doc)) {
      return true;
    }
    this.prepared.add(doc);
    this.outgoing = null;
    const style = doc.createElement("style");
    style.textContent = FRAME_STYLE;
    (doc.head || doc.body).appendChild(style);
    for (const node of doc.querySelectorAll("[data-oe-expression]")) {
      node.setAttribute("tabindex", "0");
      node.setAttribute("role", "button");
    }
    doc.addEventListener("click", (ev) => void this.onClick(ev), true);
    doc.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        void this.onClick(ev);
      }
    });
    this.markSelection();
    frame.setAttribute("data-ready", "1");
    return true;
  }

  /** Show the selection on the document the frame holds. */
  markSelection(): void {
    const doc = this.frameDoc;
    if (!doc) {
      return;
    }
    const expression = this.state.target ? this.state.target.expression : "";
    for (const node of doc.querySelectorAll("[data-oe-expression]")) {
      node.classList.toggle(
        "o_builder_report_selected",
        Boolean(expression) && node.getAttribute("data-oe-expression") === expression
      );
    }
  }

  /**
   * A click -- or Enter, or Space -- in the rendered document, resolved
   * through what qweb branded. Nothing in the document does what it would
   * on paper: a link is not followed, a form not sent.
   */
  async onClick(ev: Event): Promise<void> {
    // The target is an element of the frame's own document, whose
    // `Element` is not this window's: `instanceof Element` is false for
    // every node in there, so the method is asked for instead.
    const target = ev.target as Partial<Element> | null;
    const node =
      target && typeof target.closest === "function"
        ? target.closest("[data-oe-expression]")
        : null;
    if (ev.type === "keydown" && !node) {
      // A key pressed on nothing that can be picked is the document's.
      return;
    }
    ev.preventDefault();
    ev.stopPropagation();
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
    let found: LocateExpressionResult;
    try {
      found = await this.orm.call<LocateExpressionResult>(
        "builder.report",
        "locate_expression",
        [this.model.viewId, expression]
      );
    } catch (err) {
      if (this.alive) {
        this.state.target = null;
        this.state.message = messageOf(err);
      }
      return;
    }
    if (!this.alive) {
      return;
    }
    this.state.target = {kind: "report_field", expression, ...found};
    this.state.message = found.found ? "" : found.reason;
  }

  get frameTitle(): string {
    return String(_t("Report preview"));
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
