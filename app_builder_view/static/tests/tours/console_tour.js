import { registry } from "@web/core/registry";

/**
 * Editing a view the way a person does: open a list, pick "Edit this view",
 * click a column heading, rename it in Properties, undo, redo, close -- and
 * see the real list show the heading.
 *
 * The last step is the one worth having. Everything before it can pass while
 * the edit goes nowhere -- the arch is written, the file is written, and the
 * user still stares at the old column because the real view cached it.
 */
// Deliberately no `url`: the tour is started against an action created by the
// test, and a url here would override the one start_tour passes -- landing on
// the apps home with no list view in sight.
registry.category("web_tour.tours").add("app_builder_console_list_tour", {
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
            content: "full-screen: the navbar is gone",
            trigger: ".o_studio_console",
            run: function () {
                if (document.querySelector(".o_navbar")) {
                    throw new Error("the console should hide the navbar");
                }
            },
        },
        {
            // A list is the widest canvas there is, so it is where the panel
            // was being flex-shrunk below the width it had just set -- which
            // looked like a narrow sidebar *and* a dead resize handle.
            content: "the sidebar is not squeezed by the wide list beside it",
            trigger: ".o_studio_sidebar",
            run: function () {
                const width = document
                    .querySelector(".o_studio_sidebar")
                    .getBoundingClientRect().width;
                if (width < 340) {
                    throw new Error(`sidebar squeezed to ${Math.round(width)}px`);
                }
            },
        },
        {
            content: "the canvas renders the real list",
            trigger: ".o_studio_canvas .o_list_view th[data-name='display_name']",
        },
        {
            content: "open the View tab",
            trigger: ".o_studio_sidebar_tab[data-tab='view']",
            run: "click",
        },
        {
            content: "a core view is reported as inheriting, not rewritten",
            trigger: ".o_studio_view_tab:contains('belongs to another module')",
        },
        {
            content: "click a column heading in the live canvas",
            trigger: ".o_studio_canvas th[data-name='display_name']",
            run: "click",
        },
        {
            content: "Properties opened by itself",
            trigger: ".o_studio_sidebar_tab.active[data-tab='properties']",
        },
        {
            content: "the selection frame names the column",
            trigger: ".o_studio_overlay .o_studio_tag:contains('Column')",
        },
        {
            content: "the panel offers that column's options",
            trigger: ".o_studio_properties:contains('Column heading')",
        },
        {
            content: "rename the column",
            trigger: ".o_studio_properties .o_studio_row[data-row='string'] input",
            run: "edit Full Name && press Tab",
        },
        {
            content: "the canvas shows the new heading",
            trigger: ".o_studio_canvas th[data-name='display_name']:contains('Full Name')",
        },
        {
            content: "the change is saved",
            trigger: ".o_studio_top_bar .o_studio_status_saved",
        },
        {
            content: "the selection survived the remount",
            trigger: ".o_studio_properties:contains('Column heading')",
        },
        {
            content: "undo it",
            trigger: ".o_studio_top_bar .o_studio_undo:not(:disabled)",
            run: "click",
        },
        {
            content: "the heading is back to what it was",
            trigger:
                ".o_studio_canvas th[data-name='display_name']:not(:contains('Full Name'))",
        },
        {
            content: "redo it",
            trigger: ".o_studio_top_bar .o_studio_redo:not(:disabled)",
            run: "click",
        },
        {
            content: "the heading is renamed again",
            trigger: ".o_studio_canvas th[data-name='display_name']:contains('Full Name')",
        },
        {
            content: "close the console",
            trigger: ".o_studio_top_bar .o_studio_close",
            run: "click",
        },
        {
            content: "back on the real list, which shows the edit",
            trigger: ".o_list_view th[data-name='display_name']:contains('Full Name')",
        },
    ],
});

