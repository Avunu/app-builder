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
            content: "the report list is on screen",
            trigger: ".o_list_view",
        },
        {
            // The only thing connecting a report to the editor. Odoo's own
            // report form has a "Qweb Views" button that opens the template as
            // ir.ui.view records; this is the editing one.
            content: "the Edit Layout button is offered on the row",
            trigger: ".o_list_view button[name='action_studio_edit']",
            run: "click",
        },
        {
            content: "the editor opened on the report template",
            trigger: ".o_studio_view_editor .o_studio_report_preview",
        },
        {
            content: "the report is rendered, not an arch dump",
            trigger: ".o_studio_report_preview:contains('Job Sheet')",
        },
        {
            content: "the panel offers to place a value",
            trigger: ".o_studio_view_editor_side:contains('Place a value')",
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
            trigger: ".o_studio_view_editor_side:contains('doc.x_budget')",
        },
    ],
});
