import { registry } from "@web/core/registry";

/**
 * An automation made the way a person makes one: from the pane's New,
 * with a template, a name and a condition; then its steps added, moved
 * and taken away from the sidebar. The server test that starts this tour
 * checks the file afterwards -- the tour only proves the screen.
 */
registry.category("web_tour.tours").add("app_builder_automations_pane_tour", {
    steps: () => [
        {
            content: "open the cog menu of a real list view",
            trigger: ".o_cp_action_menus button:has(.fa-cog)",
            run: "click",
        },
        {
            content: "the studio entry",
            trigger: ".o_studio_edit_view",
            run: "click",
        },
        {
            content: "open the Automations pane",
            trigger: ".o_studio_top_bar .o_studio_top_tab[data-tab='automations']",
            run: "click",
        },
        {
            content: "nothing yet: the empty state offers the templates",
            trigger:
                ".o_studio_record_pane .o_studio_pane_empty .o_studio_pane_template[data-template='set_field']",
            run: "click",
        },
        {
            content: "the inline New form asks for a name",
            trigger: ".o_studio_create_card .o_studio_row[data-row='name'] input",
            run: "edit Tour Set Field",
        },
        {
            content: "and a condition, typed as source",
            trigger:
                ".o_studio_create_card .o_studio_row[data-row='filter_domain'] .o_studio_domain_source",
            run: "click",
        },
        {
            content: "the condition itself",
            trigger: ".o_studio_create_card .o_studio_row[data-row='filter_domain'] textarea",
            run: "edit [('is_company', '=', True)]",
        },
        {
            content: "create it",
            trigger: ".o_studio_create_card .o_studio_create_confirm",
            run: "click",
        },
        {
            content: "the card is on screen, selected, with its sentence",
            trigger:
                ".o_studio_record_card.selected:contains('Tour Set Field') .o_studio_record_sentence:contains('Update')",
        },
        {
            content: "the sidebar shows the template's step",
            trigger:
                ".o_studio_record_sidebar .o_studio_children .o_studio_child_title:contains('Update')",
        },
        {
            content: "add a second step",
            trigger: ".o_studio_record_sidebar .o_studio_child_add",
            run: "selectByLabel Execute Code",
        },
        {
            content: "it opens itself, with its code",
            trigger:
                ".o_studio_record_sidebar .o_studio_child.open:nth-child(3) .o_studio_row[data-row='code']",
        },
        {
            content: "move it up",
            trigger: ".o_studio_record_sidebar .o_studio_child.open .o_studio_child_up",
            run: "click",
        },
        {
            content: "the code step is first now",
            trigger:
                ".o_studio_record_sidebar .o_studio_child:nth-child(2):contains('Execute Code')",
        },
        {
            content: "and the sentence follows the order",
            trigger:
                ".o_studio_record_card.selected .o_studio_record_sentence:contains('Execute Code · Update')",
        },
        {
            content: "remove the update step",
            trigger: ".o_studio_record_sidebar .o_studio_child:nth-child(3) .o_studio_child_remove",
            run: "click",
        },
        {
            content: "confirm",
            trigger: ".modal .btn-primary",
            run: "click",
        },
        {
            content: "one step left",
            trigger:
                ".o_studio_record_sidebar .o_studio_children:not(:has(.o_studio_child_title:contains('Update')))",
        },
        {
            content: "switch the rule off from its row",
            trigger: ".o_studio_record_sidebar .o_studio_row[data-row='active'] input",
            run: "click",
        },
        {
            content: "the card dims and the list hides it behind the Inactive switch",
            trigger:
                ".o_studio_record_pane:not(:has(.o_studio_record_card:contains('Tour Set Field')))",
        },
        {
            content: "show inactive",
            trigger: ".o_studio_pane_inactive",
            run: "click",
        },
        {
            content: "there it is, dimmed",
            trigger: ".o_studio_record_card.inactive:contains('Tour Set Field')",
        },
    ],
});
