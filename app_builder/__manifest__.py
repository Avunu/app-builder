{
    "name": "App Builder",
    "summary": "Open-source visual builder whose output is real source code",
    "description": """
App Builder
===========

A visual builder for Odoo models, fields, views, menus, actions, access rules
and automations -- like Odoo Studio, but the output is **ordinary source code
from the first keystroke** rather than database rows with a one-time,
irreversible export.

Every change writes both the database record and the corresponding file in a
real addon directory, inside the same transaction. That means you can:

* review a studio change as a normal ``git diff``;
* hand-edit the generated files and reload them back into the builder;
* ship customizations through your existing branch/CI/deploy pipeline;
* run production from a read-only checkout, where the builder disables itself.

Generated modules are data-only, so models, fields, views and automations all
become live without restarting the server.
""",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "website": "https://github.com/Avunu/app-builder",
    "author": "Avunu LLC",
    "license": "AGPL-3",
    "development_status": "Beta",
    "installable": True,
    "application": True,
    "depends": [
        "app_builder_base",
        "app_builder_model",
        "app_builder_view",
        "app_builder_ui",
        "app_builder_report",
    ],
    "external_dependencies": {"python": ["typing_extensions"]},
    "data": [],
}
