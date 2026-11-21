/** @odoo-module **/
/**
 * The record pane's approval gate, on and off: the form that turns it on,
 * the card that says what a live gate enforces, the change form opened on
 * that, and "Turn off approvals" behind the console's own confirmation --
 * each landing on the pane model's `call` with the surface's own method
 * name. The pane model is stubbed (the server's answer is simulated by
 * swapping `extra.gate`), so what is pinned is the screen and the calls.
 */

import {expect, test} from "@odoo/hoot";
import {click, queryAllTexts, queryOne, select} from "@odoo/hoot-dom";
import {animationFrame} from "@odoo/hoot-mock";
import {mountWithCleanup} from "@web/../tests/web_test_helpers";

import {RecordPane} from "@app_builder_view/console/record_pane/record_pane";
import type {RecordPaneModel} from "@app_builder_view/console/record_pane/record_pane_model";
import type {BuilderShell} from "@app_builder_view/console/shell/shell_model";
import type {
  ApprovalGateJSON,
  GateConfigJSON,
  RecordRowJSON,
  StateFieldJSON,
} from "@app_builder_view/console/wire";

/** One call the fake model recorded: the surface method, then its args. */
type LoggedCall = readonly [string, unknown[]];

const STATUS: StateFieldJSON = {
  name: "state",
  string: "Status",
  values: [
    {value: "draft", label: "Draft"},
    {value: "review", label: "In review"},
    {value: "done", label: "Done"},
    {value: "cancel", label: "Cancelled"},
  ],
};
const STATE_FIELDS: StateFieldJSON[] = [STATUS];

/** A `catalogue()` gate as `builder_approval_surface.py` sends it. */
function gate(current: GateConfigJSON | null, module = ""): ApprovalGateJSON {
  return {
    on: Boolean(current),
    title: current
      ? "Approvals are on for x_job"
      : "Approvals are not switched on for x_job",
    help: current ? "" : "An approval rule gates a state change.",
    consequence: "Writes the tier.validation mixin into the model's class; one reload.",
    current,
    module: current ? module || "x_pkg" : "",
    off_consequence:
      "The approval rules stay as they are. The validation status column is kept under a renamed column.",
    state_fields: STATE_FIELDS,
    call: "enable_gate",
    update_call: "update_gate",
    disable_call: "disable_gate",
  };
}

const LIVE: GateConfigJSON = {
  state_field: "state",
  state_from: ["draft", "review", "cancel"],
  state_to: ["done"],
  cancel_state: "cancel",
};

function rule(id: number): RecordRowJSON {
  return {
    id,
    title: `Rule ${id}`,
    sentence: "Somebody approves",
    badges: [],
    active: true,
    owned: true,
    owner: "x_pkg",
    in_source: true,
    editable: true,
    reason: "",
    model: "x_job",
  };
}

/**
 * What `RecordPane` reads off its model (its template's and class's own
 * `this.model.*`). `call` answers the way the server does after the reload:
 * the catalogue is read again, here by swapping `extra.gate` for what the
 * change leaves behind. Written as a method so `this` is the reactive proxy
 * the component holds, and the swap re-renders it.
 */
interface FakeModel {
  entry: {key: string; scope: string; label: string};
  extra: {gate: ApprovalGateJSON};
  rows: RecordRowJSON[];
  readonly visibleRows: RecordRowJSON[];
  templates: never[];
  loading: boolean;
  busy: boolean;
  search: string;
  filter: string;
  showInactive: boolean;
  selectedId: number | false;
  creating: null;
  calls: LoggedCall[];
  refuse: boolean;
  call(method: string, args: unknown[]): Promise<unknown>;
}

function makeModel(initial: ApprovalGateJSON, rows: RecordRowJSON[] = []): FakeModel {
  return {
    entry: {key: "approvals", scope: "model", label: "Approvals"},
    extra: {gate: initial},
    rows,
    get visibleRows() {
      return this.rows;
    },
    templates: [],
    loading: false,
    busy: false,
    search: "",
    filter: "all",
    showInactive: false,
    selectedId: false,
    creating: null,
    calls: [],
    refuse: false,
    async call(method, args) {
      this.calls.push([method, args]);
      if (this.refuse) {
        // `RecordPaneModel.call`'s answer to a refusal: the notification
        // is its business, the caller is handed nothing.
        return undefined;
      }
      const [, , field, , to, cancel] = args as [
        number,
        string,
        string,
        string[] | false,
        string[],
        string | false,
      ];
      if (method === "disable_gate") {
        this.extra = {gate: gate(null)};
      } else {
        const values = STATUS.values.map((v) => v.value);
        this.extra = {
          gate: gate({
            state_field: field,
            state_from: values.filter((v) => !to.includes(v)),
            state_to: to,
            cancel_state: cancel || "",
          }),
        };
      }
      return {model: "x_job", applied: true};
    },
  };
}

