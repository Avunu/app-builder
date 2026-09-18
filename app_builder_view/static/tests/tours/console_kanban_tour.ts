import { registry } from "@web/core/registry";
import { animationFrame, drag, hover, queryAll, queryFirst, waitFor } from "@odoo/hoot-dom";

/**
 * Building a kanban card by dragging: a field from the palette into the
 * card's body, then that field into the side panel, undone, and the real
 * board showing the result.
 *
 * What makes a kanban its own tour is that the card renders once per
 * record. The zones are laid out on one card -- outlined dashed as the
 * template's stand-in -- and a drop into any card is a drop into the
 * template, so *every* card shows the field afterwards. The second drag
 * starts from one card and ends in another, to see the zones follow the
 * pointer across, and the drop still edit the one template.
 *
 * The drops are aimed at zones by what they say -- the container and its
 * edge, the kind and position -- never by where they are.
 */

/**
 * `queryFirst`'s own JSDoc marks its `options` parameter without
 * `[brackets]`, so TS infers it as required even though the real function
 * reads `arguments.length` itself and works fine with one argument -- the
 * same JSDoc-vs-runtime-arity gap already established a fix for elsewhere
 * in this migration (TYPING.md, "Known traps"; `drag.test.ts`'s own
 * `queryFirstEl`). `queryFirst`/`queryAll` return the DOM lib's own
 * `Element`/`Element[]`, not `HTMLElement`, which is all this file ever
 * needs off them (bounding rects and drag targets only, no
 * `HTMLElement`-only members).
 */
function findFirst(target: string): Element | null {
    return (queryFirst as (target: string) => Element | null)(target);
}

/**
 * `moveTo`'s real position union (`Side | \`${Side}-${Side}\` | Position`,
 * `hoot-dom/helpers/events.js`) has no `"center"` literal, but the real
 * implementation (`getPosition`) computes the exact visual centre for any
 * position string that names neither a horizontal nor a vertical side --
 * a real, working fallback the JSDoc under-documents, the same class of
 * gap already established a fix for elsewhere in this migration
 * (TYPING.md, "Known traps"; `drag.test.ts`'s own `DragHelpersWithCenter`).
 * Widened once here, cast at each of this file's two
 * `moveTo(..., { position: "center" })` call sites.
 */
interface DragHelpersWithCenter {
    cancel: () => Promise<unknown>;
    drop: (to?: unknown, options?: unknown) => Promise<unknown>;
    moveTo: (
        to?: unknown,
        options?: { position?: string; relative?: boolean },
    ) => Promise<DragHelpersWithCenter>;
}

/** Whether `inner` (a DOMRect) sits inside `outer`, give or take `slack`. */
function inside(inner: DOMRect, outer: DOMRect, slack = 4): boolean {
    return (
        inner.left >= outer.left - slack &&
        inner.right <= outer.right + slack &&
        inner.top >= outer.top - slack &&
        inner.bottom <= outer.bottom + slack
    );
}

// hoot's query helpers, not the DOM's: the selectors say `:contains`.
function rectOf(selector: string): DOMRect {
    const el = findFirst(selector);
    if (!el) {
        throw new Error(`nothing matches ${selector}`);
    }
    return el.getBoundingClientRect();
}

/** The dashed outline of the card the zones are laid out on. */
function templateRect(): DOMRect {
    return rectOf(".o_studio_overlay .o_studio_dz_template");
}

function centre(rect: DOMRect): { x: number; y: number } {
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
}

function contains(rect: DOMRect, point: { x: number; y: number }): boolean {
    return (
        point.x >= rect.left &&
        point.x <= rect.right &&
        point.y >= rect.top &&
        point.y <= rect.bottom
    );
}

/** Wait until the template outline is on the card holding `point`. */
async function waitForTemplateOn(point: { x: number; y: number }, frames = 30): Promise<void> {
    for (let i = 0; i < frames; i++) {
        const template = findFirst(".o_studio_overlay .o_studio_dz_template");
        if (template && contains(template.getBoundingClientRect(), point)) {
            return;
        }
        await animationFrame();
    }
    throw new Error("the template outline did not move to the card under the pointer");
}

