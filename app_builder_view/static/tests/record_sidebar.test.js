import { expect, test } from "@odoo/hoot";
import { click, queryAll, queryAllTexts, select } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { RecordSidebar } from "@app_builder_view/console/record_pane/record_pane";
function fieldRow(name, type, extra = {}) {
  return {
    name,
    label: name,
    type,
    target: "",
    help: "",
    invert: false,
    choices: [],
    source: "",
    field_types: [],
    only_for: [],
    placeholder_from: "",
    allow_empty: true,
    empty_label: "",
    comodel: "",
    comodel_domain: "",
    selection_from: "",
    visible_when: [],
    required: false,
    language: "",
    ...extra
  };
}
function section(id, title, rows, visible_when = []) {
  return { id, title, rows, visible_when };
}
function recordRow(overrides) {
  return {
    sentence: "",
    badges: [],
    active: true,
    owned: true,
    owner: false,
    in_source: true,
    editable: true,
    reason: "",
    model: "res.partner",
    ...overrides
  };
}
const STEP_SECTIONS = [
  section("step", "Action", [
    fieldRow("state", "select", {
      choices: [
        ["code", "Execute Code"],
        ["object_write", "Update Record"]
      ],
      allow_empty: false
    }),
    fieldRow("name", "text")
  ]),
  section("update", "Update", [fieldRow("update_path", "text")], [["state", ["object_write"]]])
];
function step(id, state) {
  return {
    row: recordRow({ id, title: `Step ${id}` }),
    values: { state, name: `Step ${id}`, update_path: "" },
    sections: STEP_SECTIONS,
    actions: [],
    notes: [],
    advanced: { res_model: "", res_id: 0, context: { studio_package_id: false } },
    sentence: state
  };
}
function makeModel(calls) {
  const model = {
    record: {
      row: recordRow({ id: 1, title: "Rule" }),
      values: { name: "Rule", active: true },
      sections: [
        section("rule", "Automation", [
          fieldRow("name", "text"),
          fieldRow("active", "toggle")
        ])
      ],
      actions: [],
      notes: [],
      // `sentence` is required on `RecordDescription`, but the
      // original JS fixture never set it either -- `RecordSidebar`
      // itself never reads it (only `RecordPane`'s own header does),
      // so an inert default, not a behavior change.
      sentence: "",
      advanced: {
        res_model: "base.automation",
        res_id: 1,
        context: { studio_package_id: false }
      },
      children: {
        surface: "studio.automation.step",
        label: "Then",
        one: "step",
        items: [step(11, "object_write"), step(12, "code")],
        kinds: [
          ["code", "Execute Code"],
          ["object_write", "Update Record"]
        ],
        kind_field: "state",
        add: "add_step",
        move: "move_step",
        empty: "The automation needs something to do."
      }
    },
    get children() {
      return this.record.children || null;
    },
    describing: false,
    busy: false,
    extra: {},
    visible(clauses, values) {
      for (const [name, allowed] of clauses || []) {
        if (!allowed.includes(String(values[name] ?? ""))) {
          return false;
        }
      }
      return true;
    },
    write: (values) => calls.push(["write", values]),
    writeChild: (id, values) => calls.push(["writeChild", id, values]),
    addChild: async (kind) => {
      calls.push(["addChild", kind]);
      return step(13, kind);
    },
    moveChild: (id, before) => calls.push(["moveChild", id, before]),
    removeChild: (id) => calls.push(["removeChild", id]),
    runChild: (id, key) => calls.push(["runChild", id, key]),
    runAction: (key) => calls.push(["runAction", key])
  };
  return model;
}
const SHELL = {
  modelName: "res.partner",
  modelLabel: "Contact",
  packageWritable: true,
  package: { name: "pkg" }
};
function sidebarProps(calls) {
  return {
    shell: SHELL,
    model: makeModel(calls)
  };
}
test("children are listed folded, with their kind and order", async () => {
  const calls = [];
  await mountWithCleanup(RecordSidebar, { props: sidebarProps(calls) });
  expect(".o_studio_children .o_studio_child").toHaveCount(2);
  expect(queryAllTexts(".o_studio_child .o_studio_child_title .fw-bold")).toEqual([
    "Update Record",
    "Execute Code"
  ]);
  expect(".o_studio_child_body").toHaveCount(0);
});
test("a child unfolds to its rows, and only the rows its state shows", async () => {
  const calls = [];
  await mountWithCleanup(RecordSidebar, { props: sidebarProps(calls) });
  await click(queryAll(".o_studio_child_head")[0]);
  await animationFrame();
  expect(".o_studio_child.open").toHaveCount(1);
  expect(".o_studio_child.open .o_studio_row[data-row='update_path']").toHaveCount(1);
  await click(queryAll(".o_studio_child_head")[1]);
  await animationFrame();
  expect(".o_studio_child.open .o_studio_row[data-row='update_path']").toHaveCount(0);
  expect(".o_studio_child.open .o_studio_row[data-row='name']").toHaveCount(1);
});
test("adding, moving and removing go through the model", async () => {
  const calls = [];
  await mountWithCleanup(RecordSidebar, { props: sidebarProps(calls) });
  await select("code", { target: ".o_studio_child_add" });
  await animationFrame();
  expect(calls.pop()).toEqual(["addChild", "code"]);
  await click(queryAll(".o_studio_child_down")[0]);
  expect(calls.pop()).toEqual(["moveChild", 11, false]);
  await click(queryAll(".o_studio_child_up")[1]);
  expect(calls.pop()).toEqual(["moveChild", 12, 11]);
  expect(queryAll(".o_studio_child_up")[0]).toHaveAttribute("disabled");
});
