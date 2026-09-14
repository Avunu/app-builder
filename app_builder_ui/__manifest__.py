{
    "name": "App Builder: Menus, Actions, Security & Automations",
    "summary": "Build menus, actions, access rules and automations into source",
    "version": "18.0.1.4.0",
    "category": "Technical",
    "website": "https://github.com/Avunu/app-builder",
    "author": "Avunu LLC",
    "license": "AGPL-3",
    "development_status": "Beta",
    "installable": True,
    "depends": ["app_builder_base", "base_automation", "web"],
    "assets": {
        "web.assets_backend": [
            "app_builder_ui/static/src/automations_menu_item.js",
            "app_builder_ui/static/src/automations_menu_item.xml",
            "app_builder_ui/static/src/console_items.js",
        ],
        "web.assets_tests": [
            "app_builder_ui/static/tests/tours/console_tabs_tour.js",
            "app_builder_ui/static/tests/tours/automations_pane_tour.js",
            "app_builder_ui/static/tests/tours/security_panes_tour.js",
            "app_builder_ui/static/tests/tours/menu_pane_tour.js",
        ],
    },
    "data": [
        "security/ir.model.access.csv",
        "views/studio_ui_views.xml",
        "views/studio_menus.xml",
    ],
}
