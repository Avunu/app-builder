/** @odoo-module **/
/**
 * The console model's bookkeeping, against a server that is a function.
 *
 * `console_model.ts` is plain -- no Owl, the services handed in -- so what
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
import { DraftModel } from "@app_builder_view/console/shell/draft_model";
import type {
    CanvasPayload,
    DragPayload,
    FieldDefLite,
    FieldService,
    NodeKind,
    NotificationService,
    OrmService,
    StudioNode,
    Token,
} from "@app_builder_view/console/types";
import type {
    DraftPackageJSON,
    DraftPayload,
    EditingContext,
    PendingChangeJSON,
} from "@app_builder_view/console/wire";

beforeEach(() => patchTranslations());

/** What the Button tile stands for when it is dropped: no action yet. */
const BUTTON: DragPayload = { kind: "component", component: "button", values: {} };

/**
 * A `StudioNode` with inert defaults for every field this file's own
 * fixtures never read, following the same house pattern as cluster 1's
 * test builders (`zones.test.ts`, `outline_tree.test.ts`): a *declared
 * function return type* gets tsc's more lenient literal-assignability,
 * which is why this works through a function but would not as a bare
 * `as StudioNode` on the object literal itself. `tag` accepts any string
 * -- a couple of fixtures below use one ("list") that is not a real
 * `NodeKind`, only ever exercising `_findAgain`'s own tag/name matching,
 * never read as a `NodeKind` by anything this file asserts on.
 */
function node(
    tag: string,
    name: string | null,
    parent: Token | null,
    index: number,
    extra: Partial<StudioNode> = {},
): StudioNode {
    return {
        kind: (tag === "form" ? "root" : tag) as NodeKind,
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
        ...extra,
    };
}

/** One entry of a `canvas()` fixture: a bare string is a field of that
 * name, otherwise any other kind of node, nameless when `name` is left
 * out. */
type CanvasEntry = string | { tag: string; name?: string };

/**
 * A form: a sheet holding `entries` in that order.
 */
function canvas(version: string, entries: CanvasEntry[]): CanvasPayload {
    const nodes: Record<Token, StudioNode> = {
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
        record_count: 0,
    };
}

/** An `EditingContext` with inert defaults for every field this file
 * never reads -- the same builder-with-defaults pattern as `node`/
 * `canvas` above, needed here for the same reason: a partial literal
 * (`{python_owned: true}`) shares too few of `EditingContext`'s ~14
 * fields to satisfy tsc's "sufficiently overlaps" check on a bare `as`. */
function editingContext(overrides: Partial<EditingContext> = {}): EditingContext {
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
        preview: null,
        options: null,
        catalogue: null,
        groups: null,
        owned: false,
        packages: null,
        suggested_package_id: false,
        ...overrides,
    };
}

/** A `DraftPayload` with inert defaults, same reasoning as `editingContext`. */
function draftPayload(overrides: Partial<DraftPayload> = {}): DraftPayload {
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
        ...overrides,
    };
}

function pendingChange(
    overrides: Partial<PendingChangeJSON> & { kind: PendingChangeJSON["kind"] },
): PendingChangeJSON {
    return { name: "", detail: "", ...overrides };
}

interface RecordedCall {
    method: string;
    args?: unknown[] | undefined;
    kwargs?: Record<string, unknown> | undefined;
}

interface Notice {
    message: string;
    type: string | undefined;
}

/**
 * What both `ConsoleModel` and `DraftModel` read off the fake shell they
 * share -- the union of `ConsoleModelOwner` and `DraftModelOwner`, since
 * one object here plays both roles, the way the real `StudioShell` does.
 * Not `extends` both: the two disagree on `packageId`'s own type
 * (`number | false` vs. `number | false | null`) since each was traced
 * to its own file's real reads rather than to a shared vocabulary: this
 * test never needs `null`, so the narrower of the two is declared here,
 * itself assignable everywhere either owner interface is asked for.
 */
interface FakeShell {
    packageId: number | false;
    modelName: string | null;
    modelLabel: string;
    learned: EditingContext;
    draft: DraftModel;
    learnContext(context: EditingContext): Promise<void>;
    readonly pythonOwned: boolean;
}

