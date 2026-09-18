import { beforeEach, expect, test } from "@odoo/hoot";
import { patchTranslations } from "@web/../tests/web_test_helpers";
import { ConsoleModel } from "@app_builder_view/console/console_model";
import { DraftModel } from "@app_builder_view/console/shell/draft_model";
beforeEach(() => patchTranslations());
const BUTTON = { kind: "component", component: "button", values: {} };
function node(tag, name, parent, index, extra = {}) {
  return {
    kind: tag === "form" ? "root" : tag,
    tag,
    name,
    parent,
    index,
    children: [],
    string: null,
    container: tag !== "field",
    orientation: "column",
    accepts: [],
    movable: true,
    removable: true,
    selectable: true,
    hidden: null,
    attrs: {},
    dom: true,
    field: null,
    view_id: null,
    label: null,
    ...extra
  };
}
function canvas(version, entries) {
  const nodes = {
    o_studio_n_0: node("form", null, null, 0, { children: ["o_studio_n_1"] }),
    o_studio_n_1: node("sheet", null, "o_studio_n_0", 0, {
      children: entries.map((_, i) => `o_studio_n_${i + 2}`)
    })
  };
  entries.forEach((entry, i) => {
    const { tag, name } = typeof entry === "string" ? { tag: "field", name: entry } : entry;
    nodes[`o_studio_n_${i + 2}`] = node(tag, name || null, "o_studio_n_1", i);
  });
  return {
    view: { id: 7, name: "", type: "form", model: "res.partner", mode: "form", js_class: null },
    arch: null,
    models: {},
    arch_version: version,
    res_id: false,
    root: "o_studio_n_0",
    nodes,
    pending: [],
    draft_id: false,
    editable_as: "canvas",
    source: null,
    history: { undo: [], redo: [] },
    package: null,
    record_count: 0
  };
}
function editingContext(overrides = {}) {
  return {
    view: { id: 7, name: "", type: "form", model: "res.partner", mode: "form" },
    views: [],
    python_owned: false,
    python_owner_id: false,
    field_types: [],
    draft_id: false,
    reload_mode: false,
    record_count: 0,
    fields: [],
    preview: { type: "form", view_id: false, search_view_id: false },
    options: null,
    catalogue: null,
    groups: null,
    owned: false,
    packages: null,
    suggested_package_id: false,
    ...overrides
  };
}
function draftPayload(overrides = {}) {
  return {
    id: 9,
    model: "x_job",
    package: { id: 1, name: "test", writable: true, reload_mode: "inproc" },
    spec: null,
    fields: [],
    pending: [],
    change_count: 0,
    field_types: [],
    errors: [],
    view: null,
    anchors: null,
    ...overrides
  };
}
function pendingChange(overrides) {
  return { name: "", detail: "", ...overrides };
}
function makeModel() {
  const calls = [];
  const notices = [];
  const orm = {
    // A drop answers with a canvas, as the server does; the same one,
    // since what is pinned here is what was sent.
    async call(_model, method, args, kwargs) {
      calls.push({ method, args, kwargs });
      return method === "drop_at" ? { canvas: model.canvas } : {};
    },
    async searchRead() {
      return [];
    }
  };
  const notification = {
    add(message, options) {
      notices.push({ message: String(message), type: options && options.type });
    }
  };
  const field = {
    async loadFields() {
      throw new Error("not exercised in this test");
    },
    async loadPath() {
      throw new Error("not exercised in this test");
    }
  };
  const env = {
    services: { orm, notification, field },
    bus: { trigger: () => void 0 }
  };
  const shell = {
    packageId: 3,
    modelName: "res.partner",
    modelLabel: "Contact",
    learned: editingContext(),
    async learnContext(context) {
      this.learned = context;
      this.modelName = context.view.model || null;
      this.draft.setHints(context);
    },
    get pythonOwned() {
      return Boolean(this.learned.python_owned);
    },
    // Replaced on the next line -- `DraftModel`'s own constructor
    // needs `shell` already in hand, so the circular reference is
    // resolved the same two-step way the real `StudioShell` resolves
    // it in its own constructor.
    draft: null
  };
  shell.draft = new DraftModel(env, shell);
  const model = new ConsoleModel(env, shell);
  model.params = { view_id: 7, model: false, view_type: false, res_id: false };
  model._replaceCanvas(canvas("v1", ["name", "email", "phone"]));
  return { model, calls, notices, shell };
}
test("a dropped Button tile is held with the version its token was minted on", async () => {
  const { model, calls } = makeModel();
  const result = await model.drop("o_studio_n_3", "after", BUTTON);
  expect(result).toBe(void 0);
  expect(calls).toEqual([]);
  expect(model.buttonTarget?.token).toBe("o_studio_n_3");
  expect(model.buttonTarget?.position).toBe("after");
  expect(model.buttonTarget?.arch_version).toBe("v1");
});
test("the held drop follows its node across a re-stamped canvas", async () => {
  const { model, calls, notices } = makeModel();
  await model.drop("o_studio_n_3", "after", BUTTON);
  model._replaceCanvas(canvas("v2", ["name", "x_new", "email", "phone"]));
  expect(model.buttonTarget?.token).toBe("o_studio_n_4");
  expect(model.buttonTarget?.arch_version).toBe("v2");
  expect(notices).toEqual([]);
  await model.addButton({ string: "Go", action_id: 5 });
  expect(calls).toHaveLength(1);
  expect(calls[0]?.method).toBe("drop_at");
  expect(calls[0]?.args?.[2]).toEqual({ token: "o_studio_n_4", position: "after" });
  expect(calls[0]?.args?.[4]).toBe("v2");
  expect(model.buttonTarget).toBe(null);
});
test("the held drop is let go of when its node cannot be found again", async () => {
  const { model, calls, notices } = makeModel();
  await model.drop("o_studio_n_3", "after", BUTTON);
  model._replaceCanvas(canvas("v2", ["name", "phone"]));
  expect(model.buttonTarget).toBe(null);
  expect(notices).toHaveLength(1);
  expect(notices[0]?.type).toBe("info");
  expect(notices[0]?.message).toMatch(/drop the button again/);
  model.select("o_studio_n_2");
  await model.addButton({ string: "Go", action_id: 5 });
  expect(calls).toHaveLength(1);
  expect(calls[0]?.args?.[2]).toEqual({ token: "o_studio_n_2", position: "after" });
  expect(calls[0]?.args?.[4]).toBe("v2");
});
test("a target from another version is refused rather than sent", async () => {
  const { model, calls, notices } = makeModel();
  await model.drop("o_studio_n_3", "after", BUTTON);
  model.canvas = { ...model.canvas, arch_version: "v9" };
  const result = await model.addButton({ string: "Go", action_id: 5 });
  expect(result).toBe(void 0);
  expect(calls).toEqual([]);
  expect(notices).toHaveLength(1);
  expect(model.buttonTarget).toBe(null);
});
test("a nameless anchor is itself again only while nothing before it moved", async () => {
  const { model, notices } = makeModel();
  model._replaceCanvas(canvas("v1", ["name", "email", { tag: "separator" }, "phone"]));
  await model.drop("o_studio_n_4", "after", BUTTON);
  model._replaceCanvas(canvas("v2", ["name", "email", { tag: "separator" }]));
  expect(model.buttonTarget?.token).toBe("o_studio_n_4");
  expect(model.buttonTarget?.arch_version).toBe("v2");
  expect(notices).toEqual([]);
  model._replaceCanvas(
    canvas("v3", ["name", { tag: "separator" }, "email", { tag: "separator" }])
  );
  expect(model.buttonTarget).toBe(null);
  expect(notices).toHaveLength(1);
});
test("a named anchor is told from its namesake in a subview by its parent", async () => {
  const { model, notices } = makeModel();
  await model.drop("o_studio_n_3", "after", BUTTON);
  const payload = canvas("v2", ["name", "x_new", "email", "phone", { tag: "list" }]);
  const mutableNodes = payload.nodes;
  mutableNodes["o_studio_n_7"] = node("field", "email", "o_studio_n_6", 0);
  mutableNodes["o_studio_n_6"].children = ["o_studio_n_7"];
  model._replaceCanvas(payload);
  expect(model.buttonTarget?.token).toBe("o_studio_n_4");
  expect(notices).toEqual([]);
  model._replaceCanvas(canvas("v3", ["name", "email", "phone", "email"]));
  expect(model.buttonTarget).toBe(null);
  expect(notices).toHaveLength(1);
});
const LINK = {
  kind: "new_field",
  values: { ttype: "many2one", field_description: "New Link" }
};
test("a dropped field tile that needs the editor is held, not sent", async () => {
  const { model, calls } = makeModel();
  const result = await model.drop("o_studio_n_3", "after", LINK);
  expect(result).toBe(void 0);
  expect(calls).toEqual([]);
  expect(model.fieldTarget?.token).toBe("o_studio_n_3");
  expect(model.fieldTarget?.ttype).toBe("many2one");
  expect(model.fieldTarget?.arch_version).toBe("v1");
});
test("the server's word on the editor wins over the built-in list", async () => {
  const { model, calls } = makeModel();
  model.fieldTypes = [
    {
      value: "many2one",
      ttype: "many2one",
      widget: "",
      label: "",
      group: "",
      params: [],
      enabled: true,
      tooltip: "",
      placement: { form: true, list: true, search: true, group_by: false, widget: "" },
      widgets: [],
      live: true,
      needs_dialog: false
    }
  ];
  await model.drop("o_studio_n_3", "after", LINK);
  expect(model.fieldTarget).toBe(null);
  expect(calls.map((c) => c.method)).toInclude("drop_at");
});
test("the editor's Done sends the field to the held spot, in the drop's vocabulary", async () => {
  const { model, calls } = makeModel();
  await model.drop("o_studio_n_3", "after", LINK);
  await model.addNewField({
    name: "customer",
    string: "Customer",
    ttype: "many2one",
    comodel: "res.partner",
    error: "",
    relatedInfo: null,
    selection: [{ value: "", label: "" }]
  });
  const drop = calls.find((c) => c.method === "drop_at");
  expect(drop?.args?.[2]).toEqual({ token: "o_studio_n_3", position: "after" });
  const values = (drop?.args?.[3]).values;
  expect(values["field_description"]).toBe("Customer");
  expect(values["comodel"]).toBe("res.partner");
  expect(values["string"]).toBe(void 0);
  expect(values["error"]).toBe(void 0);
  expect(values["defined"]).toBe(void 0);
  expect(values["name"]).toBe(void 0);
  expect(values["selection"]).toBe(void 0);
  expect(model.fieldTarget).toBe(null);
});
test("a live field is sent without the class attributes a row cannot hold", async () => {
  const { model } = makeModel();
  const values = model.fieldValues({
    string: "Ref",
    ttype: "char",
    default: '"draft"',
    compute_body: "x = 1",
    depends: "name",
    digits: "(16, 2)",
    help: "Kept"
  });
  expect(values).toEqual({ ttype: "char", help: "Kept", field_description: "Ref" });
  model.context = editingContext({ python_owned: true });
  expect(model.fieldValues({ string: "Ref", ttype: "char", default: "1" })["default"]).toBe("1");
});
test("a staged answer carries the draft, and the ghost is removed through it", async () => {
  const { model, calls } = makeModel();
  const ghost = canvas("v1", ["name", "email", "phone"]);
  ghost.nodes["p_weight"] = {
    ...node("widget", "weight", "o_studio_n_1", 3),
    kind: "pending",
    container: false,
    pending: { draft_id: 9, name: "weight", string: "Weight", ttype: "float", resolved: true }
  };
  ghost.pending = [
    {
      name: "weight",
      label: "Weight",
      ttype: "float",
      widget: "",
      token: "p_weight",
      placed: true,
      resolved: true,
      view_id: 7
    }
  ];
  const draft = draftPayload({
    change_count: 1,
    pending: [pendingChange({ kind: "added", name: "weight" })]
  });
  model.orm = {
    async call(_model, method, args) {
      calls.push({ method, args });
      if (method === "drop_at") {
        return {
          select: "p_weight",
          staged: { name: "weight" },
          canvas: ghost,
          draft
        };
      }
      if (method === "load") {
        return { ...draft, change_count: 0, pending: [] };
      }
      if (method === "canvas") {
        return canvas("v1", ["name", "email", "phone"]);
      }
      return method === "get_addable_fields" ? [] : true;
    },
    async searchRead() {
      return [];
    }
  };
  const result = await model.drop("o_studio_n_3", "after", {
    kind: "new_field",
    values: { ttype: "float", field_description: "New Decimal" }
  });
  expect(result?.staged_field).toBe(true);
  expect(model.draft?.id).toBe(9);
  expect(model.pendingCount).toBe(1);
  expect(model.selection?.token).toBe("p_weight");
  expect(model.tagFor("p_weight")).toBe("Pending · Weight");
  const asked = await model.remove("p_weight", false);
  expect(asked.confirm).toMatch(/Weight/);
  expect(calls.filter((c) => c.method === "remove_at")).toEqual([]);
  await model.remove("p_weight", true);
  const removal = calls.find((c) => c.method === "remove_field");
  expect(removal?.args).toEqual([[9], "weight"]);
  expect(model.pendingCount).toBe(0);
  expect(model.selection).toBe(null);
});
function makeStagedModel({
  reloadMode = "inproc",
  apply
}) {
  const { model, calls, notices, shell } = makeModel();
  const context = editingContext({
    view: { id: 7, name: "", type: "form", model: "x_job", mode: "form" },
    python_owned: true
  });
  model.context = context;
  shell.learned = context;
  const draftPackage = {
    id: 1,
    name: "test",
    writable: true,
    reload_mode: reloadMode
  };
  shell.draft.draft = draftPayload({
    model: "x_job",
    change_count: 1,
    pending: [pendingChange({ kind: "added", name: "weight" })],
    errors: [],
    package: draftPackage
  });
  model.orm = {
    async call(_model, method, args, kwargs) {
      calls.push({ method, args, kwargs });
      switch (method) {
        case "action_apply":
          return apply();
        case "load":
          return { ...model.draft, change_count: 0, pending: [] };
        case "editing_context":
          return { ...context, draft_id: 9 };
        case "canvas":
          return canvas("v2", ["name", "email", "phone", "weight"]);
        case "field_types_for":
        case "get_addable_fields":
          return [];
        case "new_field_plan":
          return { can_create: false };
        default:
          return {};
      }
    },
    async searchRead() {
      return [];
    }
  };
  return { model, calls, notices };
}
test("Apply reloads everything the console knows and says so", async () => {
  const { model, calls, notices } = makeStagedModel({
    apply: () => ({ applied: true, restart_required: false })
  });
  expect(model.pendingCount).toBe(1);
  expect(model.canApply).toBe(true);
  const result = await model.applyDraft(false);
  expect(result).toEqual({ ok: true, restartRequired: false });
  expect(calls.find((c) => c.method === "action_apply")?.args).toEqual([[9], false]);
  const after = calls.map((c) => c.method);
  expect(after.indexOf("load")).toBeGreaterThan(after.indexOf("action_apply"));
  expect(after.indexOf("editing_context")).toBeGreaterThan(after.indexOf("load"));
  expect(after.indexOf("canvas")).toBeGreaterThan(after.indexOf("editing_context"));
  expect(model.archVersion).toBe("v2");
  expect(model.pendingCount).toBe(0);
  expect(model.applying).toBe(false);
  expect(notices.at(-1)).toEqual({ message: "Applied.", type: "success" });
});
test("a refusal to apply comes back as the server's sentence, destructive or not", async () => {
  const refusal = new Error("refused");
  refusal.data = {
    message: "Removing x_old would drop its column; apply anyway to accept that."
  };
  const { model, calls } = makeStagedModel({
    apply: () => {
      throw refusal;
    }
  });
  const result = await model.applyDraft(false);
  if (result.ok) {
    throw new Error("expected a refusal, not ok:true");
  }
  expect(result.message).toMatch(/drop its column/);
  expect(result.destructive).toBe(true);
  expect(calls.map((c) => c.method)).toEqual(["action_apply"]);
  expect(model.pendingCount).toBe(1);
  const again = await model.applyDraft(true);
  if (again.ok) {
    throw new Error("expected a refusal, not ok:true");
  }
  expect(again.destructive).toBe(false);
});
test("where the server cannot reload, Apply writes and says a restart is owed", async () => {
  const { model, calls, notices } = makeStagedModel({
    reloadMode: "manual",
    apply: () => ({ applied: false, restart_required: true, state: "awaiting_restart" })
  });
  expect(model.canApply).toBe(true);
  expect(model.reloadMode).toBe("manual");
  const orm = model.orm;
  const original = (m, method, args, kwargs) => orm.call(m, method, args, kwargs);
  model.orm = {
    ...model.orm,
    async call(m, method, args, kwargs) {
      if (method === "load") {
        calls.push({ method, args, kwargs });
        return { ...model.draft, change_count: 1 };
      }
      return original(m, method, args, kwargs);
    }
  };
  const result = await model.applyDraft(false);
  expect(result).toEqual({ ok: true, restartRequired: true });
  expect(model.pendingCount).toBe(1);
  expect(notices.at(-1)?.type).toBe("info");
  expect(notices.at(-1)?.message).toMatch(/Restart the server/);
});
test("the rest of a written apply is placed once the server is back", async () => {
  const { model, calls } = makeStagedModel({ apply: () => true });
  const orm = model.orm;
  const original = (m, method, args, kwargs) => orm.call(m, method, args, kwargs);
  model.orm = {
    ...model.orm,
    async call(m, method, args, kwargs) {
      if (method === "place_pending") {
        calls.push({ method, args, kwargs });
        return { placed: true, reason: "" };
      }
      return original(m, method, args, kwargs);
    }
  };
  const result = await model.draftModel.placePending();
  expect(result).toEqual({ placed: true, reason: "" });
  expect(calls.find((c) => c.method === "place_pending")?.args).toEqual([[9]]);
  expect(model.pendingCount).toBe(0);
});
test("reveal selects and asks the canvas once; an unknown token does neither", () => {
  const { model } = makeModel();
  expect(model.revealSerial).toBe(0);
  model.reveal("o_studio_n_3");
  expect(model.selection?.token).toBe("o_studio_n_3");
  expect(model.selectionSerial).toBe(1);
  expect(model.revealSerial).toBe(1);
  expect(model.revealToken).toBe("o_studio_n_3");
  model.reveal("o_studio_n_3");
  expect(model.selectionSerial).toBe(1);
  expect(model.revealSerial).toBe(2);
  model.reveal("o_studio_n_99");
  expect(model.selection).toBe(null);
  expect(model.revealSerial).toBe(2);
});
test("the label switch goes the way the form draws the label", async () => {
  const { model, calls } = makeModel();
  const orm = model.orm;
  const call = (m, method, args, kwargs) => orm.call(m, method, args, kwargs);
  const kept = model.canvas;
  model.orm = {
    async call(m, method, args, kwargs) {
      return method === "canvas" ? kept : call(m, method, args, kwargs);
    },
    async searchRead() {
      return [];
    }
  };
  const sent = (method) => {
    const found = calls.find((c) => c.method === method);
    calls.length = 0;
    return found;
  };
  const groupField = kept.nodes["o_studio_n_2"];
  groupField.label = { shown: true, by: "group", token: null, in_group: true };
  await model.setLabelShown("o_studio_n_2", false);
  expect((sent("apply_at")?.args?.[3]).attrs).toEqual({
    nolabel: "1"
  });
  await model.setLabelShown("o_studio_n_2", true);
  expect((sent("apply_at")?.args?.[3]).attrs).toEqual({
    nolabel: null
  });
  const ownField = kept.nodes["o_studio_n_3"];
  ownField.label = { shown: false, by: null, token: null, in_group: false };
  await model.setLabelShown("o_studio_n_3", true);
  expect((sent("show_label_at")?.args?.[2]).token).toBe("o_studio_n_3");
  ownField.label = { shown: true, by: "label", token: "o_studio_n_9", in_group: false };
  await model.setLabelShown("o_studio_n_3", false);
  expect((sent("remove_at")?.args?.[2]).token).toBe("o_studio_n_9");
  expect(await model.setLabelShown("o_studio_n_1", true)).toBe(void 0);
  expect(calls).toEqual([]);
});