// Deliberately no `url`: the tour is started against an action created by the
// test, and a url here would override the one start_tour passes.
registry.category("web_tour.tours").add("app_builder_console_kanban_tour", {
    steps: () => [
        {
            content: "a kanban is on screen, with its cards",
            trigger: ".o_kanban_view .o_kanban_record:contains('Card A')",
        },
        {
            content: "open the cog menu",
            trigger: ".o_cp_action_menus button:has(.fa-cog)",
            run: "click",
        },
        {
            content: "edit this kanban",
            trigger: ".o_studio_edit_view",
            run: "click",
        },
        {
            content: "the console renders the real board, cards and all",
            trigger: ".o_studio_canvas .o_kanban_view .o_kanban_record:contains('Card B')",
        },
        {
            content: "the palette offers fields and nothing a card cannot take",
            trigger: ".o_studio_add .o_studio_tile_field[data-name='x_extra']",
            run: function () {
                if (document.querySelector(".o_studio_add .o_studio_tile[data-kind='component']")) {
                    throw new Error("a kanban card takes no form component");
                }
            },
        },
        {
            content: "the board has real records, so nothing says sample data",
            trigger: ".o_studio_canvas",
            run: function () {
                if (document.querySelector(".o_studio_canvas_note")) {
                    throw new Error("the sample-data note is for a model without records");
                }
            },
        },
        {
            // A tile is in no card, so the zones are laid out on the first
            // card the user can see, and that card is outlined as the one
            // standing in for the template.
            content: "drag a field from the palette to the end of the card's body",
            trigger: ".o_studio_tile_field.o_studio_draggable[data-name='x_extra']",
            run: async function () {
                const { drop, moveTo } = (await drag(
                    this.anchor,
                )) as unknown as DragHelpersWithCenter;
                await animationFrame();
                await hover(this.anchor, { position: { top: 20, left: 20 }, relative: true });
                await animationFrame();
                await waitFor(".o_studio_overlay .o_studio_dropzone", {
                    visible: true,
                    timeout: 1000,
                });
                const template = templateRect();
                const first = rectOf(".o_studio_canvas .o_kanban_record:contains('Card A')");
                if (!contains(template, centre(first))) {
                    throw new Error("the first card should be outlined as the template");
                }
                for (const zone of queryAll(".o_studio_overlay .o_studio_dropzone")) {
                    if (!inside(zone.getBoundingClientRect(), template)) {
                        throw new Error("every zone should be laid out on the template card");
                    }
                }
                const zone = await waitFor(
                    ".o_studio_overlay .o_studio_dropzone[data-container-kind='main'][data-edge='end']",
                    { visible: true, timeout: 1000 },
                );
                await moveTo(zone, { position: "center" });
                await animationFrame();
                await drop();
                await animationFrame();
            },
        },
        {
            content: "every card shows the field: the template was edited once",
            trigger:
                ".o_studio_canvas .o_kanban_record:contains('Card A') main span:contains('Extra A')",
        },
        {
            content: "the second card too",
            trigger:
                ".o_studio_canvas .o_kanban_record:contains('Card B') main span:contains('Extra B')",
        },
        {
            content: "and it is selected, with the properties open",
            trigger: ".o_studio_sidebar_tab.active[data-tab='properties']",
        },
        {
            content: "the selection frame names it",
            trigger: ".o_studio_overlay .o_studio_tag:contains('Extra')",
        },
        {
            content: "the drag is over: no zone and no template outline is left behind",
            trigger: ".o_studio_canvas",
            run: function () {
                if (
                    document.querySelector(
                        ".o_studio_overlay .o_studio_dropzone, .o_studio_overlay .o_studio_dz_template",
                    )
                ) {
                    throw new Error("drop zones should go with the drag");
                }
            },
        },
        {
            // Picked up in the second card, dropped in the first: the zones
            // are laid out on the card the field came from, then on the
            // card the pointer crosses into -- and the drop edits the one
            // template either way.
            content: "move the field from the body of one card into the side panel of another",
            trigger:
                ".o_studio_canvas .o_kanban_record:contains('Card B') main span:contains('Extra B')",
            run: async function () {
                const { drop, moveTo } = (await drag(
                    this.anchor,
                )) as unknown as DragHelpersWithCenter;
                await animationFrame();
                await hover(this.anchor, { position: { top: 2, left: 2 }, relative: true });
                await animationFrame();
                await waitFor(".o_studio_overlay .o_studio_dropzone", {
                    visible: true,
                    timeout: 1000,
                });
                const second = rectOf(".o_studio_canvas .o_kanban_record:contains('Card B')");
                if (!contains(templateRect(), centre(second))) {
                    throw new Error("the zones should start on the card the field came from");
                }
                const first = findFirst(".o_studio_canvas .o_kanban_record:contains('Card A')");
                await moveTo(first, { position: "center" });
                await animationFrame();
                if (!first) {
                    throw new Error(
                        "nothing matches .o_studio_canvas .o_kanban_record:contains('Card A')",
                    );
                }
                const target = centre(first.getBoundingClientRect());
                await waitForTemplateOn(target);
                const zone = await waitFor(
                    ".o_studio_overlay .o_studio_dropzone[data-kind='aside'][data-position='inside']",
                    { visible: true, timeout: 1000 },
                );
                if (!inside(zone.getBoundingClientRect(), first.getBoundingClientRect())) {
                    throw new Error("the side panel zone should be the first card's");
                }
                await moveTo(zone, { position: "center" });
                await animationFrame();
                await drop();
                await animationFrame();
            },
        },
        {
            content: "the field is in the side panel of every card",
            trigger:
                ".o_studio_canvas .o_kanban_record:contains('Card A') aside span:contains('Extra A')",
        },
        {
            content: "and no longer in the body",
            trigger:
                ".o_studio_canvas .o_kanban_record:contains('Card B'):has(aside span:contains('Extra B')):not(:has(main span:contains('Extra B')))",
        },
        {
            content: "undo the move",
            trigger: ".o_studio_top_bar .o_studio_undo:not(:disabled)",
            run: "click",
        },
        {
            content: "the field is back in the body",
            trigger:
                ".o_studio_canvas .o_kanban_record:contains('Card A') main span:contains('Extra A')",
        },
        {
            content: "the console says saved",
            trigger: ".o_studio_top_bar .o_studio_status_saved",
        },
        {
            content: "close the console",
            trigger: ".o_studio_top_bar .o_studio_close",
            run: "click",
        },
        {
            content: "back on the real board",
            trigger: ".o_kanban_view:not(.o_studio_canvas *)",
        },
        {
            // Value and all: Close runs the board's action again rather
            // than restoring a controller that would read its records with
            // the field set it was opened with. The console is gone by
            // now, so the board is the only one on the page.
            content: "whose cards carry the field, with its value",
            trigger:
                ".o_kanban_view .o_kanban_record:contains('Card A') main span:contains('Extra A')",
        },
    ],
});

