import { Component, markup, onWillStart, useEffect, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@app_builder_view/console/odoo";
class ReportCanvas extends Component {
  // Both need `override`: Owl's own `Component` base class declares
  // `static template`/`static props` by name directly on the class body
  // (TYPING.md's "Known traps" -- confirmed against
  // `component.d.ts`, not assumed from `template`'s own optionality).
  static template = "app_builder_report.ReportCanvas";
  static props = { model: Object };
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
  model;
  orm;
  previewRef;
  state;
  loadedVersion;
  setup() {
    this.model = useState(this.props.model);
    this.orm = useService("orm");
    this.previewRef = useRef("preview");
    this.state = useState({
      report: { html: "", reason: "", model: "", anchor: null, anchorReason: "" },
      target: null,
      message: "",
      field: "",
      label: "",
      list: "",
      columns: []
    });
    onWillStart(() => this.loadReport());
    useEffect(
      (version) => {
        if (version && this.loadedVersion && version !== this.loadedVersion) {
          void this.loadReport();
        }
      },
      () => [this.model.archVersion]
    );
    useEffect(
      (el) => {
        if (!el) {
          return;
        }
        const onClick = (ev) => {
          void this.onClick(ev);
        };
        el.addEventListener("click", onClick, true);
        return () => el.removeEventListener("click", onClick, true);
      },
      () => [this.previewRef.el]
    );
  }
  async loadReport() {
    const viewId = this.model.viewId;
    const [preview, anchor] = await Promise.all([
      this.orm.call("studio.report", "preview_html", [viewId]),
      this.orm.call("studio.report", "body_anchor", [viewId])
    ]);
    const printable = await this.orm.call(
      "studio.report",
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
      lists: printable.lists
    });
    this.loadedVersion = this.model.archVersion;
    if (this.state.target && this.state.target.expression) {
      await this.select(this.state.target.expression);
    }
  }
  /**
   * A click in the rendered document, resolved through what qweb branded.
   */
  async onClick(ev) {
    ev.preventDefault();
    ev.stopPropagation();
    const target = ev.target instanceof Element ? ev.target : null;
    const node = target ? target.closest("[data-oe-expression]") : null;
    if (!node) {
      this.state.target = null;
      this.state.message = this.state.report.anchor ? "" : this.state.report.anchorReason;
      return;
    }
    await this.select(node.getAttribute("data-oe-expression"));
  }
  async select(expression) {
    const found = await this.orm.call(
      "studio.report",
      "locate_expression",
      [this.model.viewId, expression]
    );
    this.state.target = { kind: "report_field", expression, ...found };
    this.state.message = found.found ? "" : found.reason;
  }
  get columnChoices() {
    const chosen = (this.state.report.lists || []).find((e) => e.name === this.state.list);
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
  get target() {
    if (this.state.target && this.state.target.found) {
      return { xpath: this.state.target.xpath, position: "after" };
    }
    const anchor = this.state.report.anchor;
    return anchor ? { xpath: anchor.xpath, position: anchor.position } : null;
  }
  async placeField() {
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
      label: this.state.label || false
    });
    if (result !== void 0) {
      this.state.label = "";
    }
  }
  async placeTable() {
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
      columns: [...this.state.columns]
    });
    if (result !== void 0) {
      this.state.columns = [];
    }
  }
  /** Another list to print: the columns picked for the last one go. */
  onListChange(ev) {
    this.state.list = ev.target.value;
    this.state.columns = [];
  }
  toggleColumn(name) {
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
export {
  ReportCanvas
};
