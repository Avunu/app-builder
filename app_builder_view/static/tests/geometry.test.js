import { expect, getFixture, test } from "@odoo/hoot";
import { queryAll, queryFirst, queryOne } from "@odoo/hoot-dom";
import {
  defineModels,
  fields,
  getMockEnv,
  makeMockEnv,
  MockServer,
  models,
  mountWithCleanup,
  onRpc
} from "@web/../tests/web_test_helpers";
import { View } from "@web/views/view";
import * as compat from "@app_builder_view/console/compat";
import {
  childEntries,
  contains,
  contentElement,
  contentRect,
  instanceOf,
  isActivePage,
  outlineRect,
  tabsOf,
  toContent
} from "@app_builder_view/console/geometry";
const findFirst = queryFirst;
class Partner extends models.Model {
  // `mock_fields.js`'s `makeFieldGenerator` self-indexes its return value
  // with a non-literal key, so every generator (`Char`, `Integer`, ...)
  // reads back as `(...) => FieldDefinition | undefined` under
  // `noUncheckedIndexedAccess` even though it always exists at runtime.
  name = fields.Char();
  city = fields.Char();
  sequence = fields.Integer();
  _records = [{ id: 1, name: "Ada", city: "London", sequence: 1 }];
}
defineModels([Partner]);
onRpc("has_group", () => true);
const ARCH = `
    <form class="o_studio_n_0">
        <sheet class="o_studio_n_1">
            <group class="o_studio_n_2">
                <group class="o_studio_n_3">
                    <field name="name" class="o_studio_n_4"/>
                    <field name="city" class="o_studio_n_5"/>
                </group>
                <group class="o_studio_n_6"/>
            </group>
            <notebook class="o_studio_n_7">
                <page name="one" string="One" class="o_studio_n_8">
                    <field name="sequence" class="o_studio_n_9"/>
                </page>
                <page name="two" string="Two" class="o_studio_n_10">
                    <group class="o_studio_n_11"/>
                </page>
            </notebook>
        </sheet>
    </form>`;
