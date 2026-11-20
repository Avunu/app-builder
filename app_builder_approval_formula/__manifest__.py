{
    "name": "App Builder: Approval rules with formulas",
    "summary": "Write Python-conditioned approval rules to source",
    "version": "18.0.2.0.0",
    "category": "Technical",
    "website": "https://github.com/Avunu/app-builder",
    "author": "Avunu LLC",
    "license": "AGPL-3",
    "development_status": "Alpha",
    "installable": True,
    # Follows app_builder_approval, which is itself opt-in: once that is
    # chosen and the formula engine is there, a formula rule must not be
    # dropped from the generated source without saying so.
    "auto_install": True,
    "depends": ["app_builder_approval", "base_tier_validation_formula"],
    "external_dependencies": {"python": ["typing_extensions"]},
    "data": [],
}
