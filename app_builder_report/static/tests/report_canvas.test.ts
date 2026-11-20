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

/** The three reads a load makes, `preview_html` as the test says. */
function serve(preview: () => unknown): string[] {
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
    return {found: true, xpath: "//span[1]", expression, tag: "span"};
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
