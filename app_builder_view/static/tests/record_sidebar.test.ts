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
import type {
    RecordPaneModel,
    VisibleWhenClauses,
} from "@app_builder_view/console/record_pane/record_pane_model";
import type { StudioShell } from "@app_builder_view/console/shell/shell_model";
import type {
    RecordChildrenJSON,
    RecordDescription,
    RecordRowJSON,
    RowJSON,
    SectionJSON,
} from "@app_builder_view/console/wire";

/**
 * A `RowJSON` (one editable field of a section) with defaults for the
 * fourteen fields this fixture's own sections never vary -- the same
 * builder-with-defaults house pattern as `console_model.test.ts`'s own
 * `node()`/`editingContext()`: a partial literal does not "sufficiently
 * overlap" `RowJSON`'s eighteen fields on a bare `as` (TYPING.md, "Known
 * traps"). Named `fieldRow` here, not `row` as the original JS had it,
 * since this file's own fixtures also need a *different* "row" --
 * `RecordRowJSON`, a record's own card -- and JS did not need to
 * disambiguate the two by name the way distinct interfaces now do.
 */
function fieldRow(name: string, type: string, extra: Partial<RowJSON> = {}): RowJSON {
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
        ...extra,
    };
}

function section(
    id: string,
    title: string,
    rows: RowJSON[],
    visible_when: SectionJSON["visible_when"] = [],
): SectionJSON {
    return { id, title, rows, visible_when };
}

/**
 * A `RecordRowJSON` (a record's own card, `RecordDescription.row`) with
 * defaults for the fields this fixture's cards never vary -- `id`/`title`
 * stay required, the same `Partial<T> & Pick<T, ...>` shape
 * `console_model.test.ts`'s own `pendingChange()` already uses for an
 * identical "most fields default, a couple always given" builder.
 */
function recordRow(
    overrides: Partial<RecordRowJSON> & Pick<RecordRowJSON, "id" | "title">,
): RecordRowJSON {
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
        ...overrides,
    };
}

const STEP_SECTIONS: SectionJSON[] = [
    section("step", "Action", [
        fieldRow("state", "select", {
            choices: [
                ["code", "Execute Code"],
                ["object_write", "Update Record"],
            ],
            allow_empty: false,
        }),
        fieldRow("name", "text"),
    ]),
    section("update", "Update", [fieldRow("update_path", "text")], [["state", ["object_write"]]]),
];

/**
 * One automation step, described the way `add_step`'s surface answers --
 * `RecordChildrenJSON.items` is `RecordDescription[]`, recursively.
 * `advanced` is never read for a child (only the top-level record's
 * "Advanced…" button reads `this.record.advanced`, `record_pane.ts`'s own
 * `onAdvanced`), but the field is required on `RecordDescription`
 * regardless of who reads it -- inert defaults, the same "typed to the
 * full interface, unread fields stay inert" treatment
 * `console_model.test.ts`'s own `draftPayload()` already gives `spec`/
 * `anchors`.
 */
function step(id: number, state: string): RecordDescription {
    return {
        row: recordRow({ id, title: `Step ${id}` }),
        values: { state, name: `Step ${id}`, update_path: "" },
        sections: STEP_SECTIONS,
        actions: [],
        notes: [],
        advanced: { res_model: "", res_id: 0, context: { studio_package_id: false } },
        sentence: state,
    };
}

/** One call `makeModel()`'s fake recorded, method name first. */
type LoggedCall = readonly [string, ...unknown[]];

/**
 * What `RecordSidebar` itself reads off `this.model` (grepped
 * `this\.model\.` over the class in `record_pane.ts`, the same way
 * `ConsoleModelOwner`/`CanvasDragModel` were each scoped): `record`,
 * `children`, `extra`, `visible`, `write`, `writeChild`, `addChild`,
 * `moveChild`, `removeChild`, `runChild`, `runAction` -- `describing`/
 * `busy` carried over from the original JS fixture too, harmlessly unread
 * by `RecordSidebar` (`RecordPane`'s own activity pill reads them, not
 * this component).
 *
 * `RecordSidebar`'s own `Props.model` is typed as the full
 * `RecordPaneModel` class (unlike `ConsoleModel`/`CanvasDrag`, which each
 * took a narrow, purpose-built owner interface once their own tests
 * needed one) -- `record_pane.ts` is already-converted, out of this
 * file's own scope to change, so this interface stays local to the test
 * and the fixture is handed to `mountWithCleanup` through an `as unknown
 * as RecordPaneModel` cast instead (below), the same "the two shapes do
 * not sufficiently overlap for a direct `as`" cast `record_pane.ts`'s own
 * `entry as unknown as RecordPaneEntry` already uses.
 */
