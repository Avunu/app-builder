{
    "name": "App Builder Base",
    "summary": "Engine for visually built Odoo modules that live in source control",
    "version": "18.0.1.6.0",
    "category": "Technical",
    "website": "https://github.com/Avunu/app-builder",
    "author": "Avunu LLC",
    "license": "AGPL-3",
    "development_status": "Beta",
    "installable": True,
    "depends": ["base"],
    "data": [
        "security/app_builder_security.xml",
        "security/ir.model.access.csv",
        "views/studio_package_views.xml",
        "views/studio_menus.xml",
    ],
}
