{
    "name": "App Builder: PDF reports",
    "summary": "Create PDF reports, and edit existing ones as inheriting views",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "website": "https://github.com/Avunu/app-builder",
    "author": "Avunu LLC",
    "license": "AGPL-3",
    "development_status": "Beta",
    "installable": True,
    # web supplies the layouts a generated report calls: web.html_container,
    # web.external_layout, web.internal_layout.
    "depends": ["app_builder_base", "app_builder_ui", "app_builder_view", "web"],
    "assets": {
        "web.assets_backend": [
            "app_builder_report/static/src/console_items.js",
            "app_builder_report/static/src/console/**/*",
        ],
        "web.assets_tests": [
            "app_builder_report/static/tests/tours/report_editor_tour.js",
        ],
    },
    "data": [
        "security/ir.model.access.csv",
        "views/studio_report_views.xml",
        "views/studio_menus.xml",
    ],
}
