{
    "name": "App Builder: Approval rules",
    "summary": "Turn on tier validation in the builder, and write the rules to source",
    "version": "18.0.2.0.2",
    "category": "Technical",
    "website": "https://github.com/Avunu/app-builder",
    "author": "Avunu LLC",
    "license": "AGPL-3",
    "development_status": "Alpha",
    "installable": True,
    # Chosen, not automatic. The serializer half would be safe to install
    # wherever base_tier_validation is -- a rule created here must not be
    # dropped from the generated source without saying so -- but the addon
    # also overrides tier.definition and offers the gate, and an Alpha
    # feature has no business arriving unasked on a database that merely
    # uses OCA tier validation and installs the (Beta) builder core.
    "auto_install": False,
    "depends": ["app_builder_base", "base_tier_validation"],
    "external_dependencies": {"python": ["typing_extensions"]},
    "assets": {
        # The console is fetched on demand (app_builder_view): its panes go
        # in its bundle, not in what every internal user downloads.
        "app_builder_view.assets_console": [
            "app_builder_approval/static/src/console_items.js",
        ],
        "web.assets_tests": [
            "app_builder_approval/static/tests/tours/approvals_pane_tour.js",
        ],
    },
    "data": [],
}