function makeModel(): {
    model: ConsoleModel;
    calls: RecordedCall[];
    notices: Notice[];
    shell: FakeShell;
} {
    const calls: RecordedCall[] = [];
    const notices: Notice[] = [];
    // `orm.call`'s closure below reads `model`, declared with `const`
    // further down (after `shell`, which `model` itself needs) -- legal
    // and safe: a closure may reference a block-scoped binding declared
    // later in the same scope, as long as nothing calls the closure
    // before that declaration runs, and nothing here does -- `orm.call`
    // is only ever invoked once a test calls a method on the
    // fully-constructed `model` this function returns.
    const orm: OrmService = {
        // A drop answers with a canvas, as the server does; the same one,
        // since what is pinned here is what was sent.
        async call<T = unknown>(
            _model: string,
            method: string,
            args?: unknown[],
            kwargs?: Record<string, unknown>,
        ): Promise<T> {
            calls.push({ method, args, kwargs });
            return (method === "drop_at" ? { canvas: model.canvas } : {}) as T;
        },
        async searchRead<T = unknown>(): Promise<T[]> {
            return [];
        },
    };
    const notification: NotificationService = {
        add(message: unknown, options?: { type?: string }) {
            notices.push({ message: String(message), type: options && options.type });
        },
    };
    const field: FieldService = {
        async loadFields(): Promise<Record<string, FieldDefLite>> {
            throw new Error("not exercised in this test");
        },
        async loadPath() {
            throw new Error("not exercised in this test");
        },
    };
    const env = {
        services: { orm, notification, field },
        bus: { trigger: () => undefined },
    };
    // The shell the Views pane's model reads through: the package in the
    // top bar, the model on the crumb, the draft; nothing else is asked.
    const shell: FakeShell = {
        packageId: 3,
        modelName: "res.partner",
        modelLabel: "Contact",
        learned: editingContext(),
        async learnContext(context: EditingContext): Promise<void> {
            this.learned = context;
            this.modelName = context.view.model || null;
            this.draft.setHints(context);
        },
        get pythonOwned(): boolean {
            return Boolean(this.learned.python_owned);
        },
        // Replaced on the next line -- `DraftModel`'s own constructor
        // needs `shell` already in hand, so the circular reference is
        // resolved the same two-step way the real `StudioShell` resolves
        // it in its own constructor.
        draft: null as unknown as DraftModel,
    };
    shell.draft = new DraftModel(env, shell);
    const model: ConsoleModel = new ConsoleModel(env, shell);
    model.params = { view_id: 7, model: false, view_type: false, res_id: false };
    model._replaceCanvas(canvas("v1", ["name", "email", "phone"]));
    return { model, calls, notices, shell };
}

test("a dropped Button tile is held with the version its token was minted on", async () => {
    const { model, calls } = makeModel();
    const result = await model.drop("o_studio_n_3", "after", BUTTON);
    // Nothing is sent until the palette has an action for it.
    expect(result).toBe(undefined);
    expect(calls).toEqual([]);
    expect(model.buttonTarget?.token).toBe("o_studio_n_3");
    expect(model.buttonTarget?.position).toBe("after");
    expect(model.buttonTarget?.arch_version).toBe("v1");
});

test("the held drop follows its node across a re-stamped canvas", async () => {
    const { model, calls, notices } = makeModel();
    await model.drop("o_studio_n_3", "after", BUTTON);
    // Another field lands before Email: every token after it now names
    // the node one slot over, and `o_studio_n_3` is that new field.
    model._replaceCanvas(canvas("v2", ["name", "x_new", "email", "phone"]));
    expect(model.buttonTarget?.token).toBe("o_studio_n_4");
    expect(model.buttonTarget?.arch_version).toBe("v2");
    expect(notices).toEqual([]);

    await model.addButton({ string: "Go", action_id: 5 });
    expect(calls).toHaveLength(1);
    expect(calls[0]?.method).toBe("drop_at");
    // The target sent is Email's token on the canvas on screen, with that
    // canvas's version -- not the token the tile was dropped with.
    expect(calls[0]?.args?.[2]).toEqual({ token: "o_studio_n_4", position: "after" });
    expect(calls[0]?.args?.[4]).toBe("v2");
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
    expect(notices[0]?.type).toBe("info");
    expect(notices[0]?.message).toMatch(/drop the button again/);

    // With no target held, the button goes to the anchor as a click would.
    model.select("o_studio_n_2");
    await model.addButton({ string: "Go", action_id: 5 });
    expect(calls).toHaveLength(1);
    expect(calls[0]?.args?.[2]).toEqual({ token: "o_studio_n_2", position: "after" });
    expect(calls[0]?.args?.[4]).toBe("v2");
});

