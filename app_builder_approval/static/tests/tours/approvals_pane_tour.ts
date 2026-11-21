import {registry} from "@web/core/registry";

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
      content: "the builder entry",
      trigger: ".o_builder_edit_view",
      run: "click",
    },
    {
      content: "open the Approvals pane",
      trigger: ".o_builder_top_bar .o_builder_top_tab[data-tab='approvals']",
      run: "click",
    },
    {
      content: "the gate header says approvals are off for this model",
      trigger:
        ".o_builder_record_pane .o_builder_gate_card:contains('not switched on for res.partner')",
    },
    {
      content: "and New is not offered",
      trigger: ".o_builder_record_pane:not(:has(.o_builder_pane_new))",
    },
    {
      content: "the button waits for a destination state",
      trigger: ".o_builder_gate_card .o_builder_gate_enable:disabled",
    },
    {
      content: "the sentence says so",
      trigger:
        ".o_builder_gate_card .o_builder_gate_sentence:contains('Say which state')",
    },
    {
      content: "choose a status field",
      trigger: ".o_builder_gate_card [data-row='gate_field'] select",
      run: "selectByLabel Address Type",
    },
    {
      content: "and where it goes",
      trigger: ".o_builder_gate_card [data-row='gate_to'] select",
      run: "selectByLabel Invoice Address",
    },
    {
      content: "the sentence reads back the transition",
      trigger:
        ".o_builder_gate_card .o_builder_gate_sentence:contains('from any state to Invoice Address')",
    },
    {
      content: "and the button is live, with its consequence under it",
      trigger:
        ".o_builder_gate_card .o_builder_gate_enable:not(:disabled) + .o_builder_row_hint:contains('one reload')",
    },
  ],
});

/**
 * The gate's whole life from the pane: turned on, changed, turned off. The
 * reload Apply would do cannot happen under a tour, so the test that runs
 * this (`test_approvals_pane_tour.py`) writes the source without applying
 * and reads the gate back from it; what is driven here is every control
 * and the confirmation, through the surface's real calls.
 */
registry.category("web_tour.tours").add("app_builder_approvals_lifecycle_tour", {
  steps: () => [
    {
      content: "open the cog menu of a real list view",
      trigger: ".o_cp_action_menus button:has(.fa-cog)",
      run: "click",
    },
    {
      content: "the builder entry",
      trigger: ".o_builder_edit_view",
      run: "click",
    },
    {
      content: "open the Approvals pane",
      trigger: ".o_builder_top_bar .o_builder_top_tab[data-tab='approvals']",
      run: "click",
    },
    {
      content: "choose a status field",
      trigger: ".o_builder_gate_card [data-row='gate_field'] select",
      run: "selectByLabel Address Type",
    },
    {
      content: "and where it goes",
      trigger: ".o_builder_gate_card [data-row='gate_to'] select",
      run: "selectByLabel Invoice Address",
    },
    {
      content: "turn approvals on",
      trigger: ".o_builder_gate_card .o_builder_gate_enable:not(:disabled)",
      run: "click",
    },
    {
      content: "the card now says what is enforced",
      trigger:
        ".o_builder_gate_on .o_builder_gate_current:contains('to Invoice Address')",
    },
    {
      content: "and offers to change it",
      trigger: ".o_builder_gate_on .o_builder_gate_change:not(:disabled)",
      run: "click",
    },
    {
      content: "the change form opens on the destination enforced now",
      trigger:
        ".o_builder_gate_on [data-row='gate_to'] select option:selected:contains('Invoice Address')",
    },
    {
      content: "move the gate to another destination",
      trigger: ".o_builder_gate_on [data-row='gate_to'] select",
      run: "selectByLabel Delivery Address",
    },
    {
      content: "save the change",
      trigger: ".o_builder_gate_on .o_builder_gate_save:not(:disabled)",
      run: "click",
    },
    {
      content: "the card reads back the new transition",
      trigger:
        ".o_builder_gate_on:not(:has(.o_builder_gate_form)) .o_builder_gate_current:contains('to Delivery Address')",
    },
    {
      content: "turn approvals off",
      trigger: ".o_builder_gate_on .o_builder_gate_disable:not(:disabled)",
      run: "click",
    },
    {
      content: "the confirmation says what happens to the data first",
      trigger: ".modal .modal-body:contains('renamed column')",
    },
    {
      content: "confirm",
      trigger: ".modal .modal-footer .btn-danger",
      run: "click",
    },
    {
      content: "the gate is off again, and the pane offers to turn it on",
      trigger:
        ".o_builder_record_pane:not(:has(.o_builder_gate_on)) .o_builder_gate_card .o_builder_gate_enable",
    },
  ],
});
