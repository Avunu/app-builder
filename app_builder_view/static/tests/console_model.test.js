/** @odoo-module **/
/**
 * The console model's bookkeeping, against a server that is a function.
 *
 * `console_model.js` is plain -- no Owl, the services handed in -- so what
 * it promises about tokens and versions is pinned here with an `orm` that
 * records its calls and answers with canned canvases. The one promise
 * that matters most: a token is only ever sent with the version of the
 * arch it was minted on, and a gesture held across a replaced canvas --
 * the Button tile's drop, which waits for an action -- is either found
 * again with certainty or let go of, never sent with a fresh version and
 * a stale token.
 */

import { beforeEach, expect, test } from "@odoo/hoot";
import { patchTranslations } from "@web/../tests/web_test_helpers";

import { ConsoleModel } from "@app_builder_view/console/console_model";

beforeEach(() => patchTranslations());

/** What the Button tile stands for when it is dropped: no action yet. */
const BUTTON = { kind: "component", component: "button", values: {} };

function node(tag, name, parent, index, extra = {}) {
    return {
        kind: tag === "form" ? "root" : tag,
        tag,
        name,
        parent,
        index,
        children: [],
        container: tag !== "field",
        selectable: true,
        ...extra,
    };
}

/**
 * A form: a sheet holding `entries` in that order -- a string is a field
 * of that name, a `{tag, name}` any other node, nameless when `name` is
 * left out.
 */
function canvas(version, entries) {
    const nodes = {
        o_studio_n_0: node("form", null, null, 0, { children: ["o_studio_n_1"] }),
        o_studio_n_1: node("sheet", null, "o_studio_n_0", 0, {
            children: entries.map((_, i) => `o_studio_n_${i + 2}`),
        }),
    };
    entries.forEach((entry, i) => {
        const { tag, name } = typeof entry === "string" ? { tag: "field", name: entry } : entry;
        nodes[`o_studio_n_${i + 2}`] = node(tag, name || null, "o_studio_n_1", i);
    });
    return {
        view: { id: 7, type: "form", model: "res.partner" },
        arch_version: version,
        root: "o_studio_n_0",
        nodes,
        history: { undo: [], redo: [] },
    };
}

function makeModel() {
    const calls = [];
    const notices = [];
    let model = null;
    const env = {
        services: {
            orm: {
                // A drop answers with a canvas, as the server does; the
                // same one, since what is pinned here is what was sent.
                async call(_model, method, args, kwargs) {
                    calls.push({ method, args, kwargs });
                    return method === "drop_at" ? { canvas: model.canvas } : {};
                },
            },
            notification: {
                add(message, options) {
                    notices.push({ message: String(message), type: options && options.type });
                },
            },
        },
    };
    model = new ConsoleModel(env, { view_id: 7 });
    model.packageId = 3;
    model._replaceCanvas(canvas("v1", ["name", "email", "phone"]));
    return { model, calls, notices };
}

test("a dropped Button tile is held with the version its token was minted on", async () => {
    const { model, calls } = makeModel();
    const result = await model.drop("o_studio_n_3", "after", BUTTON);
    // Nothing is sent until the palette has an action for it.
    expect(result).toBe(undefined);
    expect(calls).toEqual([]);
    expect(model.buttonTarget.token).toBe("o_studio_n_3");
    expect(model.buttonTarget.position).toBe("after");
    expect(model.buttonTarget.arch_version).toBe("v1");
});

test("the held drop follows its node across a re-stamped canvas", async () => {
    const { model, calls, notices } = makeModel();
    await model.drop("o_studio_n_3", "after", BUTTON);
    // Another field lands before Email: every token after it now names
    // the node one slot over, and `o_studio_n_3` is that new field.
    model._replaceCanvas(canvas("v2", ["name", "x_new", "email", "phone"]));
    expect(model.buttonTarget.token).toBe("o_studio_n_4");
    expect(model.buttonTarget.arch_version).toBe("v2");
    expect(notices).toEqual([]);

    await model.addButton({ string: "Go", action_id: 5 });
    expect(calls).toHaveLength(1);
    expect(calls[0].method).toBe("drop_at");
    // The target sent is Email's token on the canvas on screen, with that
    // canvas's version -- not the token the tile was dropped with.
    expect(calls[0].args[2]).toEqual({ token: "o_studio_n_4", position: "after" });
    expect(calls[0].args[4]).toBe("v2");
    expect(model.buttonTarget).toBe(null);
});

