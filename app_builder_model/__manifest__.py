{
    "name": "App Builder: Models & Fields",
    "summary": "Visually build models and fields that are written to source",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "website": "https://github.com/Avunu/app-builder",
    "author": "Avunu LLC",
    "license": "AGPL-3",
    "development_status": "Beta",
    "installable": True,
    "depends": ["app_builder_base", "web"],
    "assets": {
        "web.assets_backend": [
            "app_builder_model/static/src/composer/composer.js",
            "app_builder_model/static/src/composer/composer.xml",
            "app_builder_model/static/src/composer/composer.scss",
            "app_builder_model/static/src/composer/field_popover.js",
            "app_builder_model/static/src/composer/field_popover.xml",
            "app_builder_model/static/src/console_items.js",
            "app_builder_model/static/src/console_items.xml",
        ],
        "web.assets_tests": [
            "app_builder_model/static/tests/tours/composer_tour.js",
        ],
    },
    "data": [
        "security/ir.model.access.csv",
        "views/studio_model_views.xml",
        "views/studio_composer_views.xml",
        "views/studio_menus.xml",
    ],
}
