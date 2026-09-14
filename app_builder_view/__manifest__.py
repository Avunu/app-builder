{
    "name": "App Builder: View Editor",
    "summary": "Edit views visually; every change becomes an inheriting view in source",
    "version": "18.0.1.2.0",
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
    "data": [
        "security/ir.model.access.csv",
        "views/studio_view_editor_views.xml",
        "views/studio_console_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "app_builder_view/static/src/console/**/*",
        ],
        "web.assets_tests": [
            "app_builder_view/static/tests/tours/console_tour.js",
            "app_builder_view/static/tests/tours/console_drag_tour.js",
            "app_builder_view/static/tests/tours/console_new_field_tour.js",
            "app_builder_view/static/tests/tours/console_kanban_tour.js",
        ],
        "web.assets_unit_tests": [
            "app_builder_view/static/tests/**/*.test.js",
        ],
    },
}