/**
 * The same spine on a form: click a field, make it required *on this form*,
 * undo; click a notebook tab and see it switch; add a group from the palette
 * into that tab, then a field into the group.
 *
 * The tab is the interesting click. Every other click is swallowed so the
 * live view does not act on it, but a tab has to still switch pages --
 * selecting a page you cannot bring into view would mean editing something
 * you cannot see.
 */
registry.category("web_tour.tours").add("app_builder_console_form_tour", {
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
            trigger: ".o_studio_edit_view",
            run: "click",
        },
        {
            content: "the console opened on the form, on the record",
            trigger: ".o_studio_canvas .o_form_view .o_field_widget[name='name']:contains('Tour Subject')",
        },
        {
            // The label a group generates for a field carries the group's
            // classes, not the field's; it still has to select the field it
            // names. (Not "Phone": an installed module gives that one an
            // explicit <label> in the arch, which is a node of its own.)
            content: "click a field's generated label in the live form",
            trigger: ".o_studio_canvas .o_wrap_label label.o_form_label:contains('Job Position')",
            run: "click",
        },
        {
            content: "the label selected its field, not the group around it",
            trigger: ".o_studio_overlay .o_studio_tag:contains('Field · Job Position')",
        },
        {
            content: "click a field in the live form",
            trigger: ".o_studio_canvas .o_field_widget[name='function']",
            run: "click",
        },
        {
            content: "field options are offered, including form-only required",
            trigger: ".o_studio_properties:contains('Required')",
        },
        {
            content: "make it required on this form",
            trigger: ".o_studio_properties .o_studio_row[data-row='required'] input[type='checkbox']",
            run: "click",
        },
        {
            content: "the canvas marks the field required",
            trigger: ".o_studio_canvas .o_field_widget[name='function'].o_required_modifier",
        },
        {
            content: "undo it",
            trigger: ".o_studio_top_bar .o_studio_undo:not(:disabled)",
            run: "click",
        },
        {
            content: "the field is no longer required",
            trigger:
                ".o_studio_canvas .o_field_widget[name='function']:not(.o_required_modifier)",
        },
        {
            content: "click the second notebook tab",
            trigger: ".o_studio_canvas .o_notebook .nav-link:eq(1)",
            run: "click",
        },
        {
            content: "the tab actually switched, rather than only being selected",
            trigger: ".o_studio_canvas .o_notebook .nav-link:eq(1).active",
        },
        {
            content: "and the tab is what is selected",
            trigger: ".o_studio_overlay .o_studio_tag:contains('Tab')",
        },
        {
            content: "open the Add tab",
            trigger: ".o_studio_sidebar_tab[data-tab='add']",
            run: "click",
        },
        {
            content: "add a group from the components",
            trigger: ".o_studio_tile[data-component='group']",
            run: "click",
        },
        {
            content: "the new group is selected, in the tab that was open",
            trigger: ".o_studio_overlay .o_studio_tag:contains('Group')",
        },
        {
            content: "the tab is still the one that was open",
            trigger: ".o_studio_canvas .o_notebook .nav-link:eq(1).active",
        },
        {
            content: "back to the Add tab",
            trigger: ".o_studio_sidebar_tab[data-tab='add']",
            run: "click",
        },
        {
            content: "add an existing field at the selection",
            trigger: ".o_studio_tile_field[data-name='x_tour_extra']",
            run: "click",
        },
        {
            content: "the field appears on the canvas",
            trigger: ".o_studio_canvas .o_field_widget[name='x_tour_extra']",
        },
        {
            content: "and is selected",
            trigger: ".o_studio_overlay .o_studio_tag:contains('Tour Extra')",
        },
        {
            content: "open the View tab",
            trigger: ".o_studio_sidebar_tab[data-tab='view']",
            run: "click",
        },
        {
            // The version of the arch does not change with this switch, so
            // the canvas has to remount on the switch itself -- and land on
            // the tab that was open.
            content: "show the invisible elements",
            trigger: "#o_studio_show_invisible:not(:checked)",
            run: "click",
        },
        {
            content: "a field the view hides is now on the canvas, marked",
            trigger: ".o_studio_canvas .o_field_widget[name='is_blacklisted'].o_studio_invisible",
        },
        {
            content: "the notebook is still on the tab that was open",
            trigger: ".o_studio_canvas .o_notebook .nav-link:eq(1).active",
        },
        {
            content: "hide them again",
            trigger: "#o_studio_show_invisible:checked",
            run: "click",
        },
        {
            content: "the hidden field is gone again",
            trigger: ".o_studio_canvas .o_form_view:not(:has(.o_field_widget[name='is_blacklisted']))",
        },
        {
            content: "close the console",
            trigger: ".o_studio_top_bar .o_studio_close",
            run: "click",
        },
        {
            content: "back on the real form",
            trigger: ".o_form_view:not(.o_studio_canvas *)",
        },
    ],
});