test("a target from another version is refused rather than sent", async () => {
    const { model, calls, notices } = makeModel();
    await model.drop("o_studio_n_3", "after", BUTTON);
    // Should a canvas ever be swapped in behind the model's back, the
    // version on the target still says no.
    model.canvas = { ...(model.canvas as CanvasPayload), arch_version: "v9" };
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
    expect(model.buttonTarget?.token).toBe("o_studio_n_4");
    expect(model.buttonTarget?.arch_version).toBe("v2");
    expect(notices).toEqual([]);
    // Something lands before it: the token names another node now, and a
    // separator one slot over is not certainly the same one.
    model._replaceCanvas(
        canvas("v3", ["name", { tag: "separator" }, "email", { tag: "separator" }]),
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
    // `nodes` is `Readonly` on `CanvasPayload` -- the client never writes
    // it -- but this fixture needs one more node than `canvas()`'s own
    // `entries` list can express (a nested subview field); cast away the
    // readonly-ness for this one construction step only.
    const mutableNodes = payload.nodes as Record<Token, StudioNode>;
    mutableNodes["o_studio_n_7"] = node("field", "email", "o_studio_n_6", 0);
    (mutableNodes["o_studio_n_6"] as StudioNode).children = ["o_studio_n_7"];
    model._replaceCanvas(payload);
    expect(model.buttonTarget?.token).toBe("o_studio_n_4");
    expect(notices).toEqual([]);
    // Two under the same parent, and there is no telling which.
    model._replaceCanvas(canvas("v3", ["name", "email", "phone", "email"]));
    expect(model.buttonTarget).toBe(null);
    expect(notices).toHaveLength(1);
});

// -- new fields ----------------------------------------------------------------

/** A relation tile: the editor has to ask what it links to first. */
const LINK: DragPayload = {
    kind: "new_field",
    values: { ttype: "many2one", field_description: "New Link" },
};

test("a dropped field tile that needs the editor is held, not sent", async () => {
    const { model, calls } = makeModel();
    // Nothing from `field_types_for` yet: the built-in list says which
    // types cannot be made from a label alone.
    const result = await model.drop("o_studio_n_3", "after", LINK);
    expect(result).toBe(undefined);
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
            needs_dialog: false,
        },
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
        selection: [{ value: "", label: "" }],
    });
    const drop = calls.find((c) => c.method === "drop_at");
    expect(drop?.args?.[2]).toEqual({ token: "o_studio_n_3", position: "after" });
    const values = (drop?.args?.[3] as { values: Record<string, unknown> }).values;
    expect(values["field_description"]).toBe("Customer");
    expect(values["comodel"]).toBe("res.partner");
    // The editor's bookkeeping stays behind, and so does a name the live
    // path could not take: the server derives the `x_` one.
    expect(values["string"]).toBe(undefined);
    expect(values["error"]).toBe(undefined);
    expect(values["defined"]).toBe(undefined);
    expect(values["name"]).toBe(undefined);
    expect(values["selection"]).toBe(undefined);
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
    model.context = editingContext({ python_owned: true });
    expect(model.fieldValues({ string: "Ref", ttype: "char", default: "1" })["default"]).toBe("1");
});

test("a staged answer carries the draft, and the ghost is removed through it", async () => {
    const { model, calls } = makeModel();
    const ghost = canvas("v1", ["name", "email", "phone"]);
    (ghost.nodes as Record<Token, StudioNode>)["p_weight"] = {
        ...node("widget", "weight", "o_studio_n_1", 3),
        kind: "pending",
        container: false,
        pending: { draft_id: 9, name: "weight", string: "Weight", ttype: "float", resolved: true },
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
            view_id: 7,
        },
    ];
    const draft = draftPayload({
        change_count: 1,
        pending: [pendingChange({ kind: "added", name: "weight" })],
    });
    model.orm = {
        async call<T = unknown>(_model: string, method: string, args?: unknown[]): Promise<T> {
            calls.push({ method, args });
            if (method === "drop_at") {
                return {
                    select: "p_weight",
                    staged: { name: "weight" },
                    canvas: ghost,
                    draft,
                } as T;
            }
            if (method === "load") {
                return { ...draft, change_count: 0, pending: [] } as T;
            }
            if (method === "canvas") {
                return canvas("v1", ["name", "email", "phone"]) as T;
            }
            return (method === "get_addable_fields" ? [] : true) as T;
        },
        async searchRead<T = unknown>(): Promise<T[]> {
            return [];
        },
    };
    const result = await model.drop("o_studio_n_3", "after", {
        kind: "new_field",
        values: { ttype: "float", field_description: "New Decimal" },
    });
    expect(result?.staged_field).toBe(true);
    expect(model.draft?.id).toBe(9);
    expect(model.pendingCount).toBe(1);
    expect(model.selection?.token).toBe("p_weight");
    expect(model.tagFor("p_weight")).toBe("Pending · Weight");

    // Removing the ghost is un-staging the field: asked about first, then
    // done on the draft rather than on the arch.
    const asked = (await model.remove("p_weight", false)) as { confirm: string };
    expect(asked.confirm).toMatch(/Weight/);
    expect(calls.filter((c) => c.method === "remove_at")).toEqual([]);
    await model.remove("p_weight", true);
    const removal = calls.find((c) => c.method === "remove_field");
    expect(removal?.args).toEqual([[9], "weight"]);
    expect(model.pendingCount).toBe(0);
    expect(model.selection).toBe(null);
});

