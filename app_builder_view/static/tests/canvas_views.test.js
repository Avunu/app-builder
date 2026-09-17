import { after, expect, test } from "@odoo/hoot";
import { unload } from "@odoo/hoot-dom";
import { animationFrame, mockSendBeacon } from "@odoo/hoot-mock";
import {
  defineModels,
  fields,
  findComponent,
  hideTab,
  makeMockEnv,
  MockServer,
  models,
  mountWithCleanup,
  onRpc
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";
import { View } from "@web/views/view";
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";
import { ListRenderer } from "@web/views/list/list_renderer";
import { CANVAS_PREFIX, canvasJsClass } from "@app_builder_view/console/canvas_views";
import * as compat from "@app_builder_view/console/compat";
class Partner extends models.Model {
  // `mock_fields.js`'s `makeFieldGenerator` self-indexes its return value
  // with a non-literal key, so every generator (`Char`, `Integer`, ...)
  // reads back as `(...) => FieldDefinition | undefined` under
  // `noUncheckedIndexedAccess` even though it always exists at runtime.
  name = fields.Char();
  sequence = fields.Integer();
  // One record, so a list has a row to drag and a kanban a card; the form
  // tests open a *new* record and never read it.
  // `Model` already declares `_records` (typed `Partial<ModelRecord>[]`),
  // so `noImplicitOverride` requires the keyword here even though this is
  // ordinary per-model data, not a real override of any behaviour.
  _records = [{ id: 1, name: "Ada", sequence: 1 }];
}
defineModels([Partner]);
onRpc("has_group", () => true);
function recordRpcs() {
  onRpc(({ method }) => {
    if (method !== "has_group") {
      expect.step(method);
    }
  });
}
async function mountCanvasView(type, arch, extra = {}) {
  await makeMockEnv();
  const modelFields = MockServer.env["partner"].fields_get();
  const props = {
    type,
    resModel: "partner",
    arch,
    fields: modelFields,
    relatedModels: { partner: { fields: modelFields } },
    context: {},
    noBreadcrumbs: true,
    display: type === "form" ? { controlPanel: {} } : { controlPanel: false },
    ...extra
  };
  return mountWithCleanup(View, { props });
}
const FORM_ARCH = `<form><sheet><group><field name="name"/></group></sheet></form>`;
test("premise: the stock form creates a record when the tab is hidden", async () => {
  recordRpcs();
  await mountCanvasView("form", FORM_ARCH, { resId: false });
  expect.verifySteps(["onchange"]);
  await hideTab();
  await animationFrame();
  expect.verifySteps(["web_save"]);
});
test("the canvas form neither saves on a hidden tab nor on unload", async () => {
  mockSendBeacon(() => {
    expect.step("sendBeacon");
    return true;
  });
  recordRpcs();
  const jsClass = canvasJsClass("form");
  expect(jsClass).toBe(CANVAS_PREFIX + "form");
  await mountCanvasView("form", FORM_ARCH, { resId: false, jsClass });
  expect.verifySteps(["onchange"]);
  expect(".o_form_view .o_field_widget[name='name']").toHaveCount(1);
  await hideTab();
  await animationFrame();
  await unload();
  await animationFrame();
  expect.verifySteps([]);
});
test("no get_views is made when arch, fields and relatedModels are given", async () => {
  recordRpcs();
  await mountCanvasView("form", FORM_ARCH, {
    resId: 1,
    jsClass: canvasJsClass("form"),
    ...compat.readonlyViewProps()
  });
  expect.verifySteps(["web_read"]);
  expect(".o_field_widget[name='name']").toHaveText("Ada");
});
test("the canvas list cannot resequence its rows", async () => {
  const arch = `<list><field name="sequence" widget="handle"/><field name="name"/></list>`;
  const view = await mountCanvasView("list", arch, { jsClass: canvasJsClass("list") });
  const renderer = findComponent(view, (c) => c instanceof ListRenderer);
  expect(renderer).not.toBe(null);
  expect(renderer.canResequenceRows).toBe(false);
  expect(".o_list_view .o_data_row").toHaveCount(1);
});
test("the canvas kanban cannot resequence its records or groups", async () => {
  const arch = `
        <kanban default_group_by="name" records_draggable="1" groups_draggable="1">
            <templates><t t-name="card"><field name="name"/></t></templates>
        </kanban>`;
  const view = await mountCanvasView("kanban", arch, { jsClass: canvasJsClass("kanban") });
  const renderer = findComponent(
    view,
    (c) => c instanceof KanbanRenderer
  );
  expect(renderer).not.toBe(null);
  expect(renderer.canResequenceRecords).toBe(false);
  expect(renderer.canResequenceGroups).toBe(false);
  expect(".o_kanban_view .o_kanban_record:not(.o_kanban_ghost)").toHaveCount(1);
});
test("the derived class wraps the view's own js_class when it has one", async () => {
  const viewRegistry = registry.category("views");
  const registryGet = (key) => viewRegistry.get.call(viewRegistry, key);
  const own = { ...registryGet("form") };
  viewRegistry.add("app_builder_test_form", own, { force: true });
  after(() => {
    viewRegistry.remove("app_builder_test_form");
    viewRegistry.remove(CANVAS_PREFIX + "app_builder_test_form");
  });
  expect(canvasJsClass("form", "app_builder_test_form")).toBe(
    CANVAS_PREFIX + "app_builder_test_form"
  );
  const derived = registryGet(CANVAS_PREFIX + "app_builder_test_form");
  expect(Object.getPrototypeOf(derived.Controller)).toBe(own.Controller);
  expect(canvasJsClass("form", "no_such_class")).toBe(CANVAS_PREFIX + "form");
  expect(canvasJsClass("no_such_type")).toBe(null);
});
