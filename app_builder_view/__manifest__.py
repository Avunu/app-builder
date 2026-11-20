{
    "name": "App Builder: View Editor",
    "summary": "Edit views visually; every change becomes an inheriting view in source",
    "version": "18.0.2.0.3",
    "category": "Technical",
    "website": "https://github.com/Avunu/app-builder",
    "author": "Avunu LLC",
    "license": "AGPL-3",
    "development_status": "Beta",
    "installable": True,
    "uninstall_hook": "uninstall_hook",
    # html_editor is auto-installed on top of web in 18, 19 and master, but
    # auto_install decides what a fresh database gets, not what stays: the
    # module can be uninstalled, and the console imports its drag-and-drop
    # hook (`@html_editor/utils/drag_and_drop`), which only resolves while
    # the module is installed. Naming it here is what keeps the two together.
    "depends": ["app_builder_base", "web", "html_editor"],
    "external_dependencies": {"python": ["typing_extensions"]},
    "data": [
        "security/ir.model.access.csv",
        "views/builder_view_editor_views.xml",
        "views/builder_console_views.xml",
    ],
    "assets": {
        # What every internal user downloads: the two ways into the console
        # and the loader that fetches the rest when one of them is used.
        # Every file is named, here and below: the compiled .js is not under
        # version control, so a glob would also pick up the .js that a renamed
        # or deleted .ts left behind. tests/test_asset_bundles.py checks that nothing
        # is left out.
        "web.assets_backend": [
            "app_builder_view/static/src/console/cog_menu_item.js",
            "app_builder_view/static/src/console/cog_menu_item.xml",
            "app_builder_view/static/src/console/console_loader.js",
            "app_builder_view/static/src/console/l10n.js",
            "app_builder_view/static/src/console/odoo.js",
            "app_builder_view/static/src/console/systray_item.js",
            "app_builder_view/static/src/console/systray_item.scss",
            "app_builder_view/static/src/console/systray_item.xml",
        ],
        # The console itself, fetched by console_loader.js when the client
        # action is first opened. The other addons add their panes here.
        "app_builder_view.assets_console": [
            # What the stylesheets need to compile on their own, as
            # web.assets_backend_lazy has it.
            ("include", "web._assets_helpers"),
            ("include", "web._assets_backend_helpers"),
            "web/static/src/scss/pre_variables.scss",
            "web/static/lib/bootstrap/scss/_variables.scss",
            "web/static/lib/bootstrap/scss/_variables-dark.scss",
            "web/static/lib/bootstrap/scss/_maps.scss",
            "app_builder_view/static/src/console/apply_dialog.js",
            "app_builder_view/static/src/console/apply_dialog.xml",
            "app_builder_view/static/src/console/canvas.js",
            "app_builder_view/static/src/console/canvas.scss",
            "app_builder_view/static/src/console/canvas.xml",
            "app_builder_view/static/src/console/canvas_views.js",
            "app_builder_view/static/src/console/canvases/search_lists_canvas.js",
            "app_builder_view/static/src/console/canvases/search_lists_canvas.xml",
            "app_builder_view/static/src/console/compat.js",
            "app_builder_view/static/src/console/console.js",
            "app_builder_view/static/src/console/console.scss",
            "app_builder_view/static/src/console/console_model.js",
            "app_builder_view/static/src/console/dnd.scss",
            "app_builder_view/static/src/console/drag.js",
            "app_builder_view/static/src/console/flows/create_package_flow.js",
            "app_builder_view/static/src/console/flows/create_package_flow.xml",
            "app_builder_view/static/src/console/flows/flow.js",
            "app_builder_view/static/src/console/flows/flow.xml",
            "app_builder_view/static/src/console/geometry.js",
            "app_builder_view/static/src/console/identity.js",
            "app_builder_view/static/src/console/options.js",
            "app_builder_view/static/src/console/outline.scss",
            "app_builder_view/static/src/console/outline_tree.js",
            "app_builder_view/static/src/console/outline_zones.js",
            "app_builder_view/static/src/console/overlay.js",
            "app_builder_view/static/src/console/panes.scss",
            "app_builder_view/static/src/console/panes/changes_pane.js",
            "app_builder_view/static/src/console/panes/changes_pane.xml",
            "app_builder_view/static/src/console/panes/home_pane.js",
            "app_builder_view/static/src/console/panes/home_pane.xml",
            "app_builder_view/static/src/console/panes/views_pane.js",
            "app_builder_view/static/src/console/panes/views_pane.xml",
            "app_builder_view/static/src/console/pending_widget.js",
            "app_builder_view/static/src/console/pending_widget.xml",
            "app_builder_view/static/src/console/record_pane/record_pane.js",
            "app_builder_view/static/src/console/record_pane/record_pane.xml",
            "app_builder_view/static/src/console/record_pane/record_pane_model.js",
            "app_builder_view/static/src/console/record_pane/row_editor.js",
            "app_builder_view/static/src/console/record_pane/row_editor.xml",
            "app_builder_view/static/src/console/shell/draft_model.js",
            "app_builder_view/static/src/console/shell/pane_registry.js",
            "app_builder_view/static/src/console/shell/shell.js",
            "app_builder_view/static/src/console/shell/shell.xml",
            "app_builder_view/static/src/console/shell/shell_model.js",
            "app_builder_view/static/src/console/sidebar/add_tab.js",
            "app_builder_view/static/src/console/sidebar/add_tab.xml",
            "app_builder_view/static/src/console/sidebar/field_editor_fallback.js",
            "app_builder_view/static/src/console/sidebar/field_editor_fallback.xml",
            "app_builder_view/static/src/console/sidebar/outline.js",
            "app_builder_view/static/src/console/sidebar/outline.xml",
            "app_builder_view/static/src/console/sidebar/properties_tab.js",
            "app_builder_view/static/src/console/sidebar/properties_tab.xml",
            "app_builder_view/static/src/console/sidebar/remove_flow.js",
            "app_builder_view/static/src/console/sidebar/view_tab.js",
            "app_builder_view/static/src/console/sidebar/view_tab.xml",
            "app_builder_view/static/src/console/split.js",
            "app_builder_view/static/src/console/top_bar.js",
            "app_builder_view/static/src/console/top_bar.xml",
            "app_builder_view/static/src/console/types.js",
            "app_builder_view/static/src/console/wire.js",
            "app_builder_view/static/src/console/zones.js",
        ],
        # What console_loader.js fetches instead when the web client is dark
        # (the color_scheme cookie), as web/views/view.js picks
        # web.assets_backend_lazy_dark: the same files, compiled with whatever
        # dark variables a theme or dark-mode addon adds to this bundle.
        "app_builder_view.assets_console_dark": [
            ("include", "app_builder_view.assets_console"),
        ],
        "web.assets_tests": [
            "app_builder_view/static/tests/tours/console_drag_tour.js",
            "app_builder_view/static/tests/tours/console_kanban_tour.js",
            "app_builder_view/static/tests/tours/console_new_field_tour.js",
            "app_builder_view/static/tests/tours/console_outline_tour.js",
            "app_builder_view/static/tests/tours/console_tour.js",
        ],
        # The hoot runner fetches no bundle on demand, so the console is part
        # of its setup.
        "web.assets_unit_tests_setup": [
            ("include", "app_builder_view.assets_console"),
        ],
        "web.assets_unit_tests": [
            "app_builder_view/static/tests/canvas_views.test.js",
            "app_builder_view/static/tests/compat.test.js",
            "app_builder_view/static/tests/console_loader.test.js",
            "app_builder_view/static/tests/console_model.test.js",
            "app_builder_view/static/tests/drag.test.js",
            "app_builder_view/static/tests/geometry.test.js",
            "app_builder_view/static/tests/identity.test.js",
            "app_builder_view/static/tests/lifetime.test.js",
            "app_builder_view/static/tests/outline.test.js",
            "app_builder_view/static/tests/outline_tree.test.js",
            "app_builder_view/static/tests/outline_zones.test.js",
            "app_builder_view/static/tests/record_sidebar.test.js",
            "app_builder_view/static/tests/systray_item.test.js",
            "app_builder_view/static/tests/zones.test.js",
        ],
    },
}
