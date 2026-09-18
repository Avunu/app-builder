{
    "name": "App Builder: Discuss bridge",
    "summary": "Write mail and SMS settings into source alongside the rest",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "website": "https://github.com/Avunu/app-builder",
    "author": "Avunu LLC",
    "license": "AGPL-3",
    "development_status": "Beta",
    "installable": True,
    # Nothing to configure and nothing to choose: if both sides are present,
    # the settings below are already reachable in the UI and would otherwise be
    # dropped from the generated source without saying so.
    "auto_install": True,
    "depends": ["app_builder_base", "mail"],
    "external_dependencies": {"python": ["typing_extensions"]},
    "data": [],
}
