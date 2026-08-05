{
    "name": "App Builder: Approval rules",
    "summary": "Turn on tier validation from the studio, and write the rules to source",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "website": "https://github.com/Avunu/app-builder",
    "author": "Avunu LLC",
    "license": "AGPL-3",
    "development_status": "Alpha",
    "installable": True,
    # Nothing to choose: if both sides are installed, an approval rule created
    # here would otherwise be dropped from the generated source without saying
    # so, which is the same reason app_builder_mail installs itself.
    "auto_install": True,
    "depends": ["app_builder_base", "base_tier_validation"],
    "data": [],
}
