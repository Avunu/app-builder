# Changelog

Notable changes to App Builder for Odoo, newest first. Addon versions follow the OCA
scheme `<odoo series>.<major>.<minor>.<patch>`; the part after the series is bumped per
addon by the release workflow from the conventional commits that touched it (`fix:`
patch, `feat:` minor, `!` or `BREAKING CHANGE` major), so addons can sit at different
versions. This file records what a user or integrator needs to know, not every commit:
`git log -- <addon>` is the complete history.

Only Odoo **18.0** is supported. Seven addons are Beta, and `app_builder_approval` and
`app_builder_approval_formula` are Alpha. Until an addon is declared Production/Stable,
a major bump may come without a migration script, and this file will say so.

## Unreleased

### Added

- `i18n/<addon>.pot` translation templates for every addon that has translatable terms,
  exported by Odoo and including the console's TypeScript `_t()` strings.
- This changelog, a contributing guide (`.github/CONTRIBUTING.md`) and a "Scope and
  limits" section in the README stating the supported deployment: Odoo 18.0, a
  development database, a writable addons path, one process (`workers = 0`), one
  database per source tree.

### Changed

- Documentation corrected: the read-only guard is described as the temp-file probe it
  is, not `os.access`; the test recipe is `odoo-nix gate test` or `odoo test <addon>`;
  `PLAN.md` opens with the current state and keeps the original gap analysis as an
  appendix; references to files that no longer exist are fixed.

## 18.0.2.0.0 — 2026-11-19

All nine addons. **Breaking.** The project was renamed from its working name to _App
Builder for Odoo_ (commit `58b94f0`), and the rename reaches the database schema and the
generated source, not only the titles.

### Changed (breaking)

- **Models renamed `studio.*` → `builder.*`**: `studio.package` → `builder.package`,
  `studio.domain` → `builder.domain`, `studio.owned.mixin` → `builder.owned.mixin`,
  `studio.model.draft` → `builder.model.draft`, the `studio.serializer.*` family →
  `builder.serializer.*`, and every other model the addons define. Their tables are
  named after them (`studio_package` → `builder_package`, and so on).
- **Security groups renamed**: XML ids `app_builder_base.group_studio_user` and
  `group_studio_manager` → `group_builder_user` and `group_builder_manager`.
- **The marker around generated Python changed** from `# begin: studio-generated schema`
  / `# end: studio-generated schema` to `# begin: builder-generated schema` /
  `# end: builder-generated schema`, and the prefix of builder-owned methods from
  `_studio_` to `_builder_`.
- Python modules, XML ids, CSS classes and client-side module names carrying `studio`
  were renamed to `builder` throughout. Module titles are now "App Builder: …".
- **Compiled JavaScript is no longer committed.** The console's TypeScript is compiled
  by each addon's `build` script (esbuild); the Nix dev shell and Nix builds run it. A
  plain clone has no `.js` until it is built.
- The repository moved to odoo-nix's addons mode and Avunu's Odoo standards profile:
  managed CI, pre-commit configuration, conventional commits checked by
  `committed.toml`, and a release flow that bumps versions on `develop` and
  fast-forwards the series branch `18.0`.

### Upgrade notes

**There is no migration from 1.x, and upgrading a 1.x database in place is not
supported.** No addon ships a `migrations/` script for the rename. Running
`-u app_builder` on a database that had the pre-rename addons installed would create the
new `builder_*` tables empty and leave the old `studio_*` tables, their access rules and
the old groups' memberships orphaned: every package, workspace and apply record the
builder kept would be gone from its point of view.

The pre-rename addons were never published as a release (the public repository was
created after the rename), so this is expected to affect only databases built from a
development checkout. For one of those, the following is the intended route. It has not
been scripted or tested, so try it on a copy first:

1. **The addons you generated are unaffected at runtime.** A generated package is an
   ordinary Odoo addon that does not depend on the builder; it keeps installing and
   running whatever happens to the builder's own tables.
2. On the database you build in, uninstall the 1.x builder addons _before_ switching the
   checkout, which removes the `studio.*` models and groups cleanly, then install 2.0.0.
   Starting from a fresh development database works equally well and is simpler.
3. In each generated package's Python files, rename the marker comments
   (`studio-generated schema` → `builder-generated schema`) and any `_studio_`-prefixed
   builder-owned method to `_builder_`. Until then the builder does not recognise its
   block in those files.
4. Bring each package back under the builder from its directory and use **Reload from
   disk**. Files are the source of truth, so nothing else has to be carried over.
5. Give users the new groups (_Builder User_, _Builder Administrator_); memberships of
   the old groups do not transfer. System administrators get _Builder Administrator_
   automatically.

## Before 2.0.0

Development versions under the project's working name (addons at 18.0.1.0.0 to
18.0.1.6.0), never tagged or published. The history is in `git log`; the design record
is in [DESIGN.md](DESIGN.md), [PLAN.md](PLAN.md) and [TYPING.md](TYPING.md).
