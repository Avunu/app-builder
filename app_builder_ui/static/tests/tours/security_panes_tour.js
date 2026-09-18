import { registry } from "@web/core/registry";
registry.category("web_tour.tours").add("app_builder_security_panes_tour", {
  steps: () => [
    {
      content: "open the cog menu of a real list view",
      trigger: ".o_cp_action_menus button:has(.fa-cog)",
      run: "click"
    },
    {
      content: "the studio entry",
      trigger: ".o_studio_edit_view",
      run: "click"
    },
    // -- Access Control ------------------------------------------------------
    {
      content: "open the Access Control pane",
      trigger: ".o_studio_top_bar .o_studio_top_tab[data-tab='access']",
      run: "click"
    },
    {
      content: "the lines Odoo ships are shown, from their module, not editable",
      trigger: ".o_studio_record_pane .o_studio_record_card.foreign .o_studio_record_badge[data-badge='foreign']"
    },
    {
      content: "New, from the first template",
      trigger: ".o_studio_record_pane .o_studio_pane_new",
      run: "click"
    },
    {
      content: "the inline form asks for the group",
      trigger: ".o_studio_create_card .o_studio_row[data-row='group_id'] .o-autocomplete--input",
      run: "edit Tour Group"
    },
    {
      content: "pick it",
      trigger: ".o-autocomplete--dropdown-item:contains('Tour Group')",
      run: "click"
    },
    {
      content: "create the line",
      trigger: ".o_studio_create_card .o_studio_create_confirm",
      run: "click"
    },
    {
      content: "the card: the group, read only",
      trigger: ".o_studio_record_card.selected:contains('Tour Group') .o_studio_record_sentence:contains('R–––')"
    },
    {
      content: "grant write from the sidebar",
      trigger: ".o_studio_record_sidebar .o_studio_row[data-row='perm_write'] input",
      run: "click"
    },
    {
      content: "the card says so",
      trigger: ".o_studio_record_card.selected .o_studio_record_sentence:contains('RW––')"
    },
    // -- Filter Rules --------------------------------------------------------
    {
      content: "open the Filter Rules pane",
      trigger: ".o_studio_top_bar .o_studio_top_tab[data-tab='rules']",
      run: "click"
    },
    {
      content: "a template from the New menu",
      trigger: ".o_studio_record_pane .o_studio_pane_toolbar .dropdown-toggle-split",
      run: "click"
    },
    {
      content: "only their own records",
      trigger: ".o_studio_pane_template[data-template='own_records']",
      run: "click"
    },
    {
      content: "name it",
      trigger: ".o_studio_create_card .o_studio_row[data-row='name'] input",
      run: "edit Tour Own Records"
    },
    {
      content: "for the group",
      trigger: ".o_studio_create_card .o_studio_row[data-row='groups'] .o-autocomplete--input",
      run: "edit Tour Group"
    },
    {
      content: "pick it",
      trigger: ".o-autocomplete--dropdown-item:contains('Tour Group')",
      run: "click"
    },
    {
      content: "create the rule",
      trigger: ".o_studio_create_card .o_studio_create_confirm",
      run: "click"
    },
    {
      content: "the card, with the group and the condition",
      trigger: ".o_studio_record_card.selected:contains('Tour Own Records') .o_studio_record_sentence:contains('create_uid')"
    },
    {
      content: "the sidebar says what the condition matches today",
      trigger: ".o_studio_record_sidebar .o_studio_record_matches:contains('Matches')"
    }
  ]
});