/**
 * A search view, edited as its three lists beside a real list of the model.
 *
 * What is pinned: the switcher reaches it from another view's console; an
 * added field shows up in the list *and* survives Undo and Redo -- the lists
 * are not the canvas, so nothing refreshes them unless the console does; and
 * the host list is a preview, so a click on one of its rows opens nothing.
 */
registry.category("web_tour.tours").add("app_builder_console_search_tour", {
    steps: () => [
        {
            content: "the list view itself is on screen",
            trigger: ".o_list_view",
        },
        {
            content: "open the cog menu",
            trigger: ".o_cp_action_menus button:has(.fa-cog)",
            run: "click",
        },
        {
            content: "edit this view",
            trigger: ".o_studio_edit_view",
            run: "click",
        },
        {
            content: "the console opened on the list",
            trigger: ".o_studio_console .o_studio_canvas .o_list_view",
        },
        {
            content: "switch to the search view of the model",
            trigger: ".o_studio_top_bar .o_studio_switch[data-view-type='search']",
            run: "click",
        },
        {
            content: "the search view is edited as lists, beside a real list",
            trigger: ".o_studio_search_canvas .o_studio_search_host .o_list_view .o_data_row",
        },
        {
            content: "a click on a row of the host list is a click on a preview",
            trigger: ".o_studio_search_host .o_data_row .o_data_cell",
            run: "click",
        },
        {
            content: "add a searchable field",
            trigger: ".o_studio_search_lists select[name='add_search_field']",
            run: "selectByLabel Tour Search",
        },
        {
            content: "it is listed among the searchable fields",
            trigger: ".o_studio_search_entry[data-entry='x_tour_search']",
        },
        {
            content: "undo it",
            trigger: ".o_studio_top_bar .o_studio_undo:not(:disabled)",
            run: "click",
        },
        {
            content: "the list no longer offers it",
            trigger: ".o_studio_search_lists:not(:has(.o_studio_search_entry[data-entry='x_tour_search']))",
        },
        {
            content: "redo it",
            trigger: ".o_studio_top_bar .o_studio_redo:not(:disabled)",
            run: "click",
        },
        {
            content: "and it is listed again",
            trigger: ".o_studio_search_entry[data-entry='x_tour_search']",
        },
        {
            content: "the host list is still a list, and the row click opened nothing",
            trigger: ".o_studio_search_host .o_list_view .o_data_row",
            run: function () {
                if (document.querySelector(".o_form_view")) {
                    throw new Error("a row of the host list opened its record");
                }
                if (document.querySelector(".o_studio_search_host .o_selected_row")) {
                    throw new Error("a row of the host list went into edit mode");
                }
            },
        },
        {
            content: "close the console",
            trigger: ".o_studio_top_bar .o_studio_close",
            run: "click",
        },
        {
            content: "back on the real list",
            trigger: ".o_list_view:not(.o_studio_canvas *)",
        },
    ],
});
