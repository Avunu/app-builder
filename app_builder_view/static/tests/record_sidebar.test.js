/** @odoo-module **/
/**
 * The record sidebar on a described record: sections as rows, and the
 * record's children (an automation's steps) as a list that unfolds one
 * at a time, adds by kind, moves and removes -- every gesture landing on
 * the pane model, which is stubbed here so what is pinned is the screen.
 */

import { expect, test } from "@odoo/hoot";
import { click, queryAll, queryAllTexts, select } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

import { RecordSidebar } from "@app_builder_view/console/record_pane/record_pane";

const section = (id, title, rows, visible_when = []) => ({ id, title, rows, visible_when });
const row = (name, type, extra = {}) => ({
    name,
    label: name,
    type,
    help: "",
    choices: [],
    visible_when: [],
    allow_empty: true,
    required: false,
    ...extra,
});

const STEP_SECTIONS = [
    section("step", "Action", [
        row("state", "select", {
            choices: [
                ["code", "Execute Code"],
                ["object_write", "Update Record"],
            ],
            allow_empty: false,
        }),
        row("name", "text"),
    ]),
    section("update", "Update", [row("update_path", "text")], [["state", ["object_write"]]]),
];

function step(id, state) {
    return {
        row: { id, title: "Step " + id, badges: [], editable: true, in_source: true },
        values: { state, name: "Step " + id, update_path: "" },
        sections: STEP_SECTIONS,
        actions: [],
        notes: [],
        sentence: state,
    };
}

function makeModel(calls) {
    return {
        record: {
            row: { id: 1, title: "Rule", badges: [], editable: true, reason: "", in_source: true },
            values: { name: "Rule", active: true },
            sections: [section("rule", "Automation", [row("name", "text"), row("active", "toggle")])],
            actions: [],
            notes: [],
            advanced: { res_model: "base.automation", res_id: 1, context: {} },
            children: {
                surface: "studio.automation.step",
                label: "Then",
                one: "step",
                items: [step(11, "object_write"), step(12, "code")],
                kinds: [
                    ["code", "Execute Code"],
                    ["object_write", "Update Record"],
                ],
                kind_field: "state",
                add: "add_step",
                move: "move_step",
                empty: "The automation needs something to do.",
            },
        },
        get children() {
            return this.record.children;
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
        runAction: (key) => calls.push(["runAction", key]),
    };
}

const SHELL = { modelName: "res.partner", modelLabel: "Contact", packageWritable: true, package: { name: "pkg" } };

test("children are listed folded, with their kind and order", async () => {
    const calls = [];
    await mountWithCleanup(RecordSidebar, { props: { shell: SHELL, model: makeModel(calls) } });
    expect(".o_studio_children .o_studio_child").toHaveCount(2);
    expect(queryAllTexts(".o_studio_child .o_studio_child_title .fw-bold")).toEqual([
        "Update Record",
        "Execute Code",
    ]);
    expect(".o_studio_child_body").toHaveCount(0);
});

test("a child unfolds to its rows, and only the rows its state shows", async () => {
    const calls = [];
    await mountWithCleanup(RecordSidebar, { props: { shell: SHELL, model: makeModel(calls) } });
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
    await mountWithCleanup(RecordSidebar, { props: { shell: SHELL, model: makeModel(calls) } });
    await select("code", { target: ".o_studio_child_add" });
    await animationFrame();
    expect(calls.pop()).toEqual(["addChild", "code"]);
    // Down on the first: before the one after the next -- there is none, so last.
    await click(queryAll(".o_studio_child_down")[0]);
    expect(calls.pop()).toEqual(["moveChild", 11, false]);
    await click(queryAll(".o_studio_child_up")[1]);
    expect(calls.pop()).toEqual(["moveChild", 12, 11]);
    expect(queryAll(".o_studio_child_up")[0]).toHaveAttribute("disabled");
});