/** A model with a draft on it, and a server that answers every reload. */
function makeStagedModel({
    reloadMode = "inproc",
    apply,
}: {
    reloadMode?: string;
    apply: () => unknown;
}): { model: ConsoleModel; calls: RecordedCall[]; notices: Notice[] } {
    const { model, calls, notices, shell } = makeModel();
    const context = editingContext({
        view: { id: 7, name: "", type: "form", model: "x_job", mode: "form" },
        python_owned: true,
    });
    model.context = context;
    shell.learned = context;
    const draftPackage: DraftPackageJSON = {
        id: 1,
        name: "test",
        writable: true,
        reload_mode: reloadMode,
    };
    shell.draft.draft = draftPayload({
        model: "x_job",
        change_count: 1,
        pending: [pendingChange({ kind: "added", name: "weight" })],
        errors: [],
        package: draftPackage,
    });
    model.orm = {
        async call<T = unknown>(
            _model: string,
            method: string,
            args?: unknown[],
            kwargs?: Record<string, unknown>,
        ): Promise<T> {
            calls.push({ method, args, kwargs });
            switch (method) {
                case "action_apply":
                    return apply() as T;
                case "load":
                    return { ...(model.draft as DraftPayload), change_count: 0, pending: [] } as T;
                case "editing_context":
                    return { ...context, draft_id: 9 } as T;
                case "canvas":
                    return canvas("v2", ["name", "email", "phone", "weight"]) as T;
                case "field_types_for":
                case "get_addable_fields":
                    return [] as T;
                case "new_field_plan":
                    return { can_create: false } as T;
                default:
                    return {} as T;
            }
        },
        async searchRead<T = unknown>(): Promise<T[]> {
            return [];
        },
    };
    return { model, calls, notices };
}

test("Apply reloads everything the console knows and says so", async () => {
    const { model, calls, notices } = makeStagedModel({
        apply: () => ({ applied: true, restart_required: false }),
    });
    expect(model.pendingCount).toBe(1);
    expect(model.canApply).toBe(true);
    const result = await model.applyDraft(false);
    expect(result).toEqual({ ok: true, restartRequired: false });
    expect(calls.find((c) => c.method === "action_apply")?.args).toEqual([[9], false]);
    // The draft is read first, then the context and the canvas: the
    // registry was rebuilt, and the arch the canvas shows has moved.
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
    const refusal = new Error("refused") as Error & { data: { message: string } };
    refusal.data = {
        message: "Removing x_old would drop its column; apply anyway to accept that.",
    };
    const { model, calls } = makeStagedModel({
        apply: () => {
            throw refusal;
        },
    });
    const result = await model.applyDraft(false);
    if (result.ok) {
        throw new Error("expected a refusal, not ok:true");
    }
    expect(result.message).toMatch(/drop its column/);
    expect(result.destructive).toBe(true);
    // Nothing was reloaded on a refusal: the console is as it was.
    expect(calls.map((c) => c.method)).toEqual(["action_apply"]);
    expect(model.pendingCount).toBe(1);
    // Accepted the second time, the same sentence is no longer the reason.
    const again = await model.applyDraft(true);
    if (again.ok) {
        throw new Error("expected a refusal, not ok:true");
    }
    expect(again.destructive).toBe(false);
});