function node(kind, name, parent, children, extra = {}) {
  return {
    kind,
    name,
    parent,
    children,
    container: !["field"].includes(kind),
    ...extra
  };
}
const NODES = {
  o_studio_n_0: node("root", null, null, ["o_studio_n_1"]),
  o_studio_n_1: node("sheet", null, "o_studio_n_0", ["o_studio_n_2", "o_studio_n_7"]),
  o_studio_n_2: node("group", null, "o_studio_n_1", ["o_studio_n_3", "o_studio_n_6"], {
    orientation: "row"
  }),
  o_studio_n_3: node("group", null, "o_studio_n_2", ["o_studio_n_4", "o_studio_n_5"]),
  o_studio_n_4: node("field", "name", "o_studio_n_3", []),
  o_studio_n_5: node("field", "city", "o_studio_n_3", []),
  o_studio_n_6: node("group", null, "o_studio_n_2", []),
  o_studio_n_7: node("notebook", null, "o_studio_n_1", ["o_studio_n_8", "o_studio_n_10"]),
  o_studio_n_8: node("page", "one", "o_studio_n_7", ["o_studio_n_9"]),
  o_studio_n_9: node("field", "sequence", "o_studio_n_8", []),
  o_studio_n_10: node("page", "two", "o_studio_n_7", ["o_studio_n_11"]),
  o_studio_n_11: node("group", null, "o_studio_n_10", [])
};
async function mountForm() {
  if (!getMockEnv()) {
    await makeMockEnv();
  }
  const modelFields = MockServer.env.partner.fields_get();
  await mountWithCleanup(View, {
    props: {
      type: "form",
      resModel: "partner",
      arch: ARCH,
      fields: modelFields,
      relatedModels: { partner: { fields: modelFields } },
      context: {},
      noBreadcrumbs: true,
      display: { controlPanel: false },
      resId: 1,
      ...compat.readonlyViewProps()
    }
  });
  return queryOne(".o_form_view");
}
test("a container's content is where its children are drawn", async () => {
  const root = await mountForm();
  expect(contentElement("o_studio_n_1", root, NODES)).toBe(queryOne(".o_form_sheet"));
  expect(contentElement("o_studio_n_7", root, NODES)).toBe(queryOne(".o_notebook_headers"));
  expect(contentElement("o_studio_n_8", root, NODES)).toBe(queryOne(".o_notebook .tab-pane"));
  expect(contentElement("o_studio_n_10", root, NODES)).toBe(null);
  expect(isActivePage("o_studio_n_8", root, NODES)).toBe(true);
  expect(isActivePage("o_studio_n_10", root, NODES)).toBe(false);
  expect(contentElement("o_studio_n_3", root, NODES)).toBe(queryAll(".o_inner_group")[0]);
  const rect = contentRect("o_studio_n_1", root, NODES);
  const sheet = queryOne(".o_form_sheet").getBoundingClientRect();
  expect(rect.top).toBe(sheet.top);
  expect(rect.width).toBe(sheet.width);
});
test("a page is outlined as its tab and a field as its row", async () => {
  const root = await mountForm();
  const tab = queryOne(".o_notebook .nav-link[name='one']");
  expect(instanceOf("o_studio_n_8", root, NODES)).toBe(tab);
  const pageRect = outlineRect("o_studio_n_8", root, NODES);
  expect(pageRect.top).toBe(tab.getBoundingClientRect().top);
  expect(pageRect.height).toBe(tab.getBoundingClientRect().height);
  const label = findFirst("label.o_form_label");
  const widget = queryOne(".o_field_widget[name='name']");
  const fieldRect = outlineRect("o_studio_n_4", root, NODES);
  expect(fieldRect.left).toBeLessThan(label.getBoundingClientRect().left + 1);
  expect(fieldRect.left + fieldRect.width).toBeGreaterThan(
    widget.getBoundingClientRect().right - 1
  );
  expect(outlineRect("o_studio_n_11", root, NODES)).toBe(null);
  expect(outlineRect("nope", root, NODES)).toBe(null);
});
test("the children of a container, in DOM order, each with its row", async () => {
  const root = await mountForm();
  const group = childEntries(
    "o_studio_n_3",
    root,
    NODES,
    contentElement("o_studio_n_3", root, NODES)
  );
  expect(group.map((entry) => entry.token)).toEqual(["o_studio_n_4", "o_studio_n_5"]);
  expect(group[0].el).toBe(queryOne(".o_field_widget[name='name']"));
  expect(group[0].rect.top).toBeLessThan(group[1].rect.top);
  const label = findFirst("label.o_form_label");
  expect(group[0].rect.left).toBeLessThan(label.getBoundingClientRect().left + 1);
  const sheet = childEntries(
    "o_studio_n_1",
    root,
    NODES,
    contentElement("o_studio_n_1", root, NODES)
  );
  expect(sheet.map((entry) => entry.token)).toEqual(["o_studio_n_2", "o_studio_n_7"]);
  expect(sheet[1].el).toBe(queryOne(".o_notebook"));
  const tabs = childEntries(
    "o_studio_n_7",
    root,
    NODES,
    contentElement("o_studio_n_7", root, NODES)
  );
  expect(tabs.map((entry) => entry.el.getAttribute("name"))).toEqual(["one", "two"]);
  const columns = childEntries(
    "o_studio_n_2",
    root,
    NODES,
    contentElement("o_studio_n_2", root, NODES)
  );
  expect(columns.map((entry) => entry.token)).toEqual(["o_studio_n_3", "o_studio_n_6"]);
  expect(childEntries("o_studio_n_10", root, NODES, null)).toEqual([]);
  expect(tabsOf(root).map((tab) => tab.getAttribute("name"))).toEqual(["one", "two"]);
});
test("viewport rectangles become scroll-container coordinates", () => {
  const fixture = getFixture();
  const scroller = document.createElement("div");
  scroller.style.cssText = "position:relative;height:100px;overflow:auto;";
  const tall = document.createElement("div");
  tall.style.cssText = "height:400px;";
  const mark = document.createElement("div");
  mark.style.cssText = "position:absolute;top:150px;left:20px;width:30px;height:10px;";
  tall.appendChild(mark);
  scroller.appendChild(tall);
  fixture.appendChild(scroller);
  scroller.scrollTop = 100;
  const rect = toContent(mark.getBoundingClientRect(), scroller);
  expect(Math.round(rect.top)).toBe(150);
  expect(Math.round(rect.left)).toBe(20);
  expect(rect.width).toBe(30);
  expect(contains({ top: 10, left: 10, width: 20, height: 20 }, { x: 31, y: 15 })).toBe(false);
  expect(contains({ top: 10, left: 10, width: 20, height: 20 }, { x: 31, y: 15 }, 2)).toBe(true);
});
test("a field's row in the 18 layout: the cells inside the display-contents wrapper", () => {
  const fixture = getFixture();
  fixture.innerHTML = `
        <div class="o_inner_group" style="display:grid;grid-template-columns:100px 200px;width:300px">
            <div class="o_wrap_field" style="display:contents">
                <div class="o_cell o_wrap_label"><label class="o_form_label">Name</label></div>
                <div class="o_cell o_wrap_input"><div class="o_field_widget" name="name">Ada</div></div>
            </div>
        </div>`;
  const widget = fixture.querySelector(".o_field_widget");
  const label = fixture.querySelector(".o_wrap_label");
  const rect = compat.rowRect(widget);
  expect(rect.left).toBe(label.getBoundingClientRect().left);
  expect(rect.width).toBe(300);
});
test("two fields in one 18 row (col=4) each get their own rect, not the row's", () => {
  const fixture = getFixture();
  fixture.innerHTML = `
        <div class="o_inner_group" style="display:grid;grid-template-columns:100px 200px 100px 200px;width:600px">
            <div class="o_wrap_field" style="display:contents">
                <div class="o_cell o_wrap_label"><label class="o_form_label">Name</label></div>
                <div class="o_cell o_wrap_input"><div class="o_field_widget" name="name">Ada</div></div>
                <div class="o_cell o_wrap_label"><label class="o_form_label">Method</label></div>
                <div class="o_cell o_wrap_input"><div class="o_field_widget" name="method">fifo</div></div>
            </div>
        </div>`;
  const [name, method] = [...fixture.querySelectorAll(".o_field_widget")];
  const [nameLabel, methodLabel] = [...fixture.querySelectorAll(".o_wrap_label")];
  const nameRect = compat.rowRect(name);
  const methodRect = compat.rowRect(method);
  expect(nameRect.left).toBe(nameLabel.getBoundingClientRect().left);
  expect(nameRect.width).toBe(300);
  expect(methodRect.left).toBe(methodLabel.getBoundingClientRect().left);
  expect(methodRect.width).toBe(300);
  expect(methodRect.left).toBe(nameRect.left + 300);
  expect(methodRect.top).toBe(nameRect.top);
});
test("a field's row in the 19 layout: sibling cells, no wrapper", () => {
  const fixture = getFixture();
  fixture.innerHTML = `
        <div class="o_inner_group" style="display:grid;grid-template-columns:100px 200px;width:300px">
            <div class="o_cell o_wrap_label"><label class="o_form_label">Name</label></div>
            <div class="o_cell"><div class="o_field_widget" name="name">Ada</div></div>
        </div>`;
  const widget = fixture.querySelector(".o_field_widget");
  const label = fixture.querySelector(".o_wrap_label");
  const rect = compat.rowRect(widget);
  expect(rect.left).toBe(label.getBoundingClientRect().left);
  expect(rect.width).toBe(300);
});