interface ShellStub {
  modelName: string;
  modelLabel: string;
  packageId: number | false;
  packageWritable: boolean;
  package: {name: string; read_only_reason?: string} | null;
  refreshed: number;
  refreshChanges(): void;
}

function makeShell(overrides: Partial<ShellStub> = {}): ShellStub {
  return {
    modelName: "x_job",
    modelLabel: "Job",
    packageId: 7,
    packageWritable: true,
    package: {name: "x_pkg", read_only_reason: ""},
    refreshed: 0,
    refreshChanges() {
      this.refreshed++;
    },
    ...overrides,
  };
}

async function mountPane(
  model: FakeModel,
  shell: ShellStub = makeShell()
): Promise<void> {
  await mountWithCleanup(RecordPane as never, {
    props: {
      shell: shell as unknown as BuilderShell,
      model: model as unknown as RecordPaneModel,
    },
  });
}

test("a closed gate is turned on with the transition picked", async () => {
  const model = makeModel(gate(null));
  await mountPane(model);
  expect(".o_builder_gate_card:not(.o_builder_gate_on)").toHaveCount(1);
  expect(".o_builder_gate_enable").toHaveAttribute("disabled");
  await select("done", {target: "#o_builder_gate_to"});
  await animationFrame();
  expect(".o_builder_gate_sentence").toHaveText(
    "Approval is asked for when Status goes from any state to Done."
  );
  await click(".o_builder_gate_enable");
  await animationFrame();
  expect(model.calls).toEqual([
    ["enable_gate", [7, "x_job", "state", false, ["done"], false]],
  ]);
  // The catalogue came back gated: the card says what is enforced now.
  expect(".o_builder_gate_on").toHaveCount(1);
  expect(queryAllTexts(".o_builder_gate_current")).toEqual([
    "Approval is asked for when Status goes from Draft, In review, Cancelled to Done.",
  ]);
});

test("a live gate says what it enforces, its cancel state included", async () => {
  await mountPane(makeModel(gate(LIVE), [rule(1)]));
  expect(".o_builder_gate_on .fw-bold").toHaveText("Approvals are on for x_job");
  expect(queryAllTexts(".o_builder_gate_current")).toEqual([
    "Approval is asked for when Status goes from Draft, In review, Cancelled to Done.",
    "Reaching Cancelled clears the approvals asked so far.",
  ]);
  expect(".o_builder_gate_change:not(:disabled)").toHaveCount(1);
  expect(".o_builder_gate_disable:not(:disabled)").toHaveCount(1);
  expect(".o_builder_gate_locked").toHaveCount(0);
});

test("changing opens on what is enforced, and saves through update_gate", async () => {
  const model = makeModel(gate(LIVE), [rule(1)]);
  await mountPane(model);
  await click(".o_builder_gate_change");
  await animationFrame();
  expect(".o_builder_gate_on .o_builder_gate_form").toHaveCount(1);
  // The destination and the cancel state as they are; the origins empty,
  // which is what the class is written with whatever is picked.
  const to = queryOne("#o_builder_gate_to") as HTMLSelectElement;
  expect([...to.selectedOptions].map((o) => o.value)).toEqual(["done"]);
  expect((queryOne("#o_builder_gate_cancel") as HTMLSelectElement).value).toBe(
    "cancel"
  );
  const from = queryOne("#o_builder_gate_from") as HTMLSelectElement;
  expect(from.selectedOptions.length).toBe(0);

  await select(["review", "done"], {target: "#o_builder_gate_to"});
  await animationFrame();
  await click(".o_builder_gate_save");
  await animationFrame();
  expect(model.calls).toEqual([
    ["update_gate", [7, "x_job", "state", false, ["review", "done"], "cancel"]],
  ]);
  expect(".o_builder_gate_on .o_builder_gate_form").toHaveCount(0);
  expect(queryAllTexts(".o_builder_gate_current")[0]).toBe(
    "Approval is asked for when Status goes from Draft, Cancelled to In review, Done."
  );
});