test("where the server cannot reload, Apply writes and says a restart is owed", async () => {
    const { model, calls, notices } = makeStagedModel({
        reloadMode: "manual",
        apply: () => ({ applied: false, restart_required: true, state: "awaiting_restart" }),
    });
    // Staging and applying both work; the pill says what the apply costs.
    expect(model.canApply).toBe(true);
    expect(model.reloadMode).toBe("manual");
    // Wrapped rather than extracted (`const original = model.orm.call`):
    // `unbound-method` flags a bare method reference on principle, even
    // though this particular mock never reads `this` -- wrapping keeps
    // the generic `<T>` this file's own calls below need, which a plain
    // `.bind()` would have erased (`Function.prototype.bind`'s own
    // typing is not generic-preserving).
    const orm = model.orm;
    const original = <T = unknown>(
        m: string,
        method: string,
        args?: unknown[],
        kwargs?: Record<string, unknown>,
    ): Promise<T> => orm.call<T>(m, method, args, kwargs);
    model.orm = {
        ...model.orm,
        async call<T = unknown>(
            m: string,
            method: string,
            args?: unknown[],
            kwargs?: Record<string, unknown>,
        ): Promise<T> {
            if (method === "load") {
                // Written, not loaded: the draft stays dirty until the restart.
                calls.push({ method, args, kwargs });
                return { ...(model.draft as DraftPayload), change_count: 1 } as T;
            }
            return original<T>(m, method, args, kwargs);
        },
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
    const original = <T = unknown>(
        m: string,
        method: string,
        args?: unknown[],
        kwargs?: Record<string, unknown>,
    ): Promise<T> => orm.call<T>(m, method, args, kwargs);
    model.orm = {
        ...model.orm,
        async call<T = unknown>(
            m: string,
            method: string,
            args?: unknown[],
            kwargs?: Record<string, unknown>,
        ): Promise<T> {
            if (method === "place_pending") {
                calls.push({ method, args, kwargs });
                return { placed: true, reason: "" } as T;
            }
            return original<T>(m, method, args, kwargs);
        },
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
    // The same node again: still a request to bring it on screen, and
    // not a new selection.
    model.reveal("o_studio_n_3");
    expect(model.selectionSerial).toBe(1);
    expect(model.revealSerial).toBe(2);
    model.reveal("o_studio_n_99");
    expect(model.selection).toBe(null);
    expect(model.revealSerial).toBe(2);
});

test("the label switch goes the way the form draws the label", async () => {
    const { model, calls } = makeModel();
    // An edit that answers with no canvas has the model fetch one, which
    // the recorded orm answers with the canvas as it is; the request is
    // looked for by name rather than taken as the last call.
    const orm = model.orm;
    const call = <T = unknown>(
        m: string,
        method: string,
        args?: unknown[],
        kwargs?: Record<string, unknown>,
    ): Promise<T> => orm.call<T>(m, method, args, kwargs);
    const kept = model.canvas as CanvasPayload;
    model.orm = {
        async call<T = unknown>(
            m: string,
            method: string,
            args?: unknown[],
            kwargs?: Record<string, unknown>,
        ): Promise<T> {
            return method === "canvas" ? (kept as T) : call<T>(m, method, args, kwargs);
        },
        async searchRead<T = unknown>(): Promise<T[]> {
            return [];
        },
    };
    const sent = (method: string): RecordedCall | undefined => {
        const found = calls.find((c) => c.method === method);
        calls.length = 0;
        return found;
    };
    // In a group: the `nolabel` attribute, off and on.
    const groupField = kept.nodes["o_studio_n_2"] as StudioNode;
    groupField.label = { shown: true, by: "group", token: null, in_group: true };
    await model.setLabelShown("o_studio_n_2", false);
    expect((sent("apply_at")?.args?.[3] as { attrs: Record<string, unknown> }).attrs).toEqual({
        nolabel: "1",
    });
    await model.setLabelShown("o_studio_n_2", true);
    expect((sent("apply_at")?.args?.[3] as { attrs: Record<string, unknown> }).attrs).toEqual({
        nolabel: null,
    });
    // Elsewhere: a <label for> of its own, made, then taken away by its token.
    const ownField = kept.nodes["o_studio_n_3"] as StudioNode;
    ownField.label = { shown: false, by: null, token: null, in_group: false };
    await model.setLabelShown("o_studio_n_3", true);
    expect((sent("show_label_at")?.args?.[2] as { token: Token }).token).toBe("o_studio_n_3");
    ownField.label = { shown: true, by: "label", token: "o_studio_n_9", in_group: false };
    await model.setLabelShown("o_studio_n_3", false);
    expect((sent("remove_at")?.args?.[2] as { token: Token }).token).toBe("o_studio_n_9");
    // Not a field with a label switch: nothing is sent.
    expect(await model.setLabelShown("o_studio_n_1", true)).toBe(undefined);
    expect(calls).toEqual([]);
});
