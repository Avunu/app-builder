{
    "name": "App Builder: View Editor",
    "summary": "Edit views visually; every change becomes an inheriting view in source",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "website": "https://github.com/Avunu/app-builder",
    "author": "Avunu LLC",
    "license": "AGPL-3",
    "development_status": "Beta",
    "installable": True,
    "depends": ["app_builder_base", "web"],
    "data": [
        "views/studio_view_editor_views.xml",
        "views/studio_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "app_builder_view/static/src/studio_editor.js",
            "app_builder_view/static/src/studio_editor.xml",
            "app_builder_view/static/src/studio_editor.scss",
        ],
    },
}