test("a refused change keeps the form open; Cancel closes it untouched", async () => {
  const model = makeModel(gate(LIVE));
  model.refuse = true;
  await mountPane(model);
  await click(".o_builder_gate_change");
  await animationFrame();
  await click(".o_builder_gate_save");
  await animationFrame();
  expect(model.calls.map((c) => c[0])).toEqual(["update_gate"]);
  expect(".o_builder_gate_on .o_builder_gate_form").toHaveCount(1);
  await click(".o_builder_gate_cancel_change");
  await animationFrame();
  expect(".o_builder_gate_on .o_builder_gate_form").toHaveCount(0);
  expect(model.calls).toHaveLength(1);
});

test("turning off asks first, says what happens to data, and can be cancelled", async () => {
  const model = makeModel(gate(LIVE), [rule(1), rule(2)]);
  await mountPane(model);
  await click(".o_builder_gate_disable");
  await animationFrame();
  expect(".modal .modal-title").toHaveText("Turn off approvals");
  const body = queryOne(".modal-body").textContent || "";
  expect(body).toInclude("Turn off approvals on Job?");
  expect(body).toInclude("Its 2 approval rules stay, and are not asked any more.");
  expect(body).toInclude("renamed column");
  expect(model.calls).toHaveLength(0);
  await click(".modal-footer .btn-secondary");
  await animationFrame();
  expect(".modal").toHaveCount(0);
  expect(model.calls).toHaveLength(0);
  expect(".o_builder_gate_on").toHaveCount(1);
});

test("confirming the turn-off calls disable_gate and the enable form comes back", async () => {
  const model = makeModel(gate(LIVE), [rule(1)]);
  const shell = makeShell();
  await mountPane(model, shell);
  await click(".o_builder_gate_disable");
  await animationFrame();
  expect(queryOne(".modal-body").textContent || "").toInclude(
    "Its 1 approval rule stays, and is not asked any more."
  );
  await click(".modal-footer .btn-danger");
  await animationFrame();
  expect(model.calls).toEqual([["disable_gate", [7, "x_job"]]]);
  expect(shell.refreshed).toBe(1);
  expect(".o_builder_gate_on").toHaveCount(0);
  expect(".o_builder_gate_enable").toHaveCount(1);
});

test("a read-only package: every control off, with the server's reason", async () => {
  const reason = "Writing code is switched off on this server.";
  const shell = makeShell({
    packageWritable: false,
    package: {name: "x_pkg", read_only_reason: reason},
  });
  await mountPane(makeModel(gate(LIVE)), shell);
  expect(".o_builder_gate_change").toHaveAttribute("disabled");
  expect(".o_builder_gate_disable").toHaveAttribute("disabled");
  expect(".o_builder_gate_locked").toHaveText(reason);
  expect(".o_builder_gate_disable").toHaveAttribute(
    "aria-describedby",
    "o_builder_gate_locked"
  );
});

test("a read-only package keeps the enable form, disabled, and says why", async () => {
  const shell = makeShell({packageWritable: false, package: {name: "x_pkg"}});
  const model = makeModel(gate(null));
  await mountPane(model, shell);
  expect("fieldset.o_builder_gate_form").toHaveAttribute("disabled");
  expect(".o_builder_gate_locked").toHaveText(
    "x_pkg is read-only, so the gate cannot be written."
  );
});

test("a gate another module wrote is not offered for change here", async () => {
  await mountPane(makeModel(gate(LIVE, "some_other_module")));
  expect(".o_builder_gate_change").toHaveAttribute("disabled");
  expect(".o_builder_gate_disable").toHaveAttribute("disabled");
  expect(".o_builder_gate_locked").toHaveText(
    "The approval gate on Job was written by some_other_module; change it or turn it off there."
  );
});

test("no package chosen: nothing can be written, and the pane says so", async () => {
  await mountPane(
    makeModel(gate(LIVE)),
    makeShell({package: null, packageId: false, packageWritable: false})
  );
  expect(".o_builder_gate_disable").toHaveAttribute("disabled");
  expect(".o_builder_gate_locked").toHaveText(
    "Choose a package to record approvals in."
  );
});