test("the held drop is let go of when its node cannot be found again", async () => {
    const { model, calls, notices } = makeModel();
    await model.drop("o_studio_n_3", "after", BUTTON);
    // Email is gone -- an undo took it out -- and `o_studio_n_3` now
    // names Phone, which is not where the button was dropped.
    model._replaceCanvas(canvas("v2", ["name", "phone"]));
    expect(model.buttonTarget).toBe(null);
    expect(notices).toHaveLength(1);
    expect(notices[0].type).toBe("info");
    expect(notices[0].message).toMatch(/drop the button again/);

    // With no target held, the button goes to the anchor as a click would.
    model.select("o_studio_n_2");
    await model.addButton({ string: "Go", action_id: 5 });
    expect(calls).toHaveLength(1);
    expect(calls[0].args[2]).toEqual({ token: "o_studio_n_2", position: "after" });
    expect(calls[0].args[4]).toBe("v2");
});

test("a target from another version is refused rather than sent", async () => {
    const { model, calls, notices } = makeModel();
    await model.drop("o_studio_n_3", "after", BUTTON);
    // Should a canvas ever be swapped in behind the model's back, the
    // version on the target still says no.
    model.canvas = { ...model.canvas, arch_version: "v9" };
    const result = await model.addButton({ string: "Go", action_id: 5 });
    expect(result).toBe(undefined);
    expect(calls).toEqual([]);
    expect(notices).toHaveLength(1);
    expect(model.buttonTarget).toBe(null);
});

test("a nameless anchor is itself again only while nothing before it moved", async () => {
    const { model, notices } = makeModel();
    // A separator with no name after Email: it can only be known by its place.
    model._replaceCanvas(canvas("v1", ["name", "email", { tag: "separator" }, "phone"]));
    await model.drop("o_studio_n_4", "after", BUTTON);
    // Something changes after it: same token, same place, still it.
    model._replaceCanvas(canvas("v2", ["name", "email", { tag: "separator" }]));
    expect(model.buttonTarget.token).toBe("o_studio_n_4");
    expect(model.buttonTarget.arch_version).toBe("v2");
    expect(notices).toEqual([]);
    // Something lands before it: the token names another node now, and a
    // separator one slot over is not certainly the same one.
    model._replaceCanvas(
        canvas("v3", ["name", { tag: "separator" }, "email", { tag: "separator" }])
    );
    expect(model.buttonTarget).toBe(null);
    expect(notices).toHaveLength(1);
});

test("a named anchor is told from its namesake in a subview by its parent", async () => {
    const { model, notices } = makeModel();
    await model.drop("o_studio_n_3", "after", BUTTON);
    // An embedded list repeats the form's field names under a parent of
    // its own; the one under the sheet is still the one.
    const payload = canvas("v2", ["name", "x_new", "email", "phone", { tag: "list" }]);
    payload.nodes.o_studio_n_7 = node("field", "email", "o_studio_n_6", 0);
    payload.nodes.o_studio_n_6.children = ["o_studio_n_7"];
    model._replaceCanvas(payload);
    expect(model.buttonTarget.token).toBe("o_studio_n_4");
    expect(notices).toEqual([]);
    // Two under the same parent, and there is no telling which.
    model._replaceCanvas(canvas("v3", ["name", "email", "phone", "email"]));
    expect(model.buttonTarget).toBe(null);
    expect(notices).toHaveLength(1);
});

// -- new fields ----------------------------------------------------------------

/** A relation tile: the editor has to ask what it links to first. */
const LINK = { kind: "new_field", values: { ttype: "many2one", field_description: "New Link" } };

test("a dropped field tile that needs the editor is held, not sent", async () => {
    const { model, calls } = makeModel();
    // Nothing from `field_types_for` yet: the built-in list says which
    // types cannot be made from a label alone.
    const result = await model.drop("o_studio_n_3", "after", LINK);
    expect(result).toBe(undefined);
    expect(calls).toEqual([]);
    expect(model.fieldTarget.token).toBe("o_studio_n_3");
    expect(model.fieldTarget.ttype).toBe("many2one");
    expect(model.fieldTarget.arch_version).toBe("v1");
});

