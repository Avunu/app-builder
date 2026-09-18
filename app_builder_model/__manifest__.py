{
    "name": "App Builder: Models & Fields",
    "summary": "Visually build models and fields that are written to source",
    "version": "18.0.1.1.0",
    "category": "Technical",
    "website": "https://github.com/Avunu/app-builder",
    "author": "Avunu LLC",
    "license": "AGPL-3",
    "development_status": "Beta",
    "installable": True,
    # The console (app_builder_view) is the one builder: Compose opens a
    # model in it, and the field editor below is registered into it.
    "depends": ["app_builder_base", "app_builder_view", "web"],
    "external_dependencies": {"python": ["typing_extensions"]},
    "assets": {
        "web.assets_backend": [
            "app_builder_model/static/src/field_popover.js",
            "app_builder_model/static/src/field_popover.xml",
            "app_builder_model/static/src/console_items.js",
            "app_builder_model/static/src/console_items.xml",
            "app_builder_model/static/src/flows/build_app_flow.js",
            "app_builder_model/static/src/flows/build_app_flow.xml",
            "app_builder_model/static/src/flows/adopt_model_flow.js",
            "app_builder_model/static/src/flows/adopt_model_flow.xml",
        ],
        "web.assets_tests": [
            "app_builder_model/static/tests/tours/build_app_tour.js",
        ],
    },
    "data": [
        "views/studio_model_views.xml",
        "views/studio_composer_views.xml",
        "views/studio_menus.xml",
    ],
}
