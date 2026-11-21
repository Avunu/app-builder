/** @odoo-module **/
/**
 * The report canvas, on its own.
 *
 * What a tour cannot pin, because it only ever sees a report that renders
 * and a template nobody wrote a handler into: that the rendered document
 * is kept in a sandboxed frame -- its stylesheets and scripts never reach
 * the console's own page -- and that a template which does not render
 * still opens, says why, and can be tried again. The second is the state
 * a template is in halfway through an edit, which is when the editor is
 * needed.
 */

import {expect, test} from "@odoo/hoot";
import {click, queryAll, queryOne, select, waitFor} from "@odoo/hoot-dom";
import {animationFrame} from "@odoo/hoot-mock";
import {reactive} from "@odoo/owl";
import {makeServerError, mountWithCleanup, onRpc} from "@web/../tests/web_test_helpers";

import {defineMailModels} from "@mail/../tests/mail_test_helpers";

import type {ConsoleModel} from "@app_builder_view/console/console_model";
import {frameDocument, ReportCanvas} from "@app_builder_report/console/report_canvas";

// This addon depends on `mail` (through `app_builder_ui` and
// `base_automation`), so hoot loads mail's services with it, and they ask
// the mock server for models of their own as soon as an env exists.
defineMailModels();

/** A whole document, as `web.html_container` renders one: a stylesheet
 * that would hide the tools if it reached them, a script, and an inline
 * handler on the one value qweb branded. */
const REPORT = `<!DOCTYPE html>
<html>
  <head>
    <style>.o_builder_report_tools { display: none !important; }</style>
    <script>window.top.__app_builder_report_ran = true;</script>
  </head>
  <body>
    <p>Job Sheet for
      <span data-oe-expression="doc.name"
            onclick="window.top.__app_builder_report_ran = true">Azure</span>
    </p>
  </body>
</html>`;

const FRAME = "iframe.o_builder_report_frame";
/** The frame once its document has been prepared for picking: until
 * then a click in it is nobody's. */
const READY = `${FRAME}[data-ready]`;

interface Flags {
  __app_builder_report_ran?: boolean;
}

/** The slice of `ConsoleModel` the canvas reads, reactive so that a new
 * `archVersion` is seen the way the console's own is. */
function makeModel(): ConsoleModel {
  return reactive({
    viewId: 7,
    archVersion: "v1",
    busy: false,
    applyOperation: () => Promise.resolve(undefined),
  }) as unknown as ConsoleModel;
}

/** A model with a package to record into, whose `applyOperation` notes
 * what it was asked to do. */
function makeWritableModel(
  ops: Record<string, unknown>[],
  pkg: {writable: boolean; read_only_reason?: string} = {writable: true}
): ConsoleModel {
  return reactive({
    viewId: 7,
    archVersion: "v1",
    busy: false,
    packageId: 3,
    package: {id: 3, name: "x_pkg", ...pkg},
    applyOperation: (op: Record<string, unknown>) => {
      ops.push(op);
      return Promise.resolve({});
    },
  }) as unknown as ConsoleModel;
}

/** A key pressed on `el`, the way the browser sends it: bubbling, and
 * cancelable so the canvas can claim it. */
function keydown(el: Element, key: string): KeyboardEvent {
  const ev = new KeyboardEvent("keydown", {key, bubbles: true, cancelable: true});
  el.dispatchEvent(ev);
  return ev;
}

/** The three reads a load makes, `preview_html` as the test says. */
function serve(preview: () => unknown, removals: string[] = ["value"]): string[] {
  const calls: string[] = [];
  onRpc("preview_html", () => {
    calls.push("preview_html");
    return preview();
  });
  onRpc("body_anchor", () => ({
    found: true,
    xpath: "//main",
    position: "inside",
    model: "x.job",
  }));
  onRpc("printable_fields", ({args}) => {
    calls.push(`printable_fields ${String(args[0])}`);
    return {values: [{name: "name", string: "Name", type: "char"}], lists: []};
  });
  onRpc("locate_expression", ({args}) => {
    const expression = String(args[1]);
    calls.push(`locate ${expression}`);
    return {found: true, xpath: "//span[1]", expression, tag: "span", removals};
  });
  return calls;
}

test("the scripts are taken out of what the frame is given", () => {
  const html = frameDocument(REPORT);
  expect(html).not.toInclude("<script");
  expect(html).toInclude("data-oe-expression");
  expect(html).toInclude("<style>");
  expect(frameDocument("")).toBe("");
});

test("the report is shown in a sandboxed frame, and none of it reaches the page", async () => {
  const flags = window as unknown as Flags;
  delete flags.__app_builder_report_ran;
  const calls = serve(() => ({html: REPORT, reason: false, model: "x.job", res_id: 1}));
  await mountWithCleanup(ReportCanvas as never, {props: {model: makeModel()}});

  const frame = queryOne(FRAME);
  expect(frame).toHaveAttribute("sandbox", "allow-same-origin");
  // Nothing of the document is in the console's own DOM: its stylesheet
  // cannot restyle the tools, which are still on show.
  expect(queryAll(".o_builder_report_preview style")).toHaveLength(0);
  expect(queryAll(".o_builder_report_preview [data-oe-expression]")).toHaveLength(0);
  expect(".o_builder_report_tools").toBeVisible();

  // It is in the frame, where the value can be picked -- by key too.
  const value = await waitFor(`${READY}:iframe [data-oe-expression='doc.name']`);
  expect(value).toHaveAttribute("tabindex", "0");
  await click(value);
  await animationFrame();
  expect(calls).toEqual(["preview_html", "printable_fields x.job", "locate doc.name"]);
  expect(".o_builder_report_tools").toHaveText(/doc\.name/);
  expect(value).toHaveClass("o_builder_report_selected");
  // Neither the script nor the inline handler ran.
  expect(flags.__app_builder_report_ran).toBe(undefined);
});

