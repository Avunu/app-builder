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
        "security/ir.model.access.csv",
        "views/studio_view_editor_views.xml",
        "views/studio_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "app_builder_view/static/src/wysiwyg/selection.js",
            "app_builder_view/static/src/wysiwyg/options.js",
            "app_builder_view/static/src/wysiwyg/view_editor.js",
            "app_builder_view/static/src/wysiwyg/view_editor.xml",
            "app_builder_view/static/src/wysiwyg/view_editor.scss",
            "app_builder_view/static/src/wysiwyg/cog_menu_item.js",
            "app_builder_view/static/src/wysiwyg/cog_menu_item.xml",
        ],
        "web.assets_tests": [
            "app_builder_view/static/tests/tours/view_editor_tour.js",
        ],
    },
}
