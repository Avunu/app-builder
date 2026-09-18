import { registry } from "@web/core/registry";

/**
 * The Approvals pane on a model that is not gated: the gate header comes
 * first, says why, offers the status field and the transition, and keeps
 * the button off until there is a state to approve into. New is not on
 * offer until the gate is -- a rule on an ungated model would never fire.
 */
registry.category("web_tour.tours").add("app_builder_approvals_pane_tour", {
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
            content: "open the Approvals pane",
            trigger: ".o_studio_top_bar .o_studio_top_tab[data-tab='approvals']",
            run: "click",
        },
        {
            content: "the gate header says approvals are off for this model",
            trigger:
                ".o_studio_record_pane .o_studio_gate_card:contains('not switched on for res.partner')",
        },
        {
            content: "and New is not offered",
            trigger: ".o_studio_record_pane:not(:has(.o_studio_pane_new))",
        },
        {
            content: "the button waits for a destination state",
            trigger: ".o_studio_gate_card .o_studio_gate_enable:disabled",
        },
        {
            content: "the sentence says so",
            trigger: ".o_studio_gate_card .o_studio_gate_sentence:contains('Say which state')",
        },
        {
            content: "choose a status field",
            trigger: ".o_studio_gate_card [data-row='gate_field'] select",
            run: "selectByLabel Address Type",
        },
        {
            content: "and where it goes",
            trigger: ".o_studio_gate_card [data-row='gate_to'] select",
            run: "selectByLabel Invoice Address",
        },
        {
            content: "the sentence reads back the transition",
            trigger:
                ".o_studio_gate_card .o_studio_gate_sentence:contains('from any state to Invoice Address')",
        },
        {
            content: "and the button is live, with its consequence under it",
            trigger:
                ".o_studio_gate_card .o_studio_gate_enable:not(:disabled) + .o_studio_row_hint:contains('one reload')",
        },
    ],
});