test("a report that does not render opens anyway, says why, and can be retried", async () => {
  let broken = true;
  const calls = serve(() => {
    if (broken) {
      throw makeServerError({message: "t-field refers to a field that is gone"});
    }
    return {html: REPORT, reason: false, model: "x.job", res_id: 1};
  });
  // The mount itself is the first thing pinned: `onWillStart` must not
  // reject, or the report could not be opened to be fixed.
  await mountWithCleanup(ReportCanvas as never, {props: {model: makeModel()}});

  expect(".o_builder_report_error").toHaveText(/could not be rendered/);
  expect(".o_builder_report_error").toHaveText(
    /t-field refers to a field that is gone/
  );
  expect(queryAll(FRAME)).toHaveLength(0);
  // The tools are usable: where a value would go and what the model can
  // print were read without the render, so a field can be placed to fix
  // the template.
  expect("select[name='report_field'] option[value='name']").toHaveCount(1);
  await select("name", {target: "select[name='report_field']"});
  await animationFrame();
  expect("button[name='place_report_field']").toBeEnabled();

  broken = false;
  await click("button[name='retry_report_preview']");
  await waitFor(`${READY}:iframe [data-oe-expression='doc.name']`);
  expect(queryAll(".o_builder_report_error")).toHaveLength(0);
  expect(calls).toEqual([
    "preview_html",
    "printable_fields x.job",
    "preview_html",
    "printable_fields x.job",
  ]);
});

const VALUE = `${READY}:iframe [data-oe-expression='doc.name']`;
const RENDERED = {html: REPORT, reason: false, model: "x.job", res_id: 1};

test("a selected value is removed with its label, by its button or by Delete", async () => {
  const ops: Record<string, unknown>[] = [];
  serve(() => RENDERED, ["labelled"]);
  await mountWithCleanup(ReportCanvas as never, {
    props: {model: makeWritableModel(ops)},
  });
  // Nothing selected, nothing to remove.
  expect(queryAll(".o_builder_report_remove")).toHaveLength(0);

  await click(await waitFor(VALUE));
  await animationFrame();
  expect("button[name='remove_report_labelled']").toBeEnabled();
  expect("button[name='remove_report_labelled']").toHaveText("Remove value and label");
  await click("button[name='remove_report_labelled']");
  await animationFrame();
  expect(ops).toEqual([
    {type: "remove_report_element", xpath: "//span[1]", unit: "labelled"},
  ]);
  // What was selected is gone, and so is the selection.
  expect(queryAll(".o_builder_report_remove")).toHaveLength(0);

  // Delete, pressed on the value in the document, does the same.
  const value = await waitFor(VALUE);
  await click(value);
  await animationFrame();
  const ev = keydown(value, "Delete");
  await animationFrame();
  expect(ev.defaultPrevented).toBe(true);
  expect(ops).toHaveLength(2);
  expect(ops[1]).toEqual({
    type: "remove_report_element",
    xpath: "//span[1]",
    unit: "labelled",
  });
});

test("a table cell offers its column and its table", async () => {
  const ops: Record<string, unknown>[] = [];
  serve(() => RENDERED, ["column", "table"]);
  await mountWithCleanup(ReportCanvas as never, {
    props: {model: makeWritableModel(ops)},
  });
  await click(await waitFor(VALUE));
  await animationFrame();
  expect("button[name='remove_report_column']").toHaveText("Remove column");
  expect("button[name='remove_report_table']").toHaveText("Remove table");
  await click("button[name='remove_report_table']");
  await animationFrame();
  expect(ops).toEqual([
    {type: "remove_report_element", xpath: "//span[1]", unit: "table"},
  ]);
});

test("Backspace in the label being typed is typing, not a removal", async () => {
  const ops: Record<string, unknown>[] = [];
  serve(() => RENDERED);
  await mountWithCleanup(ReportCanvas as never, {
    props: {model: makeWritableModel(ops)},
  });
  await click(await waitFor(VALUE));
  await animationFrame();
  const ev = keydown(queryOne("input[name='report_label']"), "Backspace");
  await animationFrame();
  expect(ev.defaultPrevented).toBe(false);
  expect(ops).toEqual([]);
  // Pressed anywhere else in the tools, it removes.
  keydown(
    queryAll(".o_builder_report_tools .o_builder_section_title")[0]!,
    "Backspace"
  );
  await animationFrame();
  expect(ops).toEqual([
    {type: "remove_report_element", xpath: "//span[1]", unit: "value"},
  ]);
});

test("on a read-only package Remove is offered disabled, and says why", async () => {
  const ops: Record<string, unknown>[] = [];
  serve(() => RENDERED);
  await mountWithCleanup(ReportCanvas as never, {
    props: {
      model: makeWritableModel(ops, {
        writable: false,
        read_only_reason: "Writing source code has not been enabled on this server.",
      }),
    },
  });
  const value = await waitFor(VALUE);
  await click(value);
  await animationFrame();
  expect("button[name='remove_report_value']").not.toBeEnabled();
  expect(".o_builder_report_remove_blocked").toHaveText(
    "Writing source code has not been enabled on this server."
  );
  keydown(value, "Delete");
  await animationFrame();
  expect(ops).toEqual([]);
});

test("with no package chosen Remove is disabled, and says so", async () => {
  serve(() => RENDERED);
  await mountWithCleanup(ReportCanvas as never, {props: {model: makeModel()}});
  await click(await waitFor(VALUE));
  await animationFrame();
  expect("button[name='remove_report_value']").not.toBeEnabled();
  expect(".o_builder_report_remove_blocked").toHaveText(/Choose a package/);
});
