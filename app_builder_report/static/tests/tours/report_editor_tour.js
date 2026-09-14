import { registry } from "@web/core/registry";

/**
 * Placing a value on a report by clicking, the way a person does.
 *
 * This is the test the phase exists for. The two operations had unit tests and
 * no caller: `add_report_field` was written, tested, committed and described as
 * a gesture while nothing in the browser could invoke it. A server test cannot
 * see that. This can.
 */
registry.category("web_tour.tours").add("app_builder_report_editor_tour", {
    steps: () => [
        {
            content: "the list of the model is on screen",
            trigger: ".o_list_view",
        },
        {
            content: "open the cog menu",
            trigger: ".o_cp_action_menus button:has(.fa-cog)",
            run: "click",
        },
        {
            content: "the studio entry",
            trigger: ".o_studio_edit_view",
            run: "click",
        },
        {
            content: "the Reports pane",
            trigger: ".o_studio_top_bar .o_studio_top_tab[data-tab='reports']",
            run: "click",
        },
        {
            content: "nothing yet: the empty state offers the layouts",
            trigger: ".o_studio_record_pane .o_studio_pane_empty .o_studio_pane_template[data-template='internal']",
            run: "click",
        },
        {
            content: "name it",
            trigger: ".o_studio_create_card .o_studio_row[data-row='name'] input",
            run: "edit Job Sheet",
        },
        {
            content: "create it",
            trigger: ".o_studio_create_card .o_studio_create_confirm",
            run: "click",
        },
        {
            content: "the card, selected, in the Print menu",
            trigger: ".o_studio_record_card.selected:contains('Job Sheet') .o_studio_record_badge[data-badge='print']",
        },
        {
            // The only thing connecting a report to the editor: the card's
            // Edit layout, which opens the template on the same console.
            content: "Edit layout is offered on the card",
            trigger: ".o_studio_record_card.selected .o_studio_record_actions [data-action='edit']",
            run: "click",
        },
        {
            content: "the console opened on the report template",
            trigger: ".o_studio_console .o_studio_report_preview",
        },
        {
            content: "the report is rendered, not an arch dump",
            trigger: ".o_studio_report_preview:contains('Job Sheet')",
        },
        {
            content: "the panel offers to place a value",
            trigger: ".o_studio_report_tools:contains('Place a value')",
        },
        {
            content: "choose the field to print",
            trigger: "select[name='report_field']",
            run: "select x_budget",
        },
        {
            content: "give it a label, so the two travel together",
            trigger: "input[name='report_label']",
            run: "edit Budget",
        },
        {
            content: "place it",
            trigger: "button[name='place_report_field']",
            run: "click",
        },
        {
            // The step worth having. Everything above can pass while the edit
            // goes nowhere: the arch is written, the file is written, and the
            // preview still shows the document from before.
            content: "the value is now on the document",
            trigger: ".o_studio_report_preview:contains('Budget')",
        },
        {
            content: "and it is selectable, because qweb branded it",
            trigger: ".o_studio_report_preview [data-oe-expression='doc.x_budget']",
            run: "click",
        },
        {
            content: "clicking it selects it rather than doing nothing",
            trigger: ".o_studio_report_tools:contains('doc.x_budget')",
        },
    ],
});
