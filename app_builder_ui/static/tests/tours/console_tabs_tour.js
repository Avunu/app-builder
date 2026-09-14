import { registry } from "@web/core/registry";

/**
 * The tabs this addon puts on the console, used the way a person does:
 * open the console on a list, click Automations, land on the automations
 * of that model with the console one breadcrumb back, and come back to a
 * console that is as it was.
 *
 * The last step is the one worth having. A tab that opened the right list
 * and lost the console on the way back would cost more than a tab that did
 * nothing: the user would be dropped in Settings → Technical, which is
 * exactly the distance the tab exists to remove.
 */
// Deliberately no `url`: the tour is started against an action created by the
// test, and a url here would override the one start_tour passes.
registry.category("web_tour.tours").add("app_builder_console_tabs_tour", {
    steps: () => [
        {
            content: "the list view itself is on screen",
            trigger: ".o_list_view",
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
            content: "the console opened on that view",
            trigger: ".o_studio_console .o_studio_top_bar",
        },
        {
            content: "the canvas renders the real list",
            trigger: ".o_studio_canvas .o_list_view th[data-name='display_name']",
        },
        {
            content: "every tab of this addon is offered on a model's view",
            trigger: ".o_studio_top_bar .o_studio_top_tab[data-tab='automations']",
            run: function () {
                for (const key of ["automations", "webhooks", "access", "rules", "edit_menu"]) {
                    if (!document.querySelector(`.o_studio_top_tab[data-tab='${key}']`)) {
                        throw new Error(`the ${key} tab is missing from the top bar`);
                    }
                }
            },
        },
        {
            content: "open the Automations tab",
            trigger: ".o_studio_top_bar .o_studio_top_tab[data-tab='automations']",
            run: "click",
        },
        {
            content: "the automations list of that model is on screen",
            trigger: ".o_last_breadcrumb_item:contains('Automations')",
        },
        {
            content: "the list is not the console's canvas",
            trigger: ".o_action_manager .o_list_view",
            run: function () {
                if (document.querySelector(".o_studio_console")) {
                    throw new Error("the console should have been left for the list");
                }
            },
        },
        {
            content: "the list shows the model's automation",
            trigger: ".o_list_view .o_data_row:contains('Tour Partner Rule')",
        },
        {
            content: "and not another model's",
            trigger: ".o_list_view:not(:has(.o_data_row:contains('Tour Other Rule')))",
        },
        {
            content: "the console is one breadcrumb back",
            trigger: ".o_breadcrumb .breadcrumb-item:contains('Edit list view')",
            run: "click",
        },
        {
            content: "the console is back",
            trigger: ".o_studio_console .o_studio_top_bar",
        },
        {
            content: "with its canvas rendering the same list",
            trigger: ".o_studio_canvas .o_list_view th[data-name='display_name']",
        },
        {
            content: "and its tabs still offered",
            trigger: ".o_studio_top_bar .o_studio_top_tab[data-tab='automations']",
        },
    ],
});