test("the server's word on the editor wins over the built-in list", async () => {
    const { model, calls } = makeModel();
    model.fieldTypes = [{ value: "many2one", enabled: true, live: true, needs_dialog: false }];
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
        selection: [{ value: "", label: "" }],
    });
    const drop = calls.find((c) => c.method === "drop_at");
    expect(drop.args[2]).toEqual({ token: "o_studio_n_3", position: "after" });
    const values = drop.args[3].values;
    expect(values.field_description).toBe("Customer");
    expect(values.comodel).toBe("res.partner");
    // The editor's bookkeeping stays behind, and so does a name the live
    // path could not take: the server derives the `x_` one.
    expect(values.string).toBe(undefined);
    expect(values.error).toBe(undefined);
    expect(values.defined).toBe(undefined);
    expect(values.name).toBe(undefined);
    expect(values.selection).toBe(undefined);
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
        help: "Kept",
    });
    expect(values).toEqual({ ttype: "char", help: "Kept", field_description: "Ref" });
    // Staged on a Python-owned model, the same keys are the point.
    model.context = { python_owned: true };
    expect(model.fieldValues({ string: "Ref", ttype: "char", default: "1" }).default).toBe("1");
});

test("a staged answer carries the draft, and the ghost is removed through it", async () => {
    const { model, calls } = makeModel();
    const ghost = canvas("v1", ["name", "email", "phone"]);
    ghost.nodes.p_weight = {
        ...node("widget", "weight", "o_studio_n_1", 3),
        kind: "pending",
        container: false,
        pending: { name: "weight", string: "Weight", ttype: "float" },
    };
    ghost.pending = [{ name: "weight", label: "Weight", ttype: "float", token: "p_weight" }];
    const draft = { id: 9, change_count: 1, pending: [{ kind: "added", name: "weight" }] };
    model.orm.call = async (_model, method, args) => {
        calls.push({ method, args });
        if (method === "drop_at") {
            return { select: "p_weight", staged: { name: "weight" }, canvas: ghost, draft };
        }
        if (method === "load") {
            return { ...draft, change_count: 0, pending: [] };
        }
        if (method === "canvas") {
            return canvas("v1", ["name", "email", "phone"]);
        }
        return method === "get_addable_fields" ? [] : true;
    };
    const result = await model.drop("o_studio_n_3", "after", {
        kind: "new_field",
        values: { ttype: "float", field_description: "New Decimal" },
    });
    expect(result.staged_field).toBe(true);
    expect(model.draft.id).toBe(9);
    expect(model.pendingCount).toBe(1);
    expect(model.selection.token).toBe("p_weight");
    expect(model.tagFor("p_weight")).toBe("Pending · Weight");

    // Removing the ghost is un-staging the field: asked about first, then
    // done on the draft rather than on the arch.
    const asked = await model.remove("p_weight", false);
    expect(asked.confirm).toMatch(/Weight/);
    expect(calls.filter((c) => c.method === "remove_at")).toEqual([]);
    await model.remove("p_weight", true);
    const removal = calls.find((c) => c.method === "remove_field");
    expect(removal.args).toEqual([[9], "weight"]);
    expect(model.pendingCount).toBe(0);
    expect(model.selection).toBe(null);
});

