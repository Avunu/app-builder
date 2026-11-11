import {waitUntil} from "@odoo/hoot-dom";
import {registry} from "@web/core/registry";

/**
 * A new field, dropped where it is wanted, on the two kinds of model.
 *
 * On a core model the Text tile is a field the moment it lands: an `x_`
 * row, placed after the field it was dropped on, with the cursor already
 * in its Label row and the placeholder label selected, so typing names
 * it. Renaming it there renames the field itself -- the label is the
 * model's, not this view's -- and the canvas shows the new label. Undo
 * takes it off the view and nothing else: the field stays, and turns up
 * among the existing fields to be put back.
 */
// Deliberately no `url`: the tour is started against an action created by the
// test, and a url here would override the one start_tour passes.
registry.category("web_tour.tours").add("app_builder_console_new_field_tour", {
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
      content: "the Text tile is offered live, needing no dialog",
      trigger:
        ".o_builder_tile_new.o_builder_draggable[data-type='char'][data-needs-dialog='0']:not(:disabled)",
    },
    {
      content: "drag the Text tile to just after Job Position",
      trigger: ".o_builder_tile_new.o_builder_draggable[data-type='char']",
      run: "drag_and_drop .o_builder_overlay .o_builder_dropzone[data-name='function'][data-position='after']",
    },
    {
      content: "the new field is on the canvas, right after Job Position",
      trigger: ".o_builder_canvas .o_field_widget[name='x_new_text']",
    },
    {
      content: "and is selected, with the properties open",
      trigger: ".o_builder_sidebar_tab.active[data-tab='properties']",
    },
    {
      content: "the Label row is focused with its text selected",
      trigger: ".o_builder_properties .o_builder_row[data-row='string'] input",
      run: async function () {
        // The cursor is handed over once the row has been drawn,
        // which is a few frames after it appears.
        for (let left = 40; left > 0; left--) {
          if (document.activeElement === this.anchor) {
            break;
          }
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
        const input = this.anchor as HTMLInputElement;
        if (document.activeElement !== input) {
          throw new Error("the Label row should have the focus after the drop");
        }
        if (input.value !== "New Text") {
          throw new Error(`the label should read "New Text", got "${input.value}"`);
        }
        if (input.selectionStart !== 0 || input.selectionEnd !== input.value.length) {
          throw new Error(
            "the label's text should be selected, ready to be typed over"
          );
        }
      },
    },
    {
      content: "the row says it renames the field itself",
      trigger:
        ".o_builder_properties .o_builder_row[data-row='string'] .o_builder_row_hint",
    },
    {
      content: "rename the field",
      trigger: ".o_builder_properties .o_builder_row[data-row='string'] input",
      run: "edit Delivery date && press Tab",
    },
    {
      content: "the canvas shows the field under its new label",
      trigger: ".o_builder_canvas .o_form_label:contains('Delivery date')",
    },
    {
      content: "the change is saved",
      trigger: ".o_builder_top_bar .o_builder_status_saved",
    },
    {
      content: "undo the drop",
      trigger: ".o_builder_top_bar .o_builder_undo:not(:disabled)",
      run: "click",
    },
    {
      content: "the field is off the view",
      trigger:
        ".o_builder_canvas .o_form_view:not(:has(.o_field_widget[name='x_new_text']))",
    },
    {
      content: "open the Add tab",
      trigger: ".o_builder_sidebar_tab[data-tab='add']",
      run: "click",
    },
    {
      content: "the field still exists, and is offered among the existing fields",
      trigger: ".o_builder_tile_field[data-name='x_new_text']",
    },
    {
      // A relation cannot be made from a label alone: the tile opens
      // the field editor before anything is sent, and Cancel is no
      // request at all -- the server never hears of it.
      content: "drag a Link tile, which needs its definition first",
      trigger:
        ".o_builder_tile_new.o_builder_draggable[data-type='many2one'][data-needs-dialog='1']:not(:disabled)",
      run: "drag_and_drop .o_builder_overlay .o_builder_dropzone[data-name='function'][data-position='after']",
    },
    {
      content: "the field editor opened instead of a request being made",
      trigger: ".o_builder_field_editor_popover .o_builder_field_editor",
    },
    {
      content: "nothing landed on the canvas meanwhile",
      trigger: ".o_builder_canvas .o_form_view",
      run: function () {
        if (
          document.querySelector(
            ".o_builder_canvas .o_field_widget[name^='x_new_link']"
          )
        ) {
          throw new Error("a field was created before the editor was done");
        }
        if (document.querySelector(".o_builder_top_bar .o_builder_status_saving")) {
          throw new Error("nothing should be saving while the editor asks");
        }
      },
    },
    {
      content: "cancel it",
      trigger: ".o_builder_field_editor_popover button:contains('Cancel')",
      run: "click",
    },
    {
      content: "the editor is gone and nothing was written",
      trigger:
        ".o_builder_console:not(:has(.o_builder_field_editor_popover)) .o_builder_top_bar .o_builder_status_saved",
    },
    {
      content: "close the console",
      trigger: ".o_builder_top_bar .o_builder_close",
      run: "click",
    },
    {
      content: "back on the real form",
      trigger: ".o_form_view:not(.o_builder_canvas *)",
    },
  ],
});

