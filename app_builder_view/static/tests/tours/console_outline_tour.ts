import {registry} from "@web/core/registry";

/**
 * The outline, as a person uses it: a row selects the node on the canvas
 * and opens its properties; a row for a field on another tab switches the
 * canvas to that tab; a key press on a row moves the field, and the tree
 * and the arch both say so.
 *
 * Every row is found by what it stands for -- `data-name` -- never by its
 * place, and the reorder is checked on the rows themselves: the row that
 * was below is above once the move is made.
 */
// Deliberately no `url`: the tour is started against an action created by the
// test, and a url here would override the one start_tour passes.
/** The row below Job Position before the move: above it after. */
let below: string | null | undefined = null;

function rowNamed(name: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(
    `.o_builder_outline_row[data-name='${name}']`
  );
}

registry.category("web_tour.tours").add("app_builder_console_outline_tour", {
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
      trigger: ".o_builder_edit_view",
      run: "click",
    },
    {
      content: "the console opened on the form, on the record",
      trigger:
        ".o_builder_canvas .o_form_view .o_field_widget[name='name']:contains('Tour Subject')",
    },
    {
      content: "the outline lists the form's fields, Job Position among them",
      trigger:
        ".o_builder_outline_row[data-name='function'] + .o_builder_outline_row[data-kind='field']",
      run() {
        below = (rowNamed("function")!.nextElementSibling as HTMLElement).dataset[
          "name"
        ];
      },
    },
    {
      content: "the outline lists the tabs too, under the notebook",
      trigger: ".o_builder_outline_row[data-kind='page'][data-name='sales_purchases']",
    },
    {
      content: "click the Job Position row",
      trigger: ".o_builder_outline_row[data-name='function']",
      run: "click",
    },
    {
      content: "the canvas frames the field the row stands for",
      trigger: ".o_builder_overlay .o_builder_tag:contains('Field · Job Position')",
    },
    {
      content: "the properties opened, and the row shows it is selected",
      trigger: ".o_builder_sidebar_tab.active[data-tab='properties']",
    },
    {
      content: "the row is marked selected",
      trigger:
        ".o_builder_outline_row.o_builder_outline_selected[data-name='function']",
    },
    {
      content: "click a row for a field on the second tab",
      trigger: ".o_builder_outline_row[data-name='ref']",
      run: "click",
    },
    {
      content: "the canvas switched to that tab to show the field",
      trigger: ".o_builder_canvas .o_notebook .nav-link.active[name='sales_purchases']",
    },
    {
      content: "and framed it",
      trigger: ".o_builder_overlay .o_builder_tag:contains('Field · Reference')",
    },
    {
      content: "click a field on the canvas: the tree follows",
      trigger: ".o_builder_canvas .o_field_widget[name='name']",
      run: "click",
    },
    {
      content: "the tree marks the field the canvas selected",
      trigger: ".o_builder_outline_row.o_builder_outline_selected[data-name='name']",
    },
    {
      content: "back on the Job Position row",
      trigger: ".o_builder_outline_row[data-name='function']",
      run: "click",
    },
    {
      content: "move it down with the keyboard",
      trigger:
        ".o_builder_outline_row.o_builder_outline_selected[data-name='function']",
      run: "press Alt+ArrowDown",
    },
    {
      content: "the edit was made: it can be undone",
      trigger: ".o_builder_top_bar .o_builder_undo:not(:disabled)",
    },
    {
      content: "the edit is saved",
      trigger: ".o_builder_top_bar .o_builder_status_saved",
    },
    {
      content: "the tree shows the row that was below Job Position above it now",
      trigger: ".o_builder_outline_row[data-name='function']",
      run() {
        const above = (rowNamed("function")!.previousElementSibling as HTMLElement)
          .dataset["name"];
        if (above !== below) {
          throw new Error(`expected ${below} above Job Position, found ${above}`);
        }
      },
    },
    {
      content: "the moved field is still the selection, on the canvas too",
      trigger: ".o_builder_overlay .o_builder_tag:contains('Field · Job Position')",
    },
    {
      content: "close the console",
      trigger: ".o_builder_top_bar .o_builder_close",
      run: "click",
    },
    {
      content: "back on the real form, which the server's arch says is reordered",
      trigger:
        "body:not(:has(.o_builder_console)) .o_form_view .o_field_widget[name='function']",
    },
  ],
});