/** A model with a draft on it, and a server that answers every reload. */
function makeStagedModel({ reloadMode = "inproc", apply } = {}) {
    const { model, calls, notices } = makeModel();
    model.context = { view: { id: 7, type: "form", model: "x_job" }, python_owned: true };
    model.draft = {
        id: 9,
        change_count: 1,
        pending: [{ kind: "added", name: "weight" }],
        errors: [],
        package: { writable: true, reload_mode: reloadMode },
    };
    model.orm.call = async (_model, method, args, kwargs) => {
        calls.push({ method, args, kwargs });
        switch (method) {
            case "action_apply":
                return apply();
            case "load":
                return { ...model.draft, change_count: 0, pending: [] };
            case "editing_context":
                return { ...model.context, draft_id: 9 };
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
    };
    return { model, calls, notices };
}

test("Apply reloads everything the console knows and says so", async () => {
    const { model, calls, notices } = makeStagedModel({ apply: () => true });
    expect(model.pendingCount).toBe(1);
    expect(model.canApply).toBe(true);
    const result = await model.applyDraft(false);
    expect(result).toEqual({ ok: true });
    expect(calls.find((c) => c.method === "action_apply").args).toEqual([[9], false]);
    // The context, the canvas and the draft are read again, in that order:
    // the registry was rebuilt, and the arch the canvas shows has moved.
    const after = calls.map((c) => c.method);
    expect(after.indexOf("editing_context")).toBeGreaterThan(after.indexOf("action_apply"));
    expect(after.indexOf("canvas")).toBeGreaterThan(after.indexOf("editing_context"));
    expect(after).toInclude("load");
    expect(model.archVersion).toBe("v2");
    expect(model.pendingCount).toBe(0);
    expect(model.applying).toBe(false);
    expect(notices.at(-1)).toEqual({ message: "Applied.", type: "success" });
});

test("a refusal to apply comes back as the server's sentence, destructive or not", async () => {
    const refusal = new Error("refused");
    refusal.data = { message: "Removing x_old would drop its column; apply anyway to accept that." };
    const { model, calls } = makeStagedModel({
        apply: () => {
            throw refusal;
        },
    });
    const result = await model.applyDraft(false);
    expect(result.ok).toBe(false);
    expect(result.message).toMatch(/drop its column/);
    expect(result.destructive).toBe(true);
    // Nothing was reloaded on a refusal: the console is as it was.
    expect(calls.map((c) => c.method)).toEqual(["action_apply"]);
    expect(model.pendingCount).toBe(1);
    // Accepted the second time, the same sentence is no longer the reason.
    const again = await model.applyDraft(true);
    expect(again.destructive).toBe(false);
});

test("Apply is not offered where the server cannot reload", async () => {
    const { model } = makeStagedModel({ reloadMode: "manual", apply: () => true });
    expect(model.canApply).toBe(false);
    expect(model.applyBlocker).toMatch(/restart/);
});

test("under a restart the console waits for the server, then reads the draft", async () => {
    let up = false;
    const { model, calls } = makeStagedModel({
        reloadMode: "restart",
        apply: () => {
            // The request dies with the server: no `data`, as the RPC
            // layer reports a lost connection.
            throw new Error("connection lost");
        },
    });
    const call = model.orm.call;
    model.orm.call = async (m, method, ...rest) => {
        if (method === "canvas" && !up) {
            up = true;
            throw new Error("connection lost");
        }
        return call(m, method, ...rest);
    };
    model._reconnect = () => ConsoleModel.prototype._reconnect.call(model, [1, 1, 1]);
    const result = await model.applyDraft(false);
    expect(result).toEqual({ ok: true });
    // One probe failed, the next answered, and the reload went on from there.
    expect(calls.filter((c) => c.method === "canvas").length).toBeGreaterThan(1);
    expect(model.pendingCount).toBe(0);
});

test("a restart that outran the placement is finished, not reported as pending", async () => {
    // The package was written and reloaded, the request died before the
    // fields were placed: the draft comes back still counting them.
    const { model, calls, notices } = makeStagedModel({
        reloadMode: "restart",
        apply: () => {
            throw new Error("connection lost");
        },
    });
    let placed = false;
    const call = model.orm.call;
    model.orm.call = async (m, method, ...rest) => {
        if (method === "load" && !placed) {
            return { ...model.draft };
        }
        if (method === "place_pending") {
            calls.push({ method, args: rest[0] });
            placed = true;
            return { placed: true, reason: "" };
        }
        return call(m, method, ...rest);
    };
    model._reconnect = () => ConsoleModel.prototype._reconnect.call(model, [1]);
    const result = await model.applyDraft(false);
    expect(result).toEqual({ ok: true });
    expect(calls.find((c) => c.method === "place_pending").args).toEqual([[9]]);
    expect(model.pendingCount).toBe(0);
    expect(notices.at(-1)).toEqual({ message: "Applied.", type: "success" });
});

test("a restart before the write is still pending, with the server's reason", async () => {
    const { model, calls } = makeStagedModel({
        reloadMode: "restart",
        apply: () => {
            throw new Error("connection lost");
        },
    });
    const call = model.orm.call;
    model.orm.call = async (m, method, ...rest) => {
        if (method === "load") {
            return { ...model.draft };
        }
        if (method === "place_pending") {
            calls.push({ method, args: rest[0] });
            return { placed: false, reason: "x_job does not have weight yet." };
        }
        return call(m, method, ...rest);
    };
    model._reconnect = () => ConsoleModel.prototype._reconnect.call(model, [1]);
    const result = await model.applyDraft(false);
    expect(result.ok).toBe(false);
    expect(result.message).toMatch(/still pending/);
    expect(result.message).toMatch(/does not have weight yet/);
    expect(model.pendingCount).toBe(1);
});
