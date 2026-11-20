{
    "name": "App Builder: PDF reports",
    "summary": "Create PDF reports, and edit existing ones as inheriting views",
    "version": "18.0.2.0.2",
    "category": "Technical",
    "website": "https://github.com/Avunu/app-builder",
    "author": "Avunu LLC",
    "license": "AGPL-3",
    "development_status": "Beta",
    "installable": True,
    # web supplies the layouts a generated report calls: web.html_container,
    # web.external_layout, web.internal_layout.
    "depends": ["app_builder_base", "app_builder_ui", "app_builder_view", "web"],
    "external_dependencies": {"python": ["typing_extensions"]},
    "assets": {
        # The console is fetched on demand (app_builder_view): its panes go
        # in its bundle, not in what every internal user downloads.
        # Named file by file: a glob would also load the compiled .js that a
        # renamed or deleted .ts left behind.
        "app_builder_view.assets_console": [
            "app_builder_report/static/src/console_items.js",
            "app_builder_report/static/src/console/report_canvas.js",
            "app_builder_report/static/src/console/report_canvas.scss",
            "app_builder_report/static/src/console/report_canvas.xml",
        ],
        "web.assets_tests": [
            "app_builder_report/static/tests/tours/report_editor_tour.js",
        ],
        "web.assets_unit_tests": [
            "app_builder_report/static/tests/report_canvas.test.js",
        ],
    },
    "data": [
        "views/builder_report_views.xml",
    ],
}
