import { registry } from "@web/core/registry";

/**
 * The panes this addon puts on the console, used the way a person does:
 * open the console on a list, click Automations, see the automations of
 * that model -- and only those -- inside the console, and come back to a
 * canvas that is as it was.
 *
 * The console never leaves the screen: a pane that sent the user to a
 * plain list would cost more than a pane that did nothing, since the
 * distance to Settings → Technical is exactly what the pane exists to
 * remove.
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
            content: "every pane of this addon is offered on a model's view",
            trigger: ".o_studio_top_bar .o_studio_top_tab[data-tab='automations']",
            run: function () {
                for (const key of ["automations", "webhooks", "access", "rules", "menu"]) {
                    if (!document.querySelector(`.o_studio_top_tab[data-tab='${key}']`)) {
                        throw new Error(`the ${key} tab is missing from the top bar`);
                    }
                }
            },
        },
        {
            content: "open the Automations pane",
            trigger: ".o_studio_top_bar .o_studio_top_tab[data-tab='automations']",
            run: "click",
        },
        {
            content: "the pane is on screen, inside the console",
            trigger: ".o_studio_console .o_studio_console_body[data-pane='automations'] .o_studio_record_pane",
            run: function () {
                if (document.querySelector(".o_studio_canvas")) {
                    throw new Error("the canvas should have made way for the pane");
                }
                if (!document.querySelector(".o_studio_top_tab[data-tab='automations'].active")) {
                    throw new Error("the Automations tab should be the active one");
                }
            },
        },
        {
            content: "the pane lists the model's automation",
            trigger: ".o_studio_record_pane .o_studio_card:contains('Tour Partner Rule')",
        },
        {
            content: "and not another model's",
            trigger: ".o_studio_record_pane:not(:has(.o_studio_card:contains('Tour Other Rule')))",
        },
        {
            content: "back to the Views pane",
            trigger: ".o_studio_top_bar .o_studio_top_tab[data-tab='views']",
            run: "click",
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
