import { registry } from "@web/core/registry";
import { animationFrame, delay, drag, hover, waitFor } from "@odoo/hoot-dom";

/**
 * Building a form by dragging: a field from the palette between two fields,
 * a group and two columns onto the end of the sheet, a tab onto the notebook,
 * a field of the view into the empty group, a field across tabs by resting
 * on the tab -- and one drag let go of with a key, which changes nothing.
 *
 * Every drop is aimed at a zone by what it says -- `data-name` and
 * `data-position`, or the container and edge -- never by where it is, so
 * the tour reads as the user's intent and survives the view being laid out
 * differently. The zones exist only while something is dragged, which is
 * why the drag helper hovers before it looks for one.
 */
// Deliberately no `url`: the tour is started against an action created by the
// test, and a url here would override the one start_tour passes.
registry.category("web_tour.tours").add("app_builder_console_drag_tour", {
    steps: () => [
        {
            content: "a form is on screen",
            trigger: ".o_form_view",
        },
        {
            content: "open the cog menu",
            trigger: ".o_cp_action_menus button:has(.fa-cog)",
            run: "click",
        },
        {
            content: "edit this form",
            trigger: ".o_studio_edit_view",
            run: "click",
        },
        {
            content: "the console opened on the form, on the record",
            trigger: ".o_studio_canvas .o_form_view .o_field_widget[name='name']:contains('Tour Subject')",
        },
        {
            content: "nothing on the palette is a native drag source",
            trigger: ".o_studio_add",
            run: function () {
                if (document.querySelector(".o_studio_console [draggable='true']")) {
                    throw new Error("a native draggable would keep the pointer drag from starting");
                }
            },
        },
        {
            content: "drag an existing field from the palette to just after Job Position",
            trigger: ".o_studio_tile_field.o_studio_draggable[data-name='x_tour_extra']",
            run: "drag_and_drop .o_studio_overlay .o_studio_dropzone[data-name='function'][data-position='after']",
        },
        {
            content: "the field landed on the canvas",
            trigger: ".o_studio_canvas .o_field_widget[name='x_tour_extra']",
        },
        {
            content: "and is selected, with the properties open",
            trigger: ".o_studio_sidebar_tab.active[data-tab='properties']",
        },
        {
            content: "the selection frame names it",
            trigger: ".o_studio_overlay .o_studio_tag:contains('Tour Extra')",
        },
        {
            content: "the drag is over: no zone is left behind",
            trigger: ".o_studio_canvas",
            run: function () {
                if (document.querySelector(".o_studio_overlay .o_studio_dropzone")) {
                    throw new Error("drop zones should go with the drag");
                }
                if (document.body.classList.contains("o_studio_dragging")) {
                    throw new Error("the body should no longer be marked as dragging");
                }
            },
        },
        {
            content: "back to the Add tab",
            trigger: ".o_studio_sidebar_tab[data-tab='add']",
            run: "click",
        },
        {
            content: "drag a group onto the end of the sheet",
            trigger: ".o_studio_tile.o_studio_draggable[data-component='group']",
            run: "drag_and_drop .o_studio_overlay .o_studio_dropzone[data-container-kind='sheet'][data-edge='end']",
        },
        {
            content: "the new, empty group is selected and has a grip",
            trigger: ".o_studio_overlay .o_studio_selection:not([hidden]):has(.o_studio_tag:contains('Group')) .o_studio_grip:not([hidden])",
        },
        {
            content: "move Job Position from its group into the empty one",
            trigger: ".o_studio_canvas .o_field_widget[name='function']",
            run: "drag_and_drop .o_studio_overlay .o_studio_dropzone[data-position='inside'][data-kind='group']",
        },
        {
            content: "the field is now in the group at the sheet level",
            trigger: ".o_studio_canvas .o_form_sheet > .o_inner_group .o_field_widget[name='function']",
        },
        {
            content: "and no longer in the group it came from",
            trigger: ".o_studio_canvas .o_group .o_inner_group:has(.o_field_widget[name='title']):not(:has(.o_field_widget[name='function']))",
        },
        {
            content: "back to the Add tab",
            trigger: ".o_studio_sidebar_tab[data-tab='add']",
            run: "click",
        },
        {
            content: "drag two columns onto the end of the sheet",
            trigger: ".o_studio_tile.o_studio_draggable[data-component='columns']",
            run: "drag_and_drop .o_studio_overlay .o_studio_dropzone[data-container-kind='sheet'][data-edge='end']",
        },
        {
            content: "a second outer group is on the sheet, with two columns in it",
            trigger: ".o_studio_canvas .o_form_sheet > .o_group:eq(1)",
            run: function () {
                const columns = this.anchor.querySelectorAll(":scope > .o_inner_group");
                if (columns.length !== 2) {
                    throw new Error(`expected two columns, found ${columns.length}`);
                }
            },
        },
        {
            content: "back to the Add tab",
            trigger: ".o_studio_sidebar_tab[data-tab='add']",
            run: "click",
        },
        {
            content: "drag a tab onto the end of the notebook's tab strip",
            trigger: ".o_studio_tile.o_studio_draggable[data-component='page']",
            run: "drag_and_drop .o_studio_overlay .o_studio_dropzone[data-container-kind='notebook'][data-edge='end']",
        },
        {
            content: "the notebook has the new tab",
            trigger: ".o_studio_canvas .o_notebook .nav-link:contains('New tab')",
        },
        {
            content: "and it is what is selected",
            trigger: ".o_studio_overlay .o_studio_tag:contains('Tab')",
        },
        {
            // The body takes no pointer events during a drag, so the tab
            // cannot be hovered: resting on it is what switches the page.
            content: "carry the field to another tab by resting on the tab",
            trigger: ".o_studio_canvas .o_field_widget[name='x_tour_extra']",
            run: async function () {
                const { drop, moveTo } = await drag(this.anchor);
                await animationFrame();
                await hover(this.anchor, { position: { top: 20, left: 20 }, relative: true });
                await animationFrame();
                await waitFor(".o_studio_overlay .o_studio_dropzone", { visible: true, timeout: 1000 });
                const tab = document.querySelector(
                    ".o_studio_canvas .o_notebook .nav-link[name='sales_purchases']"
                );
                await moveTo(tab, { position: "center" });
                await delay(400);
                await animationFrame();
                const zone = await waitFor(
                    ".o_studio_overlay .o_studio_dropzone[data-name='purchase'][data-position='inside']",
                    { visible: true, timeout: 2000 }
                );
                await moveTo(zone, { position: "center" });
                await animationFrame();
                await drop();
                await animationFrame();
            },
        },
        {
            content: "the field is in the Purchase group of the other tab",
            trigger: ".o_studio_canvas .o_notebook .nav-link[name='sales_purchases'].active",
        },
        {
            content: "rendered in that tab's pane",
            trigger: ".o_studio_canvas .o_notebook .tab-pane .o_inner_group:has(.o_field_widget[name='x_tour_extra'])",
        },
        {
            content: "back to the Add tab",
            trigger: ".o_studio_sidebar_tab[data-tab='add']",
            run: "click",
        },
        {
            content: "a drag given up with a key drops nothing",
            trigger: ".o_studio_tile_field.o_studio_draggable[data-name='x_tour_second']",
            run: async function () {
                const { moveTo, cancel } = await drag(this.anchor);
                await animationFrame();
                await hover(this.anchor, { position: { top: 20, left: 20 }, relative: true });
                await animationFrame();
                const zone = await waitFor(
                    ".o_studio_overlay .o_studio_dropzone[data-name='vat'][data-position='after']",
                    { visible: true, timeout: 1000 }
                );
                await moveTo(zone, { position: "center" });
                await animationFrame();
                // The helper's own cancel: it presses Escape *and* lets go
                // of the button it holds, so the next drag can start.
                await cancel();
                await animationFrame();
                if (document.querySelector(".o_studio_overlay .o_studio_dropzone")) {
                    throw new Error("the zones should go with the cancelled drag");
                }
                // A drop sent by mistake would show as the pill saving for
                // its round trip, and as the field once it came back: give
                // it time to show, then look for both.
                await delay(300);
                await animationFrame();
                if (document.querySelector(".o_studio_top_bar .o_studio_status_saving")) {
                    throw new Error("a cancelled drag must not send a drop");
                }
                if (document.querySelector(".o_studio_canvas .o_field_widget[name='x_tour_second']")) {
                    throw new Error("a cancelled drag must not drop");
                }
            },
        },
        {
            content: "the console still says saved",
            trigger: ".o_studio_top_bar .o_studio_status_saved",
        },
        // A field dropped on the sheet itself, outside any group, is where
        // the form draws no label: the drop gives it one of its own, and
        // the panel's switch takes it away and brings it back.
        {
            content: "drop the same field on the sheet, after a group",
            trigger: ".o_studio_tile_field.o_studio_draggable[data-name='x_tour_second']",
            run: "drag_and_drop .o_studio_overlay .o_studio_dropzone[data-container-kind='sheet'][data-kind='group'][data-position='after']",
        },
        {
            content: "it renders on the sheet, with a label of its own before it",
            trigger: ".o_studio_canvas .o_form_sheet > label.o_form_label:contains('Tour Second') + .o_field_widget[name='x_tour_second']",
        },
        {
            content: "the panel says so, with the switch on",
            trigger: ".o_studio_properties .o_studio_row[data-row='show_label'] input:checked",
        },
        {
            content: "switch the label off",
            trigger: ".o_studio_properties .o_studio_row[data-row='show_label'] input:checked",
            run: "click",
        },
        {
            content: "the field renders bare once the canvas has followed",
            trigger: ".o_studio_canvas .o_form_sheet:has(.o_field_widget[name='x_tour_second']):not(:has(label.o_form_label:contains('Tour Second')))",
        },
        {
            content: "and the panel says why",
            trigger: ".o_studio_properties .o_studio_row[data-row='show_label'] .o_studio_label_note:contains('outside a group')",
        },
        {
            content: "and back on",
            trigger: ".o_studio_properties .o_studio_row[data-row='show_label'] input:not(:checked)",
            run: "click",
        },
        {
            content: "a label of its own stands before the field again",
            trigger: ".o_studio_canvas .o_form_sheet > label.o_form_label:contains('Tour Second') + .o_field_widget[name='x_tour_second']",
        },
        {
            content: "rename it from the Label row",
            trigger: ".o_studio_properties .o_studio_row[data-row='string'] input",
            run: "edit Second Label && press Tab",
        },
        {
            content: "the label on the sheet follows",
            trigger: ".o_studio_canvas .o_form_sheet > label.o_form_label:contains('Second Label')",
        },
        {
            content: "saved",
            trigger: ".o_studio_top_bar .o_studio_status_saved",
        },
        {
            content: "close the console",
            trigger: ".o_studio_top_bar .o_studio_close",
            run: "click",
        },
        {
            content: "back on the real form",
            trigger: ".o_form_view:not(.o_studio_canvas *)",
        },
    ],
});