interface FakeModel {
    record: RecordDescription;
    readonly children: RecordChildrenJSON | null;
    describing: boolean;
    busy: boolean;
    extra: Record<string, unknown>;
    visible(
        clauses: VisibleWhenClauses | null | undefined,
        values: Record<string, unknown>,
    ): boolean;
    write(values: Record<string, unknown>): unknown;
    writeChild(id: number, values: Record<string, unknown>): unknown;
    // The real `RecordPaneModel.addChild` takes `string | null` (`onAddChild`
    // guards the empty-selection case before ever calling it), but this
    // fixture's own implementation is only ever exercised with a real kind
    // -- narrowed to `string` here, the same "typed to what it actually,
    // always evaluates to" treatment `row.placeholder`/`row.follow`
    // already got elsewhere in this migration.
    addChild(kind: string): Promise<RecordDescription>;
    moveChild(id: number, before: number | false): unknown;
    removeChild(id: number): unknown;
    runChild(id: number, key: string): unknown;
    runAction(key: string): unknown;
}

function makeModel(calls: LoggedCall[]): FakeModel {
    const model: FakeModel = {
        record: {
            row: recordRow({ id: 1, title: "Rule" }),
            values: { name: "Rule", active: true },
            sections: [
                section("rule", "Automation", [
                    fieldRow("name", "text"),
                    fieldRow("active", "toggle"),
                ]),
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
                context: { studio_package_id: false },
            },
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
            return this.record.children || null;
        },
        describing: false,
        busy: false,
        extra: {},
        visible(clauses, values) {
            for (const [name, allowed] of clauses || []) {
                // `values[name]` is `unknown` (`Record<string, unknown>`);
                // this fixture's own tests only ever pass plain strings, so
                // unlike the real `RecordPaneModel.visible`'s own id-unwrap
                // (`record_pane_model.ts`, the same `no-base-to-string`
                // finding already accepted there) nothing here needs to
                // handle an object value.
                // eslint-disable-next-line @typescript-eslint/no-base-to-string
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
    return model;
}

/**
 * What `RecordSidebar` itself reads off `this.shell`: `modelName`
 * (`rowContext`) and `refreshChanges()` (`onAdvanced`'s save callback,
 * never exercised by this file's own tests). `modelLabel`/
 * `packageWritable`/`package` are `RecordPane`'s own reads, not
 * `RecordSidebar`'s -- carried over from the original JS `SHELL` fixture
 * unchanged (harmless extra fields on a plain object) rather than pruned,
 * since pruning them is not this pass's job. Cast the same way as
 * `FakeModel` above, for the identical reason (`StudioShell` is a ~30
 * member class, `Props.shell` stays typed to it in `record_pane.ts`).
 */
interface SidebarShellStub {
    modelName: string;
    modelLabel: string;
    packageWritable: boolean;
    package: { name: string };
}

const SHELL: SidebarShellStub = {
    modelName: "res.partner",
    modelLabel: "Contact",
    packageWritable: true,
    package: { name: "pkg" },
};

/** The two props every test mounts `RecordSidebar` with, `calls` fresh each time. */
function sidebarProps(calls: LoggedCall[]): { shell: StudioShell; model: RecordPaneModel } {
    return {
        shell: SHELL as unknown as StudioShell,
        model: makeModel(calls) as unknown as RecordPaneModel,
    };
}

test("children are listed folded, with their kind and order", async () => {
    const calls: LoggedCall[] = [];
    await mountWithCleanup(RecordSidebar, { props: sidebarProps(calls) });
    expect(".o_studio_children .o_studio_child").toHaveCount(2);
    expect(queryAllTexts(".o_studio_child .o_studio_child_title .fw-bold")).toEqual([
        "Update Record",
        "Execute Code",
    ]);
    expect(".o_studio_child_body").toHaveCount(0);
});

test("a child unfolds to its rows, and only the rows its state shows", async () => {
    const calls: LoggedCall[] = [];
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
    const calls: LoggedCall[] = [];
    await mountWithCleanup(RecordSidebar, { props: sidebarProps(calls) });
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
