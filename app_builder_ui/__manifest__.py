{
    "name": "App Builder: Menus, Actions, Security & Automations",
    "summary": "Build menus, actions, access rules and automations into source",
    "version": "18.0.1.2.0",
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
        ],
    },
    "data": [
        "security/ir.model.access.csv",
        "views/studio_ui_views.xml",
        "views/studio_menus.xml",
    ],
}
