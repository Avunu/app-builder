{
    "name": "App Builder: PDF reports",
    "summary": "Create PDF reports, and edit existing ones as inheriting views",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "website": "https://github.com/Avunu/app-builder",
    "author": "Avunu LLC",
    "license": "AGPL-3",
    "development_status": "Alpha",
    "installable": True,
    # web supplies the layouts a generated report calls: web.html_container,
    # web.external_layout, web.internal_layout.
    "depends": ["app_builder_base", "app_builder_ui", "app_builder_view", "web"],
    "data": [
        "security/ir.model.access.csv",
        "views/studio_report_views.xml",
        "views/studio_menus.xml",
    ],
}