/**
 * The same board with no records: the canvas shows sample cards and says
 * so, and a drop into one still edits the template -- the arch changes,
 * not the data. The views fade sample records and take the pointer away
 * from them; the canvas gives both back, or there would be nothing to
 * aim at.
 */
registry.category("web_tour.tours").add("app_builder_console_kanban_sample_tour", {
    steps: () => [
        {
            content: "an empty kanban is on screen",
            trigger: ".o_kanban_view",
        },
        {
            content: "open the cog menu",
            trigger: ".o_cp_action_menus button:has(.fa-cog)",
            run: "click",
        },
        {
            content: "edit this kanban",
            trigger: ".o_studio_edit_view",
            run: "click",
        },
        {
            content: "the canvas shows sample cards, and says they are samples",
            trigger: ".o_studio_canvas .o_kanban_record:not(.o_kanban_ghost) main",
        },
        {
            content: "the note is on the canvas",
            trigger: ".o_studio_canvas .o_studio_canvas_note:contains('Sample data')",
        },
        {
            content: "the sample cards are there to be pointed at, not faded away",
            trigger: ".o_studio_canvas .o_kanban_record:not(.o_kanban_ghost)",
            run: function () {
                const style = window.getComputedStyle(this.anchor);
                if (Number(style.opacity) < 0.9 || style.pointerEvents === "none") {
                    throw new Error(
                        "sample cards should be as visible and as clickable as real ones",
                    );
                }
            },
        },
        {
            content: "drag a field from the palette to the end of the card's body",
            trigger: ".o_studio_tile_field.o_studio_draggable[data-name='x_extra']",
            run: "drag_and_drop .o_studio_overlay .o_studio_dropzone[data-container-kind='main'][data-edge='end']",
        },
        {
            // Sample data has no value for a field it does not know by
            // name, so the span is empty -- and, to a tour, invisible.
            content: "every sample card carries a third field in its body",
            trigger:
                ".o_studio_canvas .o_kanban_record:not(.o_kanban_ghost) main > span:nth-child(3):not(:visible)",
        },
        {
            content: "and it is selected",
            trigger: ".o_studio_overlay .o_studio_tag:contains('Extra')",
        },
        {
            content: "close the console",
            trigger: ".o_studio_top_bar .o_studio_close",
            run: "click",
        },
        {
            content: "back on the real board",
            trigger: ".o_kanban_view:not(.o_studio_canvas *)",
        },
    ],
});
