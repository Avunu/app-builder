import { registry } from "@web/core/registry";

/**
 * Editing a view the way a person does: open a list, pick "Edit this view",
 * click a column heading, rename it, and see the heading change.
 *
 * The last step is the one worth having. Everything before it can pass while
 * the edit goes nowhere -- the arch is written, the file is written, and the
 * user still stares at the old column because the preview cached the view.
 */
// Deliberately no `url`: the tour is started against an action created by the
// test, and a url here would override the one start_tour passes -- landing on
// the apps home with no list view in sight.
registry.category("web_tour.tours").add("app_builder_view_editor_tour", {
    steps: () => [
        {
            content: "the list view itself is on screen",
            trigger: ".o_list_view",
        },
        {
            content: "the cog menu is present at all",
            trigger: ".o_cp_action_menus",
        },
        {
            content: "open the cog menu of a real list view",
            trigger: ".o_cp_action_menus button:has(.fa-cog)",
            run: "click",
        },
        {
            content: "the studio entry is offered on an ordinary view",
            trigger: ".o_studio_edit_view",
            run: "click",
        },
        {
            content: "the editor opened on that view",
            trigger: ".o_studio_view_editor .o_studio_view_editor_bar",
        },
        {
            content: "nothing is selected yet, so it says what to do",
            trigger: ".o_studio_view_editor_side:contains('Click anything in the view')",
        },
        {
            content: "a core view is reported as inheriting, not rewritten",
            trigger: ".o_studio_view_editor_bar .badge:contains('inheriting view')",
        },
        {
            content: "click a column heading in the live preview",
            trigger: ".o_studio_view_editor_preview th[data-name='display_name']",
            run: "click",
        },
        {
            content: "the sidebar offers that column's options",
            trigger: ".o_studio_view_editor_side:contains('Column heading')",
        },
        {
            content: "rename the column",
            trigger: ".o_studio_view_editor_side input.form-control-sm",
            run: "edit Full Name && press Tab",
        },
        {
            content: "the live preview shows the new heading",
            trigger:
                ".o_studio_view_editor_preview th[data-name='display_name']:contains('Full Name')",
        },
        {
            content: "select the view itself for its own settings",
            trigger: ".o_studio_view_editor_bar button:contains('Select the view itself')",
            run: "click",
        },
        {
            content: "root options are offered",
            trigger: ".o_studio_view_editor_side:contains('Edit rows inline')",
        },
        {
            content: "the change is listed as undoable",
            trigger: ".o_studio_view_editor_side:contains('Recent changes')",
        },
        {
            content: "undo it",
            trigger: ".o_studio_view_editor_bar button:contains('Undo')",
            run: "click",
        },
        {
            content: "the heading is back to what it was",
            trigger:
                ".o_studio_view_editor_preview th[data-name='display_name']:not(:contains('Full Name'))",
        },
    ],
});

/**
 * The same spine on a form: click a field, make it required *on this form*, and
 * click a notebook tab to rename it.
 *
 * The tab is the interesting one. Every other click is swallowed so the live
 * view does not act on it, but a tab has to still switch pages -- selecting a
 * page you cannot bring into view would mean editing something you cannot see.
 */
registry.category("web_tour.tours").add("app_builder_form_editor_tour", {
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
            content: "the editor opened on the form",
            trigger: ".o_studio_view_editor_bar .badge:contains('form')",
        },
        {
            content: "click a field in the live form",
            trigger: ".o_studio_view_editor_preview .o_field_widget[name='function']",
            run: "click",
        },
        {
            content: "field options are offered, including form-only required",
            trigger: ".o_studio_view_editor_side:contains('Required')",
        },
        {
            content: "click the second notebook tab",
            trigger: ".o_studio_view_editor_preview .o_notebook .nav-link:eq(1)",
            run: "click",
        },
        {
            content: "the tab actually switched, rather than only being selected",
            trigger: ".o_studio_view_editor_preview .o_notebook .nav-link:eq(1).active",
        },
        {
            content: "and its options are offered",
            trigger: ".o_studio_view_editor_side:contains('Tab name')",
        },
        {
            content: "rename the tab",
            trigger: ".o_studio_view_editor_side input.form-control-sm",
            run: "edit Renamed Tab && press Tab",
        },
        {
            content: "the live form shows the new tab name",
            trigger: ".o_studio_view_editor_preview .o_notebook .nav-link:contains('Renamed Tab')",
        },
    ],
});
