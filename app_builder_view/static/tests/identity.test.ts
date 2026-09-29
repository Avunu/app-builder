/** @odoo-module **/
/**
 * Token <-> DOM, on views the real compilers rendered.
 *
 * `identity.js` rests on one contract with the web client: the `class` of
 * an arch node reaches the element that renders it, except in the places
 * the module says it does not -- a list heading, a generated label, a
 * kanban card that renders once per record. These tests mount the stock
 * form, list and kanban from a hand-stamped arch and check both halves of
 * the contract: that a token walks up to the node it was minted on, and
 * that the module's exceptions are the real ones.
 *
 * The tokens are written into the arch by hand and the node table beside
 * them, since the server that stamps them is not part of a hoot run; they
 * follow `canvas_stamp.py` -- ordinals in document order, a `column` kind
 * for a list field, a `card` kind for the template.
 */

import { expect, test } from "@odoo/hoot";
import { queryFirst, queryOne } from "@odoo/hoot-dom";
import {
    defineModels,
    fields,
    getMockEnv,
    makeMockEnv,
    MockServer,
    models,
    mountWithCleanup,
    onRpc,
} from "@web/../tests/web_test_helpers";

import { View } from "@web/views/view";
import * as compat from "@app_builder_view/console/compat";
import {
    elementsFor,
    instanceAt,
    ownToken,
    rectFor,
    tabFor,
    tokenOf,
} from "@app_builder_view/console/identity";
import type { NodeKind, NodeTable, StudioNode, Token } from "@app_builder_view/console/types";

/**
 * The one shape read off hoot's mock server here: `MockServer.env` is the
 * vendored Proxy-backed server environment (`mock_server.js:makeServerEnv`),
 * whose model handles come back through the vendor "error" type. A model's
 * `fields_get()` (`mock_model.js`) returns its field-definition map.
 */
interface MockModelHandle {
    fields_get(): Record<string, Record<string, unknown>>;
}

// `queryFirst`'s JSDoc marks its second `options` param required (no
// `[options]` brackets, and its own declared type excludes `undefined`),
// but the real function (`hoot-dom/helpers/dom.js`) destructures
// `arguments` itself and never branches on its length (unlike
// `Registry.get`, where omitting a 2nd arg changes behavior) -- a
// one-argument call is confirmed identical to passing no options.
const findFirst = queryFirst as (target: string) => Element | null;

class Partner extends models.Model {
    // `mock_fields.js`'s `makeFieldGenerator` self-indexes its return value
    // with a non-literal key, so every generator (`Char`, `Integer`, ...)
    // reads back as `(...) => FieldDefinition | undefined` under
    // `noUncheckedIndexedAccess` even though it always exists at runtime.
    name = fields.Char!();
    sequence = fields.Integer!();
    // `Model` (hoot's mock-server base class) already declares an instance
    // `_records` field of its own, so `noImplicitOverride` requires the
    // modifier here even though nothing about this field's runtime
    // behavior changes.
    override _records = [
        { id: 1, name: "Ada", sequence: 1 },
        { id: 2, name: "Grace", sequence: 2 },
    ];
}

defineModels([Partner]);

// The control panel's cog menu and the list's export button ask the user
// service for groups; the mock server has no `res.users` to answer with.
onRpc("has_group", () => true);

async function mountArch(
    type: "form" | "list" | "kanban",
    arch: string,
    extra: Record<string, unknown> = {},
) {
    if (!getMockEnv()) {
        await makeMockEnv();
    }
    // `MockServer.env` is `this.current?.env`, so the vendor getter's own
    // inferred type carries the `| undefined` of that optional chain; and
    // `MockServerEnvironment` (`MockServerBaseEnvironment & { [modelName:
    // string]: Model }`) reaches a model only through that index signature,
    // so both `noPropertyAccessFromIndexSignature` (bracket, not dot) and
    // `noUncheckedIndexedAccess` (a second `!`) apply. Both `!`s trust the
    // same runtime fact the original untyped call did: a mock env exists
    // here, one line after `makeMockEnv()`/`getMockEnv()` confirmed it.
    const modelFields = (MockServer.env as unknown as Record<string, MockModelHandle>)[
        "partner"
    ]!.fields_get();
    const props = {
        type,
        resModel: "partner",
        arch,
        fields: modelFields,
        relatedModels: { partner: { fields: modelFields } },
        context: {},
        noBreadcrumbs: true,
        display: { controlPanel: false },
        ...extra,
    };
    return mountWithCleanup(View, { props });
}

