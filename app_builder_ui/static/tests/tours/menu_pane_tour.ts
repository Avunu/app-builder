import {registry} from "@web/core/registry";

/**
 * The Menu pane: the package's app with its icon made from a template,
 * a submenu that opens a model under it, moved above its sibling; and
 * the tree the pane draws of it. The server test checks menus.xml.
 */
registry.category("web_tour.tours").add("app_builder_menu_pane_tour", {
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
      content: "open the Menu pane",
      trigger: ".o_builder_top_bar .o_builder_top_tab[data-tab='menu']",
      run: "click",
    },
    {
      content: "the package has a menu already: the fixture's submenu under its app",
      trigger:
        ".o_builder_record_pane .o_builder_record_card:contains('Tour Fixture Sub')",
    },
    {
      content: "it is indented under its parent",
      trigger:
        ".o_builder_record_pane .o_builder_record_card[style*='padding-left']:contains('Tour Fixture Sub')",
    },
    {
      content: "New submenu",
      trigger: ".o_builder_record_pane .o_builder_pane_new",
      run: "click",
    },
    {
      content: "name it",
      trigger: ".o_builder_create_card .o_builder_row[data-row='name'] input",
      run: "edit Tour People",
    },
    {
      content: "under the app",
      trigger:
        ".o_builder_create_card .o_builder_row[data-row='parent_id'] .o-autocomplete--input",
      run: "edit Tour Fixture App",
    },
    {
      content: "pick it",
      trigger: ".o-autocomplete--dropdown-item:contains('Tour Fixture App')",
      run: "click",
    },
    {
      content: "opening Contacts",
      trigger:
        ".o_builder_create_card .o_builder_row[data-row='opens_model'] .o-autocomplete--input",
      run: "edit res.partner",
    },
    {
      content: "pick the model",
      trigger: ".o-autocomplete--dropdown-item:contains('Contact')",
      run: "click",
    },
    {
      content: "create it",
      trigger: ".o_builder_create_card .o_builder_create_confirm",
      run: "click",
    },
    {
      content:
        "the card, under the app, opening the model -- and highlighted, since it opens the model on the canvas",
      trigger:
        ".o_builder_record_card.selected.highlight:contains('Tour People') .o_builder_record_sentence:contains('res.partner')",
    },
    {
      content: "it sits after the fixture's submenu",
      trigger:
        ".o_builder_record_card:contains('Tour Fixture Sub') + .o_builder_record_card:contains('Tour People')",
    },
    {
      content: "move it up",
      trigger:
        ".o_builder_record_card.selected .o_builder_record_actions [data-action='up']",
      run: "click",
    },
    {
      content: "now it is first under the app",
      trigger:
        ".o_builder_record_card:contains('Tour People') + .o_builder_record_card:contains('Tour Fixture Sub')",
    },
    {
      content: "rename it from the sidebar",
      trigger: ".o_builder_record_sidebar .o_builder_row[data-row='name'] input",
      run: "edit Tour Contacts && click body",
    },
    {
      content: "the card follows",
      trigger: ".o_builder_record_card.selected:contains('Tour Contacts')",
    },
  ],
});