/**
 * The same tile on a model a package defines in Python: the field is a
 * class attribute waiting for an Apply, so the drop stages it and the
 * canvas shows a ghost where it will land, in the flow of the form; the
 * pill counts it and offers Apply. Discard takes it back, ghost and all.
 */
registry.category("web_tour.tours").add("app_builder_console_staged_field_tour", {
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
        ".o_builder_canvas .o_form_view .o_field_widget[name='x_name']:contains('Staged Subject')",
    },
    {
      content: "the palette says fields are staged here",
      trigger: ".o_builder_add .o_builder_staged_note",
    },
    {
      content: "nothing is pending yet",
      trigger: ".o_builder_top_bar .o_builder_status_saved",
    },
    {
      content: "drag the Decimal tile to just after the name",
      trigger:
        ".o_builder_tile_new.o_builder_draggable[data-type='float']:not(:disabled)",
      run: "drag_and_drop .o_builder_overlay .o_builder_dropzone[data-name='x_name'][data-position='after']",
    },
    {
      content: "a ghost of the field is on the canvas, in the flow of the form",
      trigger:
        ".o_builder_canvas .o_form_view .o_inner_group .o_builder_pending:contains('New Decimal')",
    },
    {
      content: "the ghost says it is pending",
      trigger: ".o_builder_canvas .o_builder_pending:contains('appears after Apply')",
    },
    {
      content: "the pill counts it and offers Apply",
      trigger: ".o_builder_top_bar .o_builder_status_pending:contains('1 pending')",
    },
    {
      content: "the ghost is selected",
      trigger: ".o_builder_overlay .o_builder_tag:contains('Pending')",
    },
    {
      content: "the properties show the staged definition",
      trigger: ".o_builder_properties .o_builder_pending_name:contains('New Decimal')",
    },
    {
      content: "the Apply button is there too",
      trigger: ".o_builder_top_bar .o_builder_apply",
    },
    {
      // A ghost is not in the arch to be moved: dragging it re-anchors
      // the staged field, and the canvas draws it at the new spot.
      content: "drag the ghost to after the note",
      trigger: ".o_builder_canvas .o_builder_pending",
      run: "drag_and_drop .o_builder_overlay .o_builder_dropzone[data-name='x_note'][data-position='after']",
    },
    {
      content: "the ghost now sits after the note",
      trigger: ".o_builder_canvas .o_form_view .o_inner_group .o_builder_pending",
      run: async function () {
        // The trigger is met at once by the ghost where it was: the drop's
        // RPC is still in flight, so this waits for the redraw it leads to.
        // The note has been on the canvas since this tour's first step and
        // nothing removes it, so a missing one still fails here.
        await waitUntil(
          () => {
            const note = document.querySelector(
              ".o_builder_canvas .o_form_view .o_field_widget[name='x_note']"
            )!;
            const ghost = document.querySelector(
              ".o_builder_canvas .o_form_view .o_inner_group .o_builder_pending"
            );
            return (
              ghost !== null &&
              Boolean(
                note.compareDocumentPosition(ghost) & Node.DOCUMENT_POSITION_FOLLOWING
              )
            );
          },
          {timeout: 5000, message: "the ghost should have moved after the note"}
        );
      },
    },
    {
      content: "still one pending: a move is not a second field",
      trigger: ".o_builder_top_bar .o_builder_status_pending:contains('1 pending')",
    },
    {
      content: "open the staged definition in the field editor",
      trigger: ".o_builder_properties .o_builder_edit_pending",
      run: "click",
    },
    {
      content: "the editor opened on the staged field, with its label",
      trigger:
        ".o_builder_field_editor_popover .o_builder_field_editor input[type='text']:eq(0):value('New Decimal')",
    },
    {
      content: "rename it",
      trigger:
        ".o_builder_field_editor_popover .o_builder_field_editor input[type='text']:eq(0)",
      run: "edit Weight",
    },
    {
      content: "done",
      trigger: ".o_builder_field_editor_popover button:contains('Done')",
      run: "click",
    },
    {
      content: "the ghost follows the new label",
      trigger: ".o_builder_canvas .o_builder_pending:contains('Weight')",
    },
    {
      content: "and so do the properties",
      trigger: ".o_builder_properties .o_builder_pending_name:contains('Weight')",
    },
    {
      content: "open the Apply dialog from the pill",
      trigger: ".o_builder_top_bar .o_builder_status_pending",
      run: "click",
    },
    {
      content: "the dialog lists the staged field",
      trigger: ".o_builder_apply_dialog .o_builder_apply_changes:contains('Weight')",
    },
    {
      content: "show the diff of what would be written",
      trigger: ".o_builder_apply_dialog .o_builder_show_diff",
      run: "click",
    },
    {
      content: "the diff names the field",
      trigger: ".o_builder_apply_dialog .o_builder_diff:contains('new_decimal')",
    },
    {
      content: "and says what the reload will cost",
      trigger: ".o_builder_apply_dialog .o_builder_reload_notice",
    },
    {
      content: "close the dialog without applying",
      trigger: ".o_builder_apply_dialog .modal-footer .btn-link",
      run: "click",
    },
    {
      // The class itself, from the View tab: every field in the order
      // it is written, the staged one marked, and the others editable
      // the same way -- this is what the composer used to be.
      content: "open the View tab",
      trigger: ".o_builder_sidebar_tab[data-tab='view']",
      run: "click",
    },
    {
      content: "the model's fields are listed, in class order",
      trigger:
        ".o_builder_view_tab .o_builder_model_field[data-field='x_name']:contains('Name')",
    },
    {
      content: "the staged field is among them, marked new",
      trigger:
        ".o_builder_view_tab .o_builder_model_field[data-field='new_decimal'] .o_builder_model_badge:contains('new')",
    },
    {
      content: "edit an existing field's definition",
      trigger:
        ".o_builder_view_tab .o_builder_model_field[data-field='x_note'] .o_builder_model_edit",
      run: "click",
    },
    {
      content: "the editor opened on it",
      trigger:
        ".o_builder_field_editor_popover .o_builder_field_editor input[type='text']:eq(0):value('Note')",
    },
    {
      content: "relabel it",
      trigger:
        ".o_builder_field_editor_popover .o_builder_field_editor input[type='text']:eq(0)",
      run: "edit Remarks",
    },
    {
      content: "done",
      trigger: ".o_builder_field_editor_popover button:contains('Done')",
      run: "click",
    },
    {
      content: "the list shows the edit, marked",
      trigger:
        ".o_builder_view_tab .o_builder_model_field[data-field='x_note']:contains('Remarks') .o_builder_model_badge:contains('edited')",
    },
    {
      content: "two things pending now",
      trigger: ".o_builder_top_bar .o_builder_status_pending:contains('2 pending')",
    },
    {
      content: "add a field to the model without dropping it anywhere",
      trigger: ".o_builder_view_tab .o_builder_model_add",
      run: "click",
    },
    {
      content: "the editor opened for a new field",
      trigger:
        ".o_builder_field_editor_popover .o_builder_field_editor input[type='text']:eq(0)",
      run: "edit Colour",
    },
    {
      content: "done",
      trigger: ".o_builder_field_editor_popover button:contains('Done')",
      run: "click",
    },
    {
      content: "it is listed as new, and counted",
      trigger:
        ".o_builder_view_tab .o_builder_model_field:contains('Colour') .o_builder_model_badge:contains('new')",
    },
    {
      content: "three pending",
      trigger: ".o_builder_top_bar .o_builder_status_pending:contains('3 pending')",
    },
    {
      content: "select the relabelled field on the canvas",
      trigger: ".o_builder_canvas .o_form_view .o_field_widget[name='x_note']",
      run: "click",
    },
    {
      content: "its properties offer the definition, and say an edit is staged",
      trigger: ".o_builder_properties .o_builder_owned_pending:contains('staged edit')",
    },
    {
      content: "the class attribute can be edited from here too",
      trigger: ".o_builder_properties .o_builder_edit_owned",
      run: "click",
    },
    {
      content: "on the staged label",
      trigger:
        ".o_builder_field_editor_popover .o_builder_field_editor input[type='text']:eq(0):value('Remarks')",
    },
    {
      content: "leave it",
      trigger: ".o_builder_field_editor_popover button:contains('Cancel')",
      run: "click",
    },
    {
      content: "discard it from the top bar",
      trigger: ".o_builder_top_bar .o_builder_discard",
      run: "click",
    },
    {
      content: "confirm",
      trigger: ".modal .modal-footer .btn-primary",
      run: "click",
    },
    {
      content: "the ghost is gone",
      trigger: ".o_builder_canvas .o_form_view:not(:has(.o_builder_pending))",
    },
    {
      content: "and nothing is pending",
      trigger: ".o_builder_top_bar .o_builder_status_saved",
    },
    {
      content: "back to the View tab",
      trigger: ".o_builder_sidebar_tab[data-tab='view']",
      run: "click",
    },
    {
      content: "the model list has no marks left",
      trigger:
        ".o_builder_view_tab .o_builder_model_fields:not(:has(.o_builder_model_badge))",
    },
    {
      content: "close the console",
      trigger: ".o_builder_top_bar .o_builder_close",
      run: "click",
    },
    {
      content: "back on the real form",
      trigger: ".o_form_view:not(.o_builder_canvas *)",
    },
  ],
});
