# Contributing to App Builder for Odoo

Thanks for looking. This is a young, single-maintainer project in beta, targeting Odoo
18.0 only; bug reports with a reproduction are as valuable as patches.

This file lives under `.github/` rather than the repository root because the standards
profile the repository follows reserves the root name.

## Reporting

- **Bugs and ideas:** open an issue at <https://github.com/Avunu/app-builder/issues>.
  Say which addon, the Odoo/OCB revision, how the server is run (`workers`, whether the
  addons path is writable) and, for anything about generated output, the generated file
  or diff.
- **Security problems:** do not open a public issue. Follow
  [SECURITY.md](../SECURITY.md).

## Setting up

The supported environment is the Nix dev shell; it pins OCB 18.0, OCA `server-ux`,
PostgreSQL, Node and every lint tool.

```sh
direnv allow                 # or: nix develop --no-pure-eval
odoo db provision            # a development database with this repository's addons
devenv up                    # PostgreSQL, Odoo, Mailpit and the TypeScript watcher
```

Entering the shell installs the Node dependencies and compiles the TypeScript. The
compiled `.js` beside each `.ts` is ignored by git: never commit it.

## Workflow

1. Branch from `develop`, the integration branch. Do not target `18.0`: that is the
   release branch, and only the release workflow moves it.
2. Keep a change inside the addon it belongs to where you can. Each addon is versioned
   on its own from the commits that touch it.
3. Add or adjust tests with the change (see below), and update the addon's `README.md`,
   and [CHANGELOG.md](../CHANGELOG.md) under "Unreleased" when a user would notice.
4. Open a pull request against `develop`. Its title and commits are checked against the
   commit convention; history is kept linear, so rebase rather than merge.

Do not bump `version` in a manifest. The release workflow does it.

## Commit messages

[Conventional commits](https://www.conventionalcommits.org), enforced by
`committed.toml`:

```
type(scope): lowercase subject, no trailing full stop
```

- `type` is one of `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`,
  `revert`, `style`, `test`.
- `scope` is optional. When present it is an addon name (`app_builder_view`) or one of
  `ci`, `deps`, `docs`, `tests`.
- `fix` bumps the addon's patch version, `feat` its minor, and `!` after the type or a
  `BREAKING CHANGE:` footer its major. A breaking change needs an entry with upgrade
  notes in the changelog, and a `migrations/` script if it renames or removes anything
  stored in a database.
- No merge commits, no `wip` or `fixup!` commits.

## Checks

All of these run in CI; run the ones your change touches before pushing.

```sh
# lint: prek (ruff, prettier, eslint, pylint-odoo, PO checks), manifests, ratchet
nix develop --no-pure-eval .#odoo-nix-lint -c odoo-nix gate lint

# types: pyright, tsc and the type-aware eslint (the manual hook stage)
prek run -c .pre-commit-config.yaml --hook-stage manual -a
npm run typecheck            # tsc alone
npm run lint:ts              # type-aware eslint alone

# tests: one addon while working, everything before a pull request
odoo test app_builder_view
odoo-nix gate test
```

`odoo-nix gate test` installs every addon on a fresh database and runs the Python tests,
the browser tours and the hoot unit tests, then fails on unexpected log lines. Paths a
`TransactionCase` cannot reach (install, upgrade, in-process reload) have probes under
`app_builder_base/tests/e2e/`; [DESIGN.md](../DESIGN.md#verification) says how to run
them.

What the suite is built around, and what a new serializer or operation has to keep true:

- **Round trip:** loading the generated files reproduces the database exactly.
- **Determinism:** an unchanged package re-serializes byte-identically.
- **No raw ids** in generated output; relations are always `ref="xmlid"`.

## Python and TypeScript

- Python is typed and checked by pyright; `tools/` modules are strict and free of Odoo
  imports. [TYPING.md](../TYPING.md) is the history of how that was done and the traps
  found. Its build and CI details predate the move to odoo-nix.
- User-facing strings go through `_()` / `self.env._()` in Python and `_t()` in
  TypeScript.
- The console reads the server version in exactly one place,
  `app_builder_view/static/src/console/compat.ts`. Keep it that way.

## Translations

Each addon with translatable terms has `i18n/<addon>.pot`, exported by Odoo itself.
Regenerate it when you add or change a translatable string. The export reads the
compiled `.js`, so it has to run where the TypeScript has been built (the dev shell does
that on entry), against a database with the addon installed:

```sh
odoo db provision
for addon in app_builder_*/; do
  addon=${addon%/}
  python -m odoo -c odoo.conf -d odoo_dev --no-http --stop-after-init \
    --modules="$addon" --i18n-export="$addon/i18n/$addon.pot"
done
```

`app_builder` itself has no terms and so no template. The bridge addons
(`app_builder_mail`, `app_builder_approval`, `app_builder_approval_formula`) are only
exported once installed; if the database does not have one, install it first with
`-i <addon>`. Commit only the templates whose terms changed: the export rewrites the
creation date in every file. Translations themselves (`i18n/<lang>.po`) are welcome as
pull requests.

## Licence

Contributions are accepted under the repository's licence, AGPL-3.