/**
 * A list's headings are its drag sources and the gaps between them its
 * zones: a column moved before another, and a field from the palette
 * dropped between two headings.
 */
registry.category("web_tour.tours").add("app_builder_console_list_drag_tour", {
    steps: () => [
        {
            content: "the list view itself is on screen",
            trigger: ".o_list_view",
        },
        {
            content: "open the cog menu",
            trigger: ".o_cp_action_menus button:has(.fa-cog)",
            run: "click",
        },
        {
            content: "edit this view",
            trigger: ".o_studio_edit_view",
            run: "click",
        },
        {
            content: "the canvas renders the real list",
            trigger: ".o_studio_canvas .o_list_view th[data-name='email']",
        },
        {
            content: "drag the Email heading before Name",
            trigger: ".o_studio_canvas th[data-name='email']",
            run: "drag_and_drop .o_studio_overlay .o_studio_dropzone[data-name='display_name'][data-position='before']",
        },
        {
            content: "Email is now the first column",
            trigger: ".o_studio_canvas th[data-name='email'] + th[data-name='display_name']",
        },
        {
            content: "and the list did not sort itself on the way",
            trigger: ".o_studio_canvas .o_list_view",
            run: function () {
                if (document.querySelector(".o_studio_canvas th.table-active")) {
                    throw new Error("a drag from a heading must not sort the list");
                }
            },
        },
        {
            content: "open the Add tab",
            trigger: ".o_studio_sidebar_tab[data-tab='add']",
            run: "click",
        },
        {
            content: "drop a field from the palette between Name and the next heading",
            trigger: ".o_studio_tile_field.o_studio_draggable[data-name='x_tour_extra']",
            run: "drag_and_drop .o_studio_overlay .o_studio_dropzone[data-name='display_name'][data-position='after']",
        },
        {
            content: "the new column follows Name",
            trigger: ".o_studio_canvas th[data-name='display_name'] + th[data-name='x_tour_extra']",
        },
        {
            content: "close the console",
            trigger: ".o_studio_top_bar .o_studio_close",
            run: "click",
        },
        {
            content: "back on the real list, which shows the new order",
            trigger: ".o_list_view:not(.o_studio_canvas *) th[data-name='email'] + th[data-name='display_name']",
        },
    ],
});