const FORM_ARCH = `
    <form class="o_studio_n_0">
        <sheet class="o_studio_n_1">
            <group class="o_studio_n_2">
                <group class="o_studio_n_3">
                    <field name="name" class="o_studio_n_4"/>
                </group>
            </group>
            <notebook class="o_studio_n_5">
                <page name="notes" string="Notes" class="o_studio_n_6">
                    <field name="sequence" class="o_studio_n_7"/>
                </page>
            </notebook>
        </sheet>
    </form>`;

/**
 * Only `kind`/`name` (plus whatever `extra` a caller adds) are ever real
 * data here -- `identity.ts`'s functions under test read nothing else.
 * The rest of `StudioNode`'s dozen-plus required fields get inert
 * defaults so the *table* can be a real `NodeTable`, not a per-literal
 * cast that has to paper over how little of `StudioNode` each entry
 * actually populates (that cast does not typecheck: a bare `{kind,
 * name}` and a full `StudioNode` do not "sufficiently overlap" as far
 * as tsc's excess/missing-property check for `as` is concerned).
 */
function node(kind: NodeKind, name: string | null, extra: Partial<StudioNode> = {}): StudioNode {
    return {
        tag: "",
        name,
        kind,
        parent: null,
        children: [],
        index: 0,
        string: null,
        container: false,
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

function nodeTable(entries: Record<Token, StudioNode>): NodeTable {
    return entries;
}

const FORM_NODES = nodeTable({
    o_studio_n_0: node("root", null),
    o_studio_n_1: node("sheet", null),
    o_studio_n_2: node("group", null),
    o_studio_n_3: node("group", null),
    o_studio_n_4: node("field", "name"),
    o_studio_n_5: node("notebook", null),
    o_studio_n_6: node("page", "notes"),
    o_studio_n_7: node("field", "sequence"),
});

test("form: a field, its generated label, the groups and the sheet", async () => {
    await mountArch("form", FORM_ARCH, { resId: 1, ...compat.readonlyViewProps() });
    const root = queryOne(".o_form_view");
    expect(ownToken(root)).toBe("o_studio_n_0");
    const widget = queryOne(".o_field_widget[name='name']");
    expect(ownToken(widget)).toBe("o_studio_n_4");

    // A click lands on the text inside the widget, not the widget itself.
    const inner = widget.querySelector("span") || widget.firstElementChild || widget;
    expect(tokenOf(inner, FORM_NODES)).toEqual({ token: "o_studio_n_4", el: widget });
    expect(elementsFor("o_studio_n_4", root, FORM_NODES)).toEqual([widget]);

    // The label the group generated carries the group's classes, not the
    // field's: a click on it is a click on the widget beside it.
    const label = queryOne("label.o_form_label");
    expect(ownToken(label)).toBe(null);
    expect(tokenOf(label, FORM_NODES)).toEqual({ token: "o_studio_n_4", el: widget });
    // And the outline covers the label too.
    const rect = rectFor(FORM_NODES["o_studio_n_4"], widget)!;
    expect(rect.left).toBeLessThan(widget.getBoundingClientRect().left + 1);
    expect(rect.left).toBeLessThan(label.getBoundingClientRect().left + 1);

    const inner_group = queryOne(".o_inner_group");
    expect(tokenOf(inner_group, FORM_NODES)).toEqual({ token: "o_studio_n_3", el: inner_group });
    const outer = queryOne(".o_group");
    expect(tokenOf(outer, FORM_NODES)).toEqual({ token: "o_studio_n_2", el: outer });
    expect(elementsFor("o_studio_n_2", root, FORM_NODES)).toEqual([outer]);

    // The sheet's class lands on the background that also holds the
    // header; the outline is the inner sheet's.
    const bg = queryOne(".o_form_sheet_bg");
    const sheet = queryOne(".o_form_sheet");
    expect(ownToken(bg)).toBe("o_studio_n_1");
    expect(ownToken(sheet)).toBe(null);
    expect(tokenOf(sheet, FORM_NODES)).toEqual({ token: "o_studio_n_1", el: bg });
    const sheetRect = rectFor(FORM_NODES["o_studio_n_1"], bg)!;
    const innerRect = sheet.getBoundingClientRect();
    expect(sheetRect.top).toBe(innerRect.top);
    expect(sheetRect.left).toBe(innerRect.left);
    expect(sheetRect.width).toBe(innerRect.width);
});

test("form: a notebook page is its tab link", async () => {
    await mountArch("form", FORM_ARCH, { resId: 1, ...compat.readonlyViewProps() });
    const root = queryOne(".o_form_view");
    const link = queryOne(".o_notebook .nav-link");
    expect(link).toHaveAttribute("name", "notes");
    expect(ownToken(link)).toBe("o_studio_n_6");
    expect(tokenOf(link, FORM_NODES)).toEqual({ token: "o_studio_n_6", el: link });
    // `tabFor` returns `HTMLElement | null` now (`identity.ts`, widened for
    // `canvas.ts`'s own `.click()`); `queryOne` itself stays the plain,
    // non-generic `Element` hoot-dom always returns.
    expect(tabFor("o_studio_n_6", root)).toBe(link as HTMLElement);
    expect(elementsFor("o_studio_n_6", root, FORM_NODES)).toEqual([link]);
    expect(ownToken(queryOne(".o_notebook"))).toBe("o_studio_n_5");
    // The field on the page resolves like any other.
    const widget = queryOne(".o_field_widget[name='sequence']");
    expect(tokenOf(widget, FORM_NODES)).toEqual({ token: "o_studio_n_7", el: widget });
});

test("list: a heading is mapped by name through the node table", async () => {
    const arch = `
        <list class="o_studio_n_0">
            <field name="name" class="o_studio_n_1"/>
            <field name="sequence" class="o_studio_n_2"/>
        </list>`;
    const nodes = nodeTable({
        o_studio_n_0: node("root", null),
        o_studio_n_1: node("column", "name"),
        o_studio_n_2: node("column", "sequence"),
    });
    await mountArch("list", arch);
    const root = queryOne(".o_list_view");
    const heading = queryOne("th[data-name='name']");
    // The class never reaches the heading: `th` is built from the name.
    expect(ownToken(heading)).toBe(null);
    expect(tokenOf(heading, nodes)).toEqual({ token: "o_studio_n_1", el: heading });
    // A click on the text inside the heading is a click on the heading.
    const text = heading.querySelector("span") || heading.firstElementChild || heading;
    expect(tokenOf(text, nodes)).toEqual({ token: "o_studio_n_1", el: heading });
    expect(elementsFor("o_studio_n_1", root, nodes)).toEqual([heading]);
    expect(elementsFor("o_studio_n_2", root, nodes)).toEqual([
        queryOne("th[data-name='sequence']"),
    ]);
    // A heading the table does not know -- the selector column -- is a
    // click on nothing addressable, which walks up to the view's root: the
    // root's class is carried onto the view container itself.
    expect(ownToken(root)).toBe("o_studio_n_0");
    const selector = findFirst("th.o_list_record_selector") || heading.parentElement;
    expect(tokenOf(selector, nodes)).toEqual({ token: "o_studio_n_0", el: root });
});

test("kanban: a bare field is a span, once per record", async () => {
    const arch = `
        <kanban class="o_studio_n_0">
            <templates>
                <t t-name="card" class="o_studio_n_1">
                    <field name="name" class="o_studio_n_2"/>
                </t>
            </templates>
        </kanban>`;
    const nodes = nodeTable({
        o_studio_n_0: node("root", null),
        o_studio_n_1: node("card", "card"),
        o_studio_n_2: node("field", "name"),
    });
    await mountArch("kanban", arch);
    const root = queryOne(".o_kanban_view");
    const spans = elementsFor("o_studio_n_2", root, nodes);
    expect(spans).toHaveLength(2);
    expect(spans.map((el) => el.tagName)).toEqual(["SPAN", "SPAN"]);
    expect(spans.map((el) => el.textContent)).toEqual(["Ada", "Grace"]);
    expect(tokenOf(spans[1], nodes)).toEqual({ token: "o_studio_n_2", el: spans[1]! });

    // The card template's class lands on every rendered record.
    const cards = elementsFor("o_studio_n_1", root, nodes);
    expect(cards).toHaveLength(2);
    expect(cards.every((el) => el.classList.contains("o_kanban_record"))).toBe(true);
    expect(tokenOf(spans[0]!.parentElement, nodes)!.token).toBe("o_studio_n_1");

    // The instance under the pointer is the one that counts.
    const second = spans[1]!.getBoundingClientRect();
    const point = { x: second.left + 1, y: second.top + 1 };
    expect(instanceAt("o_studio_n_2", root, nodes, point)).toBe(spans[1]!);
    expect(instanceAt("o_studio_n_2", root, nodes, null)).toBe(spans[0]!);
    expect(rectFor(nodes["o_studio_n_1"], cards[1]!)!.top).toBe(
        cards[1]!.getBoundingClientRect().top,
    );
});
