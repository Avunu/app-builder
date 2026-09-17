# Typing plan — comprehensive strongly-typed code

This is the plan for moving the addons to strongly-typed Python (pyright) and
TypeScript on the frontend, with no change to how the addon ships: it is
still pip/whool-installable, `.ts` compiles to committed `.js`, and the OCA
CI container (py3.10, no node toolchain by default) still runs the suite.

Spiked before committing to it: `tsc`-emitted JS survives
`odoo.tools.js_transpiler.transpile_javascript` unchanged (same `odoo.define`
name and dependency list; only whitespace differs from transpiling the
original `.js`) — so real `.ts` sources with a committed emitted `.js` is
viable on Odoo 18 with zero change to the asset pipeline.

## Where it starts from

|                | Python                                                                  | JS                                                          |
| -------------- | ------------------------------------------------------------------------ | -------------------------------------------------------------- |
| Size           | ~23k lines (non-test) + 19k tests, 1 915 `def`s                          | ~20k lines: 26 Owl components, 56 RPC endpoints on 8 models     |
| Typing today   | 0 return annotations, 0 `typing` imports; 35 `@dataclass`es in `tools/`  | untyped; JSDoc prose, not type tags                             |
| Already on our side | OCB 18 is itself annotated: `Field[T]` generics, `search/browse/create -> Self`, and the *official* typed-relation syntax `partner_id: ResPartner = fields.Many2one(...)` (`odoo/odoo/modules/module.py:81-90`). odoo-nix already builds the merged `odoo` tree at `.devenv/state/pythonpath` a checker needs. | Odoo ships ambient types in `web/static/src/@types`: `@odoo/owl` -> the npm package's `.d.ts`, `@odoo/hoot` -> the lib source, a typed `services` registry, and a merge-able `GlobalRegistryCategories`. Odoo 18 uses `@odoo/owl@2.8.4`. |
| Constraints    | OCA CI runs py3.10 (`.github/workflows/test.yml`); `.ruff.toml` says py310 too. So: `from __future__ import annotations` everywhere, `Self`/`NotRequired` from `typing_extensions` as an external dependency. | The addon must stay pip/whool-installable with no node toolchain -> emitted `.js` is committed. Odoo's transpiler is regex-based, so emit must be "source minus types", nothing clever. |

## Decisions (with the alternative rejected)

1. **Checker = pyright, not mypy.** Same engine as Pylance (odoo-nix already
   seeds `python.analysis.extraPaths`), per-file `# pyright: strict`, and it
   infers through OCB's partly-annotated code instead of treating
   unannotated bodies as `Any`. No `odoo-stubs`: OCB 18's inline annotations
   plus the merged addons tree are the stubs. mypy only if a plugin is ever
   needed; nothing here needs one.

2. **TS checker = `tsc --noEmit`; emitter = esbuild**, per-file transform, in
   place. Not tsc-emit: type-checking needs `allowJs` to read Odoo's JS
   through `paths`, and tsc refuses to emit in place when JS inputs are in
   the program. esbuild honours `tsconfig` and produces exactly what the
   spike showed works. Enforce the split with `erasableSyntaxOnly` +
   `verbatimModuleSyntax` + `isolatedModules`: no enums, namespaces, or
   parameter properties, so the `.js` is always the `.ts` with types deleted.

3. **`.ts` colocated in `static/src/`**, emitted `.js` beside it. Import
   aliases (`@app_builder_view/console/compat`), hoot test locations and
   manifest globs are untouched; `git mv foo.js foo.ts` keeps blame.
   `.gitattributes` marks `static/**/*.js linguist-generated`. Alternative
   (separate `static/ts/` tree) buys nothing except a second directory to
   keep in sync.

4. **The wire contract is Python-first and generated.** RPC methods get
   annotated signatures returning `TypedDict`s; a ~150-line script
   introspects them (`inspect.signature` + `get_type_hints`, imports the
   module, no DB) and writes one `static/src/wire.d.ts` per addon: the
   payload types plus an `RpcMap` of `{model: {method: {args, result}}}`. A
   typed `rpc()` facade on the TS side consumes it, so annotating a Python
   signature *is* typing the TS caller. Hand-writing both sides and "keeping
   them in sync" is the thing that never happens.

5. **Migrate file-by-file, never big-bang.** With `allowJs` on, `.ts` files
   are strict while remaining `.js` files pass through unchecked; the tree
   always builds, every PR ships.

## Phase 0 -- Tooling foundation (workspace + odoo-nix)

- **Nix**: add `pyright`, `typescript`, `esbuild`, `nodePackages.prettier` to
  the shell. Start with `extraDevPackages` in the workspace `flake.nix`;
  once it settles, promote to an `odoo-nix.ide.typecheck` option in
  `modules/devenv.nix` alongside the existing `ide.*` options, so any
  workspace gets it.
- **Path resolution, one source for both languages**: a small script
  (`scripts/typecheck_paths.py`) that locates Odoo via `import odoo` and
  writes gitignored `tsconfig.paths.json` (`@web/*`, `@html_editor/*`,
  `@web_tour/*`, `@app_builder_*/*`, `typeRoots` -> `web/static/src/@types`)
  and the pyright `extraPaths`. Works identically in the Nix shell
  (`.devenv/state/pythonpath`) and in the OCA CI container (site-packages).
  Hook it into odoo-nix's `ideSetup` later, the same way it seeds
  `.vscode/settings.json`.
- **Node deps**: `package.json` at the addon repo root with `typescript`,
  `esbuild`, `pyright`, `@odoo/owl@2.8.3` (types only; see "Implemented so
  far" for why not `2.8.4`), `prettier`, `typescript-eslint`. `npm ci` in
  the shell hook (or just `npm install`, done for now).
- **Transpiler guard test**: `app_builder_base/tests/test_assets.py` runs
  `transpile_javascript` over every `static/**/*.js` and fails on any
  surviving `^import|^export` line (catches the one known trap: esbuild
  emitting `export {};` for a type-only module, which `EXPORT_OBJECT_RE`
  does not match).

## Phase 1 -- Python (no build step, so it goes first)

**1a. Configuration.** `[tool.pyright]` in the addon repo:
`typeCheckingMode = "standard"`, `strict = ["*/tools"]`,
`pythonVersion = "3.10"`, `include = ["app_builder*"]`. Ruff: add `ANN`
(annotations required), `TC` (typing imports under `TYPE_CHECKING`), `FA`
(future annotations), `PGH003` (no blanket `type: ignore`), `PYI`; `ANN`
off in `tests/`, `__manifest__.py`, `migrations/`. `typing_extensions` in
each addon's `external_dependencies`.

**1b. `tools/` strict first** (~7.5k lines, odoo-free by design --
`catalogue.py` says so in its own docstring). Order by dependency:
`catalogue`, `modelspec`, `domainspec`, `placement`, `manifest`, `pogen`,
`xml_writer`, `pycodegen`, `pyparse`, `scaffold`, `gitrepo`,
`migrationgen`, then `app_builder_view/tools/` (`view_options`,
`canvas_stamp`, `manualfield`). The dataclasses' `to_json()` methods get
`TypedDict` return types -- these are the first wire types. One PR per 2-3
modules.

**1c. Models** (`studio_package.py` 1.8k, `studio_view_editor.py` 3k, etc.):

- every signature annotated; `Self` for recordset-returning methods;
  `api.Environment` where an env is passed;
- relational fields typed with Odoo's own syntax:
  `workspace_id: StudioWorkspace = fields.Many2one("studio.workspace")`,
  imports under `TYPE_CHECKING` -- the exact remedy Odoo prints for the
  circular-import case;
- one helper for the untyped hole: `env["studio.package"]` returns
  `BaseModel`, so `app_builder_base/tools/typed.py` gets
  `def model(env, cls: type[M]) -> M` (one `cast` inside, none outside).
  Every `self.env["..."]` in our code goes through it;
- RPC methods (`@api.model` public methods called via `orm.call`) get
  `TypedDict` argument and return types in `<addon>/wire.py`. `canvas()`
  in `studio_view_canvas.py:42` is the model case: a nested dict literal
  that becomes `CanvasPayload`;
- strictness ratchet per file: `# pyright: strict` at the top the moment a
  file passes; `reportUnknownMemberType`-class rules on last, since they
  surface every `Any` OCB leaks.

**1d. Tests**: `basic` mode, no `ANN`; annotate only where it helps the
checker read `self.env` results (via the same helper).

**1e. Runtime enforcement (optional, late)**: `typeguard`'s import hook on
`app_builder_*.tools` during the test run only. Cheap on pure functions,
worthless on ORM code; decide after 1c.

## Phase 2 -- TypeScript, checker before rename

**2a.** `tsconfig.json`: `strict`, `noUncheckedIndexedAccess`,
`exactOptionalPropertyTypes`, `noImplicitOverride`,
`noPropertyAccessFromIndexSignature`, `verbatimModuleSyntax`,
`isolatedModules`, `erasableSyntaxOnly`, `allowJs: true, checkJs: false`,
`noEmit`, `target/module: es2022`, `moduleResolution: bundler`,
`include: ["*/static/src/**/*", "*/static/tests/**/*"]`,
`extends: ./tsconfig.paths.json`. Build script:
`esbuild --format=esm --target=es2022 --outbase=. --outdir=. <every .ts>`
(tsconfig read automatically).

**2b. Convert in dependency order, leaves first**, one PR per cluster;
each PR is `git mv`, add types, regenerate `.js`, run the hoot tests
touching it:

1. pure modules: `geometry`, `identity`, `compat`, `options`, `zones`,
   `outline_zones`, `outline_tree`, `canvas_views` -- these have hoot
   tests already, convert the tests with them;
2. `console_model`, `shell/shell_model`, `shell/draft_model`,
   `record_pane/record_pane_model` -- the Owl-free models, where types
   pay most (the files say "No Owl in here... so it can be tested and
   ported as it is");
3. `drag`, `overlay`, `split`, `shell/pane_registry`;
4. components: `canvas`, `top_bar`, `sidebar/*`, `panes/*`,
   `record_pane/*`, `flows/*`, `systray_item`, `cog_menu_item`,
   `apply_dialog`; then `app_builder_model`, `app_builder_ui`,
   `app_builder_report`, `app_builder_approval` static;
5. tours last (`web_tour` step types are thin; low value).

**2c. The framework boundary, fenced in one place.**
`app_builder_view/static/src/console/odoo.ts`: typed facades for
`useService("orm")`, `rpc`, `_t`, `Dialog` props, and the pane registry --
`app_builder.panes` declared by merging into Odoo's
`GlobalRegistryCategories`, which is what that interface exists for.
Component props: `interface Props` + `static props` both kept (Owl
validates the latter at runtime; XML templates are outside tsc's reach
either way). Lint with `typescript-eslint`'s five `no-unsafe-*` rules: the
TS-side equivalent of `reportUnknown*`, so an `any` leaking from Odoo's JS
shows up at the facade rather than spreading.

**2d. Wire consumption.**
`import type { CanvasPayload, RpcMap } from "@app_builder_view/wire"`;
`rpc("studio.view.editor", "canvas", viewId, options)` typed by `RpcMap`;
hoot `onRpc` mocks typed against the same map.

## Phase 3 -- Enforcement, CI, docs

- **pre-commit** (addon repo): local hooks for `pyright`, `tsc --noEmit`,
  the esbuild build, wire generation, `prettier`/`typescript-eslint` on
  `.ts` -- each "generated" hook fails when it modifies the tree, so a
  stale `.js` or `wire.d.ts` cannot be committed. Skipped in the
  pre-commit CI job (no Odoo checkout, no node_modules) via `SKIP=`;
  running for real in `test.yml`'s `typecheck` job, inside the OCB
  container -- see "CI: the OCA container's real layout" for exactly how
  that job resolves imports pyright/tsc need that a plain checkout
  cannot answer alone. Done, unlike the rest of Phase 3 below.
- **Workspace**: `.gitattributes`, `.vscode/settings.json` already seeded
  by odoo-nix -- add `typescript.tsdk`/`eslint.validate` and
  `python.analysis.typeCheckingMode` matching `pyrightconfig` (pyright's
  config wins when both exist, so keep them equal).
- **Docs**: this file plus a short pointer from `DESIGN.md`. Note in
  `FORWARD_COMPAT.md`: `tsconfig.paths.json` is regenerated per OCB
  series, and a 19.0 workspace type-checks against 19.0's `@types` -- a
  second, advisory CI job once 19.0 CI exists.
- **Ratchet to done**: `checkJs` never needed (converted files are strict
  from day one); when the last `.js` source is gone, drop `allowJs` from
  `include` (keep it for reading Odoo's sources) and turn on
  `reportUnknown*` for `models/`. That is the finish line.

## Known traps, so they are not rediscovered

- `export {};` from type-only modules -> `test_assets.py` (Phase 0).
  Type-only modules should be `.d.ts` anyway (`wire.d.ts`).
- `@odoo/owl`'s npm version trails the vendored `owl.js`, which OCB
  patches ahead of the npm tag (`2.8.4` in the vendored file, `2.8.3` the
  latest ever published) -- pin the npm package to whatever is actually
  published, not what the vendored file's own `version` constant says,
  and expect the two to disagree. Re-check both when bumping OCB series.
- Two of Odoo's own core files opt into per-file checking with a
  `//@ts-check` pragma (`model/relational_model/{relational_model,
  dynamic_group_list}.js`, as of this OCB checkout), which **overrides**
  the project's `checkJs: false` for that file alone -- a documented but
  easy-to-forget TS behavior. Anything that imports `@web/views/view`
  (nearly everything here) pulls these in transitively via `allowJs`, so
  `tsc --noEmit` reports their pre-existing errors as if they were ours.
  `scripts/typecheck.mjs` groups tsc's output into diagnostic blocks and
  drops every block whose file path leaves this repo (always via a `../`
  path-alias hop) -- not a path allowlist, a "did tsc have to leave this
  repo to find it" test. Re-run `npm run typecheck` after any OCB bump to
  confirm the split still holds; a new `//@ts-check` file inside a path
  this repo *does* own would need a different fix.
- Odoo's own ambient `@types/*.d.ts` files are not all safe to bulk
  `include`: `services.d.ts` and most of `@types/registries/*.d.ts` exist
  specifically to `import` real service/registry *implementation* modules
  and take their type with `typeof` -- which pulls those real `.js` files
  into the program too. `tsconfig.json`'s own `include` comment has the
  current, authoritative list and why each entry is there (it has grown
  past the original "pure types only" rule as real files needed more --
  `views_registry.d.ts`/`fields_registry.d.ts` for `ViewsRegistryItemShape`/
  `FieldsRegistryItemShape`, `fields.d.ts` for the field-definition types
  those need); do not duplicate that list here where it will go stale.
  `useService`/`services` (`services.d.ts` itself) still gets its own
  narrow, hand-written facade instead (Phase 2c), never Odoo's
  auto-generated one -- that one cascade really is the whole webclient,
  unlike a single view/field descriptor shape.
- No `owl.d.ts` in `include`, on either tsconfig: `@odoo/owl` is a real
  npm dependency (`package.json: types`) that resolves on its own, and
  OCB's ambient re-export of it (`declare module "@odoo/owl" { export *
  from "@odoo/owl/dist/types/owl"; }`) does not survive
  `moduleResolution: bundler` resolving its own wildcard `exports`
  subpath -- it silently resolves to nothing and shadows the real
  package's types with an empty ambient module. Symptom: `Module
  '"@odoo/owl"' has no exported member 'Component'` (or anything else
  real) the moment a file actually needs a named export from it, with no
  hint that the ambient file is the cause. Confirmed by removing it and
  watching the error disappear -- if it ever needs to come back for a
  different reason, re-test that resolution first.
- eslint's `no-unsafe-*` rules (Phase 2c) are configured
  (`eslint.config.mjs`) but **not enforced** -- not in the pre-commit
  hooks, not in CI. typescript-eslint's own program construction
  (tried `project` as both a relative and an absolute path, and
  `projectService: true` -- all three, same result) fails to resolve
  `tsconfig.json`'s ambient `registries`/other literal, non-glob
  `include` entries that reach outside this directory via `../../odoo/...`,
  and reports spurious `no-unsafe-*` findings on any file that touches a
  type from one of them. `npm run typecheck` (the real, enforced
  checker) and the TypeScript compiler API's own
  `getParsedCommandLineOfConfigFile` (what `tsc -p` itself calls) both
  pass the same code cleanly; narrowed as far as confirming
  `ts.parseJsonConfigFileContent` called directly with a *relative* base
  path silently drops those same entries, while an absolute one or
  `getParsedCommandLineOfConfigFile` does not -- typescript-eslint
  evidently still hits the relative-basePath path somewhere internal
  that no public `parserOptions` changes. `eslint.config.mjs`'s own
  top-of-file comment has the full account. Don't trust an eslint
  finding without cross-checking it against `npm run typecheck` first;
  don't wire eslint into a hook or CI job until this is actually fixed.
- Typed relational fields + circular imports: annotation syntax +
  `from __future__ import annotations`, never `fields.Many2one[Cls]` (that
  evaluates at import).
- `Field[T]` gives `str | Literal[False]` for `Char` -- under strict, every
  `record.name` needs narrowing. That is the ORM's real contract; the
  `tools/` boundary should take `str`, not `str | False`, and models
  narrow before calling.
- A dataclass field typed `str` that is actually built from `_lt(...)`
  (`LazyGettext`) throughout its real call sites is not a hypothetical --
  it is what `catalogue.py`'s `Row.label` etc. turned out to be (see
  "Implemented so far"). Before trusting a plain-looking field type in
  `tools/`, grep every constructor call, not just the file's own
  defaults.
- pyright over the merged 906-addon tree: keep `include` to the addon
  repo; the tree is `extraPaths` only, loaded on import.
- OCA CI is py3.10 while the workspace is 3.11: run pyright with
  `pythonVersion = "3.10"` so 3.11-only syntax fails locally, not in CI.
- The OCA CI container's addon layout (`oca_install_addons`) is not the
  odoo-nix workspace layout `tsconfig.json`/`pyrightconfig.json`'s
  relative paths assume -- see "CI: the OCA container's real layout"
  above for the CI-specific configs and the mirror script that cover the
  difference. Don't assume the `pre-commit.yml` `SKIP=` treatment
  generalizes to `test.yml` without checking a container's own layout
  directly, the way that section did.
- Any script under `scripts/` has to run on Node 20, not just whatever
  local dev happens to have (odoo-nix pins `nodejs_22`): the OCA CI
  container's Node comes from jammy's nodesource package, pinned at 20.
  `fs.globSync` (Node 22+) is the one this already caught
  (`scripts/build_ts.mjs`, rewritten to `readdirSync(...,
  { recursive: true })`, stable since 20.1); check any new Node API
  the same way before relying on it.
- Reading a nullable `this.<field>` again after a null-check loses the
  narrowing the moment any method/function call runs in between, even
  though the field itself was never reassigned -- distinct from the
  repeated-bracket-index trap above (that one is about index-signature/
  array reads, this one about instance properties and plain variables).
  `Boolean(a && b)` has the identical problem for a free function's own
  parameters: it does not narrow `a`/`b` for what follows, since
  `Boolean(...)` is an opaque call as far as control-flow analysis goes,
  same as any other function reference. Fix every time: capture the
  narrowed value into a local `const` right after the check, before
  anything else runs, or (for the `Boolean(a && b)` shape specifically)
  rewrite as an early `if (!a || !b) return ...;` guard instead
  (`drag.ts`: `onDragStart`, `watchRow`/`rowAt`, `teardown`; `samePlace`).
- TS interface extension requires an *overriding* property to be
  narrower than (or equal to) what it overrides, never wider -- so
  `interface B extends A { x: T | null }` does not compile if
  `A.x: T` (no `| null`). When a "resolved" shape and a "stored" shape
  genuinely need to disagree on a field's nullability (a resolver's own
  defaulting can produce `null`; nothing that builds the stored shape
  ever writes a literal `null`), the fix is one shared, wider type on
  *both* interfaces rather than fighting the extension direction
  (`pane_registry.ts`'s `PaneRegistration`/`PaneEntry`, `makeModel`).
- A category name registered with Odoo's generic `Registry` (`registry.category(name)`)
  does not compile unless `name` is a known key of `GlobalRegistryCategories`
  (`registries.d.ts`) -- core's own categories (`views`, `fields`, ...)
  get this via a `.d.ts` under `@types/registries/`; a category this repo
  invents (`app_builder.panes`) needs the identical `declare module
  "registries" { interface GlobalRegistryCategories { "the.category":
  ItemShape } }` augmentation, legal from any real `.ts` module, not only
  a `.d.ts` -- put it in the one file that creates the category until
  Phase 2c's `console/odoo.ts` facade exists to hold it instead
  (`pane_registry.ts`).

## Implemented so far

Phase 0 is done, with three corrections to the plan above that real tool
output forced (each is also in "Known traps" below):

- **No `scripts/typecheck_paths.py` generator.** The addon repo is always
  checked out at `modules/odoo-studio` in an odoo-nix workspace (README),
  so `tsconfig.json`'s `paths` (`@web/*` -> `../../odoo/addons/web/static/src/*`,
  etc.) and `pyrightconfig.json`'s `extraPaths`
  (`../../.devenv/state/pythonpath`, odoo-nix's own merged tree) are just
  committed, static, relative paths -- nothing to generate. The merged
  tree is still needed on the Python side (OCA repos like `web` are
  physically separate directories odoo-nix symlinks together), but not on
  the TS side: every `@web`/`@html_editor`/`@web_tour` import resolves
  under OCB's own single `odoo/addons/` tree.
- **pyright installed via npm, not uv/pip.** `uv add --group dev pyright`
  tries to resolve and build the *entire* workspace's dependency graph
  (including `psycopg2` from source, which needs `pg_config` outside
  Nix's own build environment) just to add one dev tool. The PyPI
  `pyright` package is itself a thin wrapper around the same npm package,
  so `package.json` (Phase 0's Node deps) lists `pyright` alongside
  `typescript`/`esbuild` and none of that resolution ever happens.
- **`@odoo/owl@2.8.3`, not `2.8.4`.** The vendored `web/static/lib/owl/owl.js`
  reports version `2.8.4`, but that has never been published to npm
  (latest is `2.8.3`); OCB ships a patched build ahead of the npm tag.
  `2.8.3` is the closest real package and ships the exact
  `dist/types/owl.d.ts` that `web/static/src/@types/owl.d.ts` re-exports,
  so it is the correct pin despite the version not matching exactly --
  noted for whoever next bumps it expecting a clean match.

Landed: `package.json`, `tsconfig.json`, `pyrightconfig.json`,
`scripts/typecheck.mjs` (tsc, filtered), `scripts/build_ts.mjs` (esbuild
emit, drift-checking), `.gitattributes` (per converted file),
`.prettierrc.json` (`tabWidth: 4`, matching `.editorconfig` -- prettier's
own defaults are 2, and would have fought every `.ts` file's actual
style), `eslint.config.mjs` (typescript-eslint, configured but **not**
enforced yet -- see "Known traps"), `app_builder_base/tests/test_assets.py`
(the transpiler guard), local pre-commit hooks + `SKIP=` in
`pre-commit.yml`.

First real conversions, both verified against the actual tools rather
than reasoned about:

- **Python (1b):** `app_builder_base/tools/catalogue.py` is `# pyright:
  strict` clean, with `TypedDict`s for every `to_json()` (`RowJSON`,
  `SectionJSON`, `WidgetJSON`, `OptionGroupJSON`, `CatalogueJSON`) -- the
  first real wire types. Annotating it surfaced a genuine latent gap, not
  just a missing annotation: `Row.label`/`help`/`Section.title`/etc. were
  typed (informally, by every literal in the file) as plain `str`, but
  every real caller (`app_builder_view/tools/view_options.py`, extensively)
  builds them from `_lt(...)` (`LazyGettext`), and the default
  `translate=identity` handed one straight through into a dict a
  `TypedDict` promises is `str` -- a value that would fail to
  JSON-serialize, several call frames away from here. Fixed by widening
  the fields to a `Label = str | LazyGettext` alias (imported only under
  `TYPE_CHECKING`, so the module keeps its own "free of any `odoo`
  import" guarantee) and replacing the default with `_default_translate`,
  which raises immediately naming the unresolved label instead of
  passing it on. No real call site was relying on the old silent
  behavior (every one already passes `translate=env._`); confirmed by
  grepping every `.to_json(`/`catalogue_json(` call site before making
  the change.
- **TypeScript (2b, cluster 1: done except tests).** `compat.ts`,
  `identity.ts`, `geometry.ts`, `options.ts`, `zones.ts`,
  `outline_zones.ts`, `outline_tree.ts`, `canvas_views.ts` -- every
  planned file in the cluster, leaf-first as planned (`options`/`zones`
  before `outline_zones`/`outline_tree`, both before `canvas_views`,
  which turned out independent of the rest and was done first). Two new
  shared files: `types.ts` for the node-table and drop-zone shapes
  (`StudioNode`, `NodeTable`, `DescribedTarget`, `Zone`, `DragPayload`,
  `OutlineRow`, ...) and `wire.ts`, the hand-kept TS mirror of
  `catalogue.py`'s `TypedDict`s (`RowJSON`, `WidgetJSON`, ...) that
  Phase 2d's generator will eventually replace. Every file is
  `noUncheckedIndexedAccess`/`exactOptionalPropertyTypes`-clean, and
  every one's emitted `.js` was checked against transpiling its
  pre-conversion original -- same `odoo.define` name and dependency
  list every time, confirming the conversion never widened or narrowed
  what a file actually imports. Left in JS: the `.test.js` hoot tests
  for these modules (still to convert) and everything outside cluster 1.

  Two more real bugs typing surfaced, on top of catalogue.py's
  `LazyGettext` one:

  - `StudioNode.label`/`node.pending` were flat wrong in `types.ts`'s
    first draft -- `label_of()` (`canvas_stamp.py`) returns a dict
    (`{shown, by, token, in_group}`), not the bare `"group"`/`"label"`
    string its `by` key holds; a first-pass misreading of the function
    that nothing caught until `outline_tree.ts` actually needed
    `.label.token`. Fixed as `FieldLabel`, with `pending` (a
    `kind: "pending"` ghost's staged-field info, previously not modeled
    at all) added alongside it, both transcribed from the real Python
    construction rather than the earlier guess.
  - `row.placeholder` in `options.js`'s `resolve()` was never a real
    field -- `RowJSON`/the Python `Row` dataclass have only
    `placeholder_from`. Every row whose `placeholder_from` was not
    `"field.string"` has therefore always resolved to `""`, silently,
    since before this migration. Left as-is (not this migration's bug
    to fix behavior for) but now a comment instead of a silent
    always-empty read.
  - `canvas_views.ts`'s first draft extracted `Registry.get` as a bare
    method reference to work around its two-argument JSDoc (see the
    file itself) -- `const oneArgGet = viewRegistry.get as ...`, then
    called it later. That unbinds `this`, and the real `get()` reads
    `this.content` -- a genuine latent bug the `unbound-method` lint
    rule caught before it ever ran, not a style complaint. Fixed with
    `.call(viewRegistry, ...)`.

  Also caught, and not a bug: `@odoo/owl` shadowed by its own ambient
  re-export. `tsconfig.json` originally included OCB's
  `@types/owl.d.ts` (`declare module "@odoo/owl" { export * from
  "@odoo/owl/dist/types/owl"; }`); once `canvas_views.ts` needed
  `Component`'s type, that import resolved to nothing (`Module
  '"@odoo/owl"' has no exported member 'Component'`). `@odoo/owl` is a
  real npm dependency with its own `package.json: types`, and OCB's
  ambient re-export does not survive `moduleResolution: bundler`
  resolving its own wildcard `exports` subpath -- it shadows the real
  package's types with an empty one. Dropped from `include`; `@odoo/owl`
  now resolves on its own, as it should.

- **TypeScript (2b, cluster 1's tests: done).** The seven `.test.js`
  hoot files exercising cluster 1's modules -- `compat`, `identity`,
  `geometry`, `zones`, `outline_zones`, `outline_tree`, `canvas_views` --
  are now `.test.ts`, strict-clean, with the same emitted-`.js`
  transpile-equivalence check applied as every other file. Drafted by a
  seven-agent Workflow fan-out (one file each, read-only, full context on
  the already-converted source modules and this migration's own house
  patterns), then applied and brought to a real, verified `tsc`-clean
  state by hand -- the parallel step is genuinely embarrassingly
  parallel (each file only reads), but the *verification* step is not:
  `scripts/typecheck.mjs` type-checks the whole project in one pass, so
  seven agents each running it mid-edit on a shared tree would have
  raced and misattributed each other's in-progress errors. Applying
  centrally, once, after every draft landed, avoided that without
  needing per-agent worktree isolation (whose own story is murky here
  anyway -- this repo is a submodule, and isolation semantics for a
  submodule nested under the outer workspace were not confirmed before
  the draft step, so drafting was kept read-only specifically to sidestep
  needing an answer).

  The agents' own drafts were unusually well-instrumented: each ran its
  own isolated `tsc` probes against hand-extracted fragments of the real
  vendor sources to test a hypothesis before committing to it in its
  draft, and flagged exactly where it could not verify something against
  a real compiler (drafting was read-only, so none of them could run the
  project's own `tsc`). That discipline paid off -- every one of their
  flagged uncertainties turned out to be a real, reproducible issue once
  checked for real, and none of their *confident* claims turned out
  wrong. Fixed centrally, all recurring across multiple files:

  - `mock_fields.js`'s `makeFieldGenerator` (`web/static/tests/
    _framework/mock_server/mock_fields.js`) returns `{ [name](props)
    {...} }[name]` -- a self-indexing extraction, named that way on
    purpose so the function's own `.name` shows up right in a
    stack trace. Because the property key is a non-literal `string`
    variable, TS infers the *object's* type with an index signature, and
    indexing it with another non-literal `string` (even one that happens
    to equal a real key at runtime) reads as `T | undefined` under
    `noUncheckedIndexedAccess` -- so every `fields.Char`/`fields.Integer`
    a mock model's field initializers call is typed as possibly
    undefined, even though the function always exists. `fields.Char!()`
    at each call site, with one shared comment per file explaining why.
  - `queryFirst` (`hoot-dom/helpers/dom.js`) has the same
    JSDoc-vs-runtime-arity mismatch `Registry.get` already had:
    `@param {QueryOptions} options` (no `[options]` brackets) makes tsc
    treat a second argument as required, but the real function
    destructures `arguments` itself and never branches on its length. A
    local `const findFirst = queryFirst as (target: string) => Element |
    null;` per file, not a passed-`undefined` workaround (confirmed by
    testing it: `QueryOptions` itself does not accept `undefined`, so an
    explicit `undefined` argument fails a plain type check even though
    it is fine at runtime -- the cast is what actually works, and is
    what `canvas_views.ts` already does for `Registry.get`).
  - `Object.fromEntries(rows.map((row) => [row.token, row]))`-style
    lookups (`outline_tree.test.ts`) resolve to the loose
    `(Iterable<readonly any[]>) => any` overload unless the `.map`
    callback's return is annotated as a real tuple. Typing it
    (`(row): [Token, OutlineRow] => [row.token, row]`) moves
    `Object.fromEntries` onto its real generic overload -- but that
    still returns a plain `Record<string, OutlineRow>`, an index
    signature, so ~19 `by.xxx.yyy` dot-accesses would each need bracket
    notation and a `!`. Since the fixture's tokens are a known, fixed
    set, naming them as a literal union (`type ByToken = "n0" | "n1" |
    ...`) and casting the `Record` to `Record<ByToken, OutlineRow>`
    turns every one into a real, always-present named property instead
    -- the same reasoning `identity.test.ts`'s un-annotated `NODES`
    already relies on for its own dot access, just asserted by hand here
    since `Object.fromEntries`'s return type can't carry literal keys on
    its own.
  - `mockSendBeacon`'s callback must return `boolean`
    (`Navigator["sendBeacon"]`'s real DOM signature) -- a test callback
    that only calls `expect.step(...)` (returning `void`) needs an
    explicit `return true;` (a mock "the beacon was queued" result,
    matching what a real success looks like; nothing reads the value
    besides the type checker).
  - `@odoo/hoot-mock` has no ambient module declaration at all --
    `hoot.d.ts` declares `@odoo/hoot` and `@odoo/hoot-dom` (each
    re-exporting a real lib file) but not their sibling
    `hoot/hoot-mock.js`, even though several tests import
    `animationFrame`/`mockSendBeacon`/etc. from it. A vendored gap, not
    fixable at the source; `app_builder_view/static/tests/hoot-mock.d.ts`
    is the same one-line re-export pattern `hoot.d.ts` uses for its two
    siblings, kept in our own tree, picked up by tsconfig's existing
    `*/static/tests/**` include entry with no new include line needed
    (ambient declarations are global to the program once loaded
    anywhere in it).
  - `identity.test.ts`'s first draft cast a *partial* node-table literal
    (`{kind, name}` per entry) directly `as NodeTable` -- exactly the
    `LabelStyle`-style shortcut this file's own "house patterns" section
    warns test drafts away from, and it does not typecheck (`neither
    type sufficiently overlaps with the other`): a raw `as` needs the
    source and target to already resemble each other, which a two-field
    literal and a fourteen-field interface do not, no matter how many of
    those fields the code under test actually reads. Fixed the same way
    `zones.test.ts`/`outline_tree.test.ts`'s siblings independently
    arrived at: a `node()` builder function with inert defaults for
    every `StudioNode` field the test never reads, called for each
    table entry -- a *declared function return type* gets the more
    lenient literal-assignability tsc uses for a `return` statement,
    which is why the same shape works through a function but not as a
    bare `as` on the object literal itself.
  - One file (`outline_tree.test.ts`) was written directly to disk by
    its drafting agent despite being told this was a read-only pass --
    caught by `git status` before applying anything, and its content
    matched the structured-output draft exactly (diffed byte-for-byte),
    so nothing was lost or inconsistent; treated as a harmless one-off
    rather than a sign the other six needed re-checking for the same
    thing (`git status` after the whole batch showed no other stray
    writes).
  - `scripts/build_ts.mjs` emitted an empty `hoot-mock.d.js` for the new
    ambient declaration file before this was caught: its `.ts`-suffix
    filter matches `.d.ts` too (`"hoot-mock.d.ts".endsWith(".ts")` is
    true), and esbuild happily "compiles" a type-only file into nothing
    rather than refusing. `.d.ts` excluded explicitly now -- unrelated
    to the Node-20 `fs.globSync` trap already on this list, just the
    same file catching a second, independent bug.

- **TypeScript (2b, cluster 2: done).**
  `shell/draft_model.ts`, `shell/shell_model.ts`,
  `record_pane/record_pane_model.ts`, `console_model.ts` -- converted in
  their real dependency order (`grep -n "^import"` on all four cluster-2
  files first: `draft_model.js` has no cluster-2 deps, `shell_model.js`
  imports `draft_model` + `pane_registry`, `record_pane_model.js`
  imports `compat` + `shell_model`'s `draft_model`, `console_model.js`
  imports `compat` + `draft_model` directly -- the fourth and largest at
  1634 lines, done last). Each is `noUncheckedIndexedAccess`-clean and
  transpile-equivalence-checked against its pre-conversion original the
  same way as cluster 1.

  Unlike cluster 1's node/zone vocabulary, this cluster's wire types are
  server RPC payloads, so `wire.ts` grew a new block traced straight to
  their Python construction rather than to client usage --
  `studio_model_draft.py`'s `load`/`_own_changes`/`pending_changes`,
  `modelspec.py`'s `FieldSpec`/`SelectionSpec` dataclasses (`asdict()`,
  so every field is always present, `None` becomes `null` rather than an
  absent key), `studio_workspace.py`'s `_package_dict`/`_apply_dict`/
  `user_prefs`, and `studio_record_surface.py`'s `catalogue`/`rows`/
  `describe` (plus `studio_automation_surface.py`'s `_describe_extra`
  override for the recursive `children` shape). `DraftPayload.spec`/
  `view`/`anchors` are deliberately left `unknown` -- nothing converted
  so far reads them; narrow when a real reader appears, per this
  migration's own rule against typing ahead of a consumer.

  `types.ts` also grew this cluster's shared vocabulary: `PaneEntry`/
  `PaneModel`/`PaneActivity`/`PaneContext` (the pane-registry contract
  every pane implements, traced to `shell/pane_registry.js`'s own
  docstring, not converted itself this turn), `OrmService`/
  `NotificationService` (promoted out of `draft_model.ts`'s first-draft
  local interfaces once `shell_model.ts` needed the same ones), and
  `OdooRpcError` (promoted out of `compat.ts`'s previously-private copy,
  which now imports it back). This is the first place `types.ts` imports
  from `wire.ts` (`PackageEntryJSON`, for `PaneContext.package`) --
  one-directional, and the module docstring now says so: the two files'
  concerns overlap exactly there and nowhere else.

  Two real fixes, not just missing annotations:

  - `OrmService.call` was first typed with three parameters
    (`model, method, args?`), matching every cluster-1-adjacent call
    site seen so far. `record_pane_model.ts` calls it with a fourth,
    `kwargs` (`this.orm.call(this.surface, "rows", [...], {...
    this.surfaceArgs})`), which does not fit a three-parameter
    signature. Checked against the real
    `web/static/src/core/orm_service.js` rather than widening blind:
    its actual signature is `call(model, method, args=[], kwargs={})`,
    four parameters. Widened `OrmService.call<T>` to match, which also
    retroactively validated every earlier three-argument call site (a
    strict subset of the real signature, not a coincidence).
  - `shell_model.ts`'s `paneModel()` first draft defensively
    null-checked `entry.makeModel(this)`'s result, because
    `PaneEntry.makeModel` was typed `(shell: unknown) => PaneModel |
    null`. Checked against every real registration
    (`grep -rn "makeModel:"` across `record_pane.js`, `views_pane.js`,
    `home_pane.js`, `changes_pane.js`, `flow.js`): every one is
    `(shell) => new SomeModel(...)`, never null -- an invariant the
    original JS relied on directly, not a case it guarded. Tightened
    `PaneEntry.makeModel` to drop `| null` and simplified `paneModel()`
    back to the original's own structure instead of adding a
    defensive branch the real code never had.

  One behavior-neutral fix forced by strict mode rather than found by
  it: `record_pane_model.ts`'s `moveChild` returned bare `undefined` on
  one early-exit path and a `Promise` on another, which a non-`async`
  function can't unify (`Type 'undefined' is not assignable to type
  'Promise<unknown>'`). Added `async`, matching how every sibling method
  (`_childMutate` etc.) is already declared.

  `console_model.ts` is the Views pane's own model and this cluster's
  largest file by a wide margin (1634 lines of source, the console's
  central RPC surface) -- most of the wire tracing this turn was reading
  `studio_view_editor.py`/`studio_view_canvas.py`/`studio_view_new_field.py`
  (`canvas`, `editing_context`, `describe_node`, `drop_at`,
  `apply_operation`, `field_types_for`, `search_elements`, `add_view`,
  ...) to give every RPC an exact answer shape rather than the widest
  type that would compile. Two module-placement and one wire-shape
  decision came out of that:

  - **`CanvasPayload` (and anything else that carries a `Token` or a
    `NodeTable`) lives in `types.ts`, not `wire.ts`**, discovered
    immediately -- `CanvasPendingEntry.token: Token` does not compile in
    `wire.ts`, since `Token`/`NodeTable` are `types.ts`'s own. Rather
    than open a second, reverse `wire.ts -> types.ts` import (breaking
    the one-directional rule cluster 2's own earlier findings just
    established), `CanvasPayload`, `DropSuccessResult` and their small
    helper shapes moved to `types.ts` instead -- which is where they
    belong anyway, per that module's own docstring ("the shapes the
    canvas payload and node table carry"). `wire.ts` keeps the rest of
    this same RPC surface (`EditingContext`, `OperationResult`,
    `NewFieldPlan`, ...), none of which touches a `Token`.
  - **`drop_at`'s three real return sites all answer the same
    `{stale, select, created, staged, canvas, history, draft}` shape**
    (`studio_view_editor.py:drop_at`, `studio_view_new_field.py:
    _drop_live_field`/`_drop_field_definition`) -- but a fourth site,
    the version check at the top of `drop_at`, answers only
    `{stale: true, canvas}`. `_mutate` unwraps that stale case
    internally and always resolves to `undefined` instead of handing it
    to its caller (already true before this turn, just not yet typed),
    so `DropSuccessResult` -- what a caller of `dropAt`/`drop` actually
    receives -- was named and typed *without* a `stale: true` member,
    rather than as the full four-shape union `drop_at` can literally
    answer. Typing ahead of what a reader gets, the same rule
    `DraftPayload.spec` already follows, just from the answer side this
    time instead of the request side.
  - **`_mutate`'s own generic signature can't be `<T extends
    MutateResult>`**, confirmed with a standalone probe before writing
    it into the file: TS's "weak type" check rejects a primitive (like
    the bare `true`/`true` `action_undo`/`action_redo` answer) against
    an all-optional interface with zero properties in common --
    `Type 'true' has no properties in common with type 'MutateResult'`.
    `_mutate<T>` is unconstrained instead, and reads the handful of
    fields it inspects (`stale`, `canvas`, `draft`, `created_name`,
    `select`) through a single cast of the opaque `result: T` to a
    local `RawMutateFields` interface (every field optional) -- proven
    by the same probe to type-check regardless of what `T` is
    instantiated to, including `boolean`, since the cast happens from
    an abstract generic parameter rather than from a known concrete
    type. `T` itself stays accurate to what each caller's `orm.call<T>`
    actually declares (`OperationResult`, `DropSuccessResult`, `boolean`
    for undo/redo); `RawMutateFields` is `_mutate`'s own internal
    escape hatch, not something any caller sees.

  One more small, real correction, caught the same way as the
  `PaneEntry.makeModel`/`OrmService.call` ones above -- widening rather
  than guessing narrower: `shell_model.ts`'s `ShellLearnedContext.view.model`
  was typed as bare `string`, accurate to every caller *at the time it
  was written*, before `editing_context()` itself had been traced.
  `console_model.ts` now carries that whole shape (`wire.ts:
  EditingContext`), which shows `view.model` is a plain Char field on
  `ir.ui.view` -- `False` for a model-less view, a QWeb report template
  being the one `editing_context` itself already handles. Widened to
  `string | false` to match; `learnContext`'s own read of it
  (`context.view && context.view.model`, used behind a truthy check) did
  not need to change.

  Also new this file: `_carryTarget`'s `this[key]` (`key:
  "buttonTarget" | "fieldTarget"`) writing back a value shaped
  differently per key does not compile -- TS resolves a generic-keyed
  write's target type as the *intersection* of every property the key
  could name, so a `ButtonDropTarget`-shaped value fails against
  `ButtonDropTarget & FieldDropTarget` even on the `"buttonTarget"`
  branch. Fixed by giving both properties the same `DropTarget` type,
  with the field-only members (`ttype`, `label`) optional -- confirmed
  compiling with a standalone probe first, the same way as the
  `_mutate` generic above, before it went into the file. `env.services.field`
  (`@web/core/field_service.js`, used by `inverseOptions`/`resolveRelated`
  on a live, non-Python-owned model) got the same narrow-facade
  treatment as `orm`/`notification` (`FieldService`, `FieldDefLite` in
  `types.ts`) since the vendor file's own JSDoc types every return as a
  bare `object`.

- **TypeScript (2b, cluster 2's own test: `console_model.test.ts`).**
  Of the five `.test.js` files a cluster-1 drafting agent had earlier
  flagged as candidates ("likely the same `makeFieldGenerator`/`override`
  patterns"), only this one actually imports cluster 2's own converted
  modules (`ConsoleModel`, `DraftModel`); `drag.test.js`, `outline.test.js`,
  `record_sidebar.test.js` and `systray_item.test.js` all import Owl
  components that are still `.js` (`drag.js`, `overlay.js`,
  `sidebar/outline.js`, `record_pane/record_pane.js`, `systray_item.js` --
  cluster 3/4 subjects), so converting their tests now would mean typing a
  test file whose subject is still untyped, ahead of the leaf-first order
  this migration has followed throughout. Left for their own clusters;
  only `console_model.test.ts` converted this turn.

  Real design finding, not just annotation: `console_model.ts`'s
  constructor originally took `shell: StudioShell` (the real ~30-member
  class, matching `record_pane_model.ts`'s own precedent of importing the
  real class for an accurate `shell` param). Writing this test surfaced
  that this contradicts `ConsoleModel`'s *own* docstring, word for word
  the same promise `DraftModel`'s makes ("so it can be tested and ported
  as it is") -- a constructor pinned to the full class would force a unit
  test to stub every member `ConsoleModel` never reads just to construct
  one. `grep -n "this\.shell\."` showed exactly four reads:
  `packageId`, `modelLabel`, `draft`, `learnContext(...)`. Added
  `ConsoleModelOwner`, a narrow interface naming only those four --
  mirroring `DraftModelOwner`'s own already-established pattern in
  `shell/draft_model.ts` -- and changed the constructor's `shell` param
  to it. The real `StudioShell` satisfies it structurally with no change
  on its own side (confirmed with a standalone probe: `const owner:
  ConsoleModelOwner = shell` where `shell: StudioShell`, compiles clean),
  so production wiring (`views_pane.js`'s `new ConsoleModel(shell.env,
  shell)`) is unaffected; the test can now build a plain object literal
  instead of a `StudioShell` stand-in.

  Every other finding was a mechanical consequence of the same strict
  flags cluster 1's tests already met, applied to a much larger fixture
  set (`node()`/`canvas()`/`editingContext()`/`draftPayload()` builder
  functions with inert defaults, the established fix for a partial
  literal not "sufficiently overlapping" its full interface on a bare
  `as`) -- with two new ones:

  - **A non-generic replacement function cannot be assigned to a
    generic method property.** Several tests reassign `model.orm.call`
    mid-test to record calls differently; `OrmService.call<T>` is
    generic, and TS checks a replacement against *every* instantiation
    of `T`, which a function returning one concrete shape cannot
    satisfy (`Type '{...}' is not assignable to type 'T': 'T' could be
    instantiated with an arbitrary type`) -- confirmed with a
    standalone probe before writing the real fix. Every mock now
    replaces `model.orm` wholesale with a properly generic
    `async call<T = unknown>(...): Promise<T>` method (`return X as T`
    internally, the same trust-the-caller escape hatch any mock of a
    generic method needs), rather than patching just `.call` on the
    existing object.
  - **`unbound-method` (the same rule that caught a real bug in
    `canvas_views.ts`, cluster 1) flagged `const original =
    model.orm.call`** at the three sites that capture the previous
    mock before installing a new one. This mock genuinely never reads
    `this` (its body only closes over `calls`/`model` from the
    enclosing test scope), so extraction is safe here -- unlike the
    `Registry.get` case -- but `.bind()` was not the fix: `Function.prototype
    .bind`'s own stdlib typing is not generic-preserving, which would have
    silently erased `<T>` from every later explicit-type-argument call.
    Wrapped in a small arrow function that closes over the captured
    `orm` object and calls `orm.call<T>(...)` explicitly instead --
    nothing is "unbound" because nothing is extracted, and the wrapper
    declares its own `<T>`.
  - Also, `NodeTable`/`CanvasPayload.nodes` is `Readonly` in production
    (the client never writes it), but two fixtures need to splice in one
    more node than `canvas()`'s own `entries` list can express (a nested
    subview field, a pending ghost); cast to `Record<Token, StudioNode>`
    at those two construction sites only, not a change to the type
    itself.

- **TypeScript (2b, cluster 3: done).** `overlay.ts`, `split.ts`,
  `shell/pane_registry.ts`, `drag.ts` -- the first cluster done with a
  Workflow (four read-only draft agents, `overlay`/`split`/`pane_registry`
  in parallel since none of the four import each other, `drag` afterward
  fed the finished `overlay.ts` draft since it needs `Overlay`'s real
  type for its own `overlay` constructor param). Applying, reconciling
  and verifying centrally against the real `tsc`/`eslint`/`prettier`/
  `esbuild`/transpiler-guard toolchain was still this session's own job,
  same division of labor as cluster 1's test conversions. One stray
  direct write (`split.ts`, despite the read-only instruction) recurred
  -- same as cluster 1's `outline_tree.test.ts` -- caught by `git status`
  and confirmed byte-identical to the structured-output draft before
  anything was applied.

  `pane_registry.ts` is the one file whose own shape had already been
  *guessed* from the outside, in cluster 2, before it existed as real
  code (`types.ts`'s `PaneEntry`/`PaneContext`, transcribed from the
  module's own docstring and from `shell_model.ts`'s reads). Converting
  the real file surfaced two genuine corrections to that guess:

  - **`sequence` was never a field of the stored entry.** The docstring
    lists it beside `label`/`icon` as if part of the value, but its own
    parenthetical already said otherwise ("sequence (add() option)") --
    every real `paneRegistry.add(key, value, options)` call passes it as
    `add()`'s own third-argument option, never inside `value`. Dropped.
  - **`Component`/`sidebar`/`makeModel`/`surface`/`flow` need to be named
    explicitly, not left to the index signature** -- `pane_registry.ts`
    itself reads all five by dot access in `resolvePane`'s own
    three-way branch, which `noPropertyAccessFromIndexSignature`
    disallows against a bare `[key: string]: unknown`. Renamed the guess
    `PaneEntry` to `PaneRegistration` (the *stored* shape) with
    `PaneEntry extends PaneRegistration { key: string }` for the
    *resolved* one, matching `resolvePane`'s own `{ key, ...registered }`
    construction.

  One correction to a **cluster 2 decision**, caught only once
  `pane_registry.ts`'s real `resolvePane` was in hand: `PaneEntry.makeModel`
  had been tightened to drop `| null` in cluster 2, reasoning that every
  real registration provides one. `resolvePane`'s own Component-branch
  default (`{ sidebar: null, makeModel: null, ...entry }` in the
  original JS) shows the *function* genuinely can produce a `null`
  `makeModel` on the resolved entry -- true today only because every
  actual registration happens to supply one, not because the function
  cannot do otherwise, and `shell_model.ts`'s own `paneModel()` already
  defends against exactly `!entry.makeModel`. Re-widened to
  `((shell: unknown) => PaneModel) | null` on both `PaneRegistration` and
  `PaneEntry` (one shared type, not two: TS interface extension requires
  an overriding property to be *narrower*, not wider, than what it
  overrides, so `PaneEntry` alone could not add `| null` back once
  `PaneRegistration` was declared without it). The general lesson this
  reversal confirms: typing to a function's *real, full* behavior can
  overturn an earlier decision made from a narrower vantage point, the
  same way `ShellLearnedContext.view.model` was widened in cluster 2
  itself once `EditingContext`'s real shape became available -- a
  decision is only as good as how much of the real source was visible
  when it was made, and revisiting one under fuller information is not
  churn.

  A new, real ambient-module pattern, not previously needed:
  `registry.category()`'s own real signature constrains its argument to
  a *known* key of `GlobalRegistryCategories` (the same interface
  `views_registry.d.ts`/`fields_registry.d.ts` already augment for core's
  own categories) -- `app_builder.panes`/`app_builder.console_tabs` are
  ours and were declared nowhere, so `registry.category("app_builder.panes")`
  could not compile at all. Fixed with a `declare module "registries" {
  interface GlobalRegistryCategories { "app_builder.panes": PaneRegistration;
  ... } }` block directly in `pane_registry.ts` -- legal from any real
  `.ts` module, not only a `.d.ts` (confirmed by a clean `tsc` run, the
  agent's own biggest flagged uncertainty). TYPING.md's Phase 2c
  `console/odoo.ts` facade is the eventual home for this declaration;
  until it exists, the one file that creates a category is where its
  augmentation lives.

  `drag.ts` (913 lines, the largest single file converted so far) found
  the same class of JSDoc-vs-runtime mismatch `Registry.get`/`queryFirst`
  already established, at the scale of a whole hook instead of one
  method: `useDragAndDrop`'s own JSDoc (`html_editor/utils/drag_and_drop.js`)
  types `helper` as zero-argument and a handler's `dropzone` as a bare
  `HTMLElement`, but the hook's real implementation always calls `helper`
  with one argument and hands handlers `ctx.current.dropzone` itself, an
  `{el, rect}` pair -- exactly what this file's original JS already read
  it as. Fixed the same way, at the scale of the whole hook: one cast,
  `useDragAndDrop as (params: CanvasDragHookParams) => DragHook`, traced
  to the real behavior rather than the JSDoc, confirmed compiling clean
  (the agent's own second-biggest flagged uncertainty).

  A genuinely new trap, distinct from the already-documented
  repeated-bracket-index one (which is about index-signature/array reads)
  and from `Overlay.align()`'s own precedent (a `NodeTable` index read) --
  add to "Known traps" below: **reading a nullable `this.<field>` after a
  null-check loses the narrowing the moment any method/function call
  intervenes before the later read**, even though the field itself was
  never reassigned. Hit repeatedly in `drag.ts` (`onDragStart`, `watchRow`/
  `rowAt`, `teardown`'s outline branch) and once on a free function's
  parameters (`samePlace`'s `Boolean(a && b)`, which does not narrow `a`/
  `b` for what follows since `Boolean(...)` is opaque to control-flow
  analysis). Fixed every time the same way: capture the narrowed value
  into a local `const` right after the check, before anything else runs.

  Two more, smaller: `DragPayload` gained `label?: string` (the chip/
  status-pill text `drag.ts:payloadFor` always sets, but `console_model.ts`'s
  own click-to-add construction sites never do -- optional, not required,
  a distinction the drafting agent's own research missed since it was
  scoped to `drag.ts`'s dependencies and did not cross-check
  `console_model.ts`'s *own* `DragPayload` literals; caught centrally by
  grepping every construction site before trusting the "always set" claim)
  and `component?: string | undefined` (a component tile's `payloadFor`
  can legitimately build one with `component: undefined` when the
  element's markup sets neither `data-key` nor `data-name`, which
  `exactOptionalPropertyTypes` treats as a different, stricter case than
  the key being merely absent).

- **TypeScript (2b, cluster 3's own test: `drag.test.ts`).** Converted
  right after cluster 3 itself, since `drag.test.js` imports `drag.js`
  and `overlay.js` directly (`makeCanvasDrag`, `Overlay`, `ZoneLayer`) --
  both just landed -- unlike the other cluster-3-adjacent test files
  (`outline.test.js`, `record_sidebar.test.js`, `systray_item.test.js`),
  which exercise Owl components still `.js` (cluster 4). The largest and
  most involved test converted so far: real Owl component mounting
  (`Harness`, `View`), a mock server model (`Partner`), and real drag
  gestures via `@odoo/hoot-dom`'s own `drag`/`hover`/`press` helpers.

  Real design fix, found the identical way `ConsoleModelOwner` was:
  `fakeModel()`'s own hand-written fake already matched a member-for-
  member subset of `CanvasDrag`'s real needs, and `grep -n
  "this\.model\."` on `drag.ts` confirmed exactly ten reads and nothing
  else (`nodes`, `canWrite`, `selectedNode`, `selection.token`,
  `viewType`, `outlineDrag`, `beginDrag`, `setDragCaption`, `endDrag`,
  `drop`) -- `CanvasDrag`'s constructor took the real `ConsoleModel`
  class regardless, the same gap `ConsoleModelOwner` closed for
  `console_model.ts` itself. Added `CanvasDragModel`, a narrow interface
  naming only those ten, mirroring `ConsoleModelOwner`'s own reasoning
  word for word (this class's docstring makes the identical "so it can
  be tested and ported as it is" promise). The real `ConsoleModel`
  satisfies it structurally with one real fix needed along the way:
  `viewType` had to be `string | false | undefined`, not just
  `string | false` -- `ConsoleModel.viewType`'s own real getter type
  includes `undefined` (from `ViewSummary`'s optional `type` field,
  `console_model.ts`), confirmed by the same kind of standalone
  structural-assignment probe used for `ConsoleModelOwner`
  (`const dragModel: CanvasDragModel = model` where `model: ConsoleModel`,
  run for real through `tsc` before trusting it). `OutlineDragProvider`
  was also exported from `drag.ts` for the same reason: the test's own
  `fakeOutline()` needed to be checked against the real contract rather
  than duck-typed blind.

  Three more real JSDoc-vs-runtime-arity/shape gaps in `@odoo/hoot-dom`,
  the same class of trap `Registry.get`/`queryFirst`/`useDragAndDrop`
  already established, found while typing this file specifically:

  - `queryOne`/`queryAll`/`queryFirst` (`hoot-dom/helpers/dom.js`) are
    none of them generic in their real signatures, despite their own
    JSDoc examples using them as tagged templates in a way that reads
    as if they were parameterized -- confirmed by `tsc` flatly rejecting
    `queryOne<HTMLElement>(...)` ("Expected 0 type arguments, but got 1").
    They return the DOM lib's
    own `Element`/`Element[]`, not `HTMLElement`. Since every element
    this fixture's own form/palette/outline ever produces genuinely is
    an `HTMLElement` (inputs, buttons, tabs, rows -- no SVG anywhere in
    it), narrowed once via three small wrapper functions
    (`queryOneEl`/`queryAllEl`/`queryFirstEl`) rather than an `as
    HTMLElement` at each of this file's several dozen call sites.
  - `queryFirst`'s own JSDoc marks `options` without `[brackets]`
    (required), so TS infers it as a mandatory second parameter -- the
    same `Registry.get`-style mismatch, confirmed here at a third real
    call site of the identical pattern; fixed the same way, a cast to
    the real one-argument-capable signature.
  - `moveTo`'s real position union (`Side | "${Side}-${Side}" | Position`,
    `hoot-dom/helpers/events.js`) has no `"center"` literal, but the real
    implementation (`getPosition`) computes the exact visual centre for
    any position string that names neither a horizontal
    (`"left"`/`"right"`) nor a vertical (`"top"`/`"bottom"`) side -- a
    real, working, undocumented fallback this file relies on at every
    one of its many `moveTo(..., { position: "center" })` calls. Fixed
    once, on `pickUp`'s own return type (a small `DragHelpersWithCenter`
    interface widening `moveTo`'s second parameter), rather than at each
    call site -- every `"center"` in this file goes through `pickUp`'s
    returned helpers.

- **Phase 2c: the framework boundary, fenced in one place (`console/odoo.ts`).**
  Built ahead of cluster 4 itself, at the user's own request, rather than
  discovered lazily as each component needed a piece of it -- grounded in
  real usage across the whole not-yet-converted tree
  (`grep -rn 'useService("'`/`"Dialog"` across every remaining `.js`) the
  same way every other file in this migration has been, not guessed from
  the plan's own one-line description of it.

  What actually landed, and why each piece is there:

  - **`useService`, overloaded per service name** (`orm`, `notification`,
    `dialog`, `action` -- the four real names `useService("...")` is
    called with anywhere in this tree, confirmed by grep before adding a
    fourth or a fifth). Reuses `types.ts`'s own `OrmService`/
    `NotificationService` rather than redeclaring them, so a component
    and the model it hands a service to agree on the same shape. Odoo's
    own `useService` is generic over `keyof import("services").ServiceFactories`
    -- the exact `@types/services.d.ts` cascade this file's own docstring,
    and TYPING.md's "Known traps" before it, explain this whole module
    exists to avoid pulling into the program.
  - **`DialogService`**, with `add`'s `props` parameter widened from the
    vendor's own `DialogServiceInterface` typedef (`props: {}`, an
    uncorrelated bare object) to a generic tied to whichever dialog class
    is actually passed: `Component<P>`'s own constructor takes
    `props: P`, so `add<P>(dialogClass: new (...) => Component<P>, props: P, ...)`
    makes a mismatched props object a real compile error, not just
    Owl's own runtime prop validation. A genuine improvement over the
    vendor's own looser typing, confirmed correct with a standalone
    probe (a real dialog class with a required prop, `@ts-expect-error`
    on a call missing it) before it went into the file -- and confirmed
    a second time when the obvious-looking `new (...args: unknown[]) =>
    Component<P>` form was tried first and turned out to reject the
    *valid* call: TS cannot unify a rest parameter typed `unknown[]`
    with a real constructor's own specific first parameter the way it
    can with `any[]`, which turns the check off for the constructor's
    parameter list specifically while still fully checking `props`
    against `P` at the call site. `any[]` it is, with a
    `typescript-eslint/no-explicit-any` disable comment on that one line
    (the project's `recommendedTypeChecked` preset enables that rule,
    unlike the five `no-unsafe-*` ones TYPING.md's own Phase 2c note
    already expected) -- placement matters: `eslint-disable-next-line`
    disables the *next* line only, so it has to sit directly above the
    `dialogClass:` parameter itself, not above the enclosing `add<P>(`
    a few lines higher, which silently disables nothing and reports its
    own "unused directive" warning instead.
  - **`DialogProps`**, transcribed directly from `@web/core/dialog/dialog.js`'s
    own `static props` runtime-validation schema. The one place in this
    file that types something ahead of a real consumer in this tree (no
    file has converted yet), but deliberately: unlike this addon's own
    wire shapes, a fixed, stable *vendor* component's props carry none of
    the "guessed wrong" risk that rule otherwise guards against here, and
    nine real files (`grep -rln "Dialog"`) render or wrap this one
    component, so one shared shape is worth having before the first of
    them converts.
  - **`ActionService`/`ActionDescription`/`ActionController`**, narrowed
    to exactly what the two real callers (`cog_menu_item.js`,
    `systray_item.js`) construct and read -- a plain `ir.actions.client`
    descriptor (never `ActionRequest`'s other variants: a numeric id, an
    xml id, a bare tag string) and `currentController.action.res_model`/
    `.currentState.resId` off a real `Controller` object far larger than
    what either file reads.
  - **`app_builder.panes`/`app_builder.console_tabs`'s `GlobalRegistryCategories`
    augmentation, moved here from `shell/pane_registry.ts`.** That file
    carried the identical `declare module "registries"` block for one
    commit (cluster 3), specifically because `console/odoo.ts` -- its
    real, planned home -- did not exist yet; `pane_registry.ts`'s own
    comment said so at the time. No import needed to bring the
    declaration into `pane_registry.ts`'s scope: a `declare module`
    augmentation merges into the whole program once any file carrying it
    is part of the compilation, regardless of which file that is, and
    both files sit under the same `tsconfig.json` `include` glob.
  - **`rpc` and a stringifying `_t` wrapper were deliberately left out**,
    both explained in the file's own docstring rather than just omitted
    silently: `rpc` (`@web/core/network/rpc`) has no real caller anywhere
    in this tree (every server round trip already goes through
    `orm.call`; `compat.ts`'s own mention of `core/network/rpc.js` is
    about that module's cache-invalidation bus, not a call site) -- typing
    a facade nothing calls would be typing ahead of a reader for the
    first time in this migration's own Phase 2c note, not the last.
    A `_t` wrapper that eagerly stringified (`String(_t(...))`, the
    pattern every file so far already writes at the point it is needed)
    would be the wrong *default* for a future file that wants to hand a
    *lazy* translated value to a component prop instead, so Owl's own
    reactivity can re-render it on a language change -- nothing in this
    tree does that yet, but a facade cannot un-invent a wrong default
    once files start depending on it.

## CI: the OCA container's real layout

Phase 3 planned a `typecheck` job in `test.yml`'s OCB container. This was
first filed as open ("this was not able to inspect [the layout] from
here") and then actually built once the real sources
(`Avunu/oca-ci`'s `Dockerfile` and `bin/*` scripts) were available to read
directly. Read, not guessed:

- **Odoo core is at `/opt/odoo`**, `pip install -e`'d straight into
  `/opt/odoo-venv` (the Dockerfile's own README affirms both: "Odoo source
  code is in `/opt/odoo`", "Odoo is installed in editable mode"). So
  `odoo`/`odoo.addons.web` resolve from the venv alone -- no `extraPaths`
  needed for core, unlike local dev's `odoo/` submodule.
- **`$ADDONS_DIR` is `.`** -- this repo's own checkout root, the same
  directory `pyrightconfig.json`/`tsconfig.json` already sit in.
  `oca_install_addons` only tells Odoo's *runtime* loader about it (a
  plain `addons_path=...,.` line in `odoo.cfg`); it does nothing for a
  standalone `pyright`/`tsc` run, which never executes that runtime.
  Whatever this repo's OWN addons depend on *each other* for gets
  pip-installed for real as a side effect of resolving dependency
  metadata (`oca_list_addons_to_test_as_url_reqs` turns each into a
  `file://` constraint), but nothing guarantees every addon here is such
  a dependency of another. `scripts/ci_addons_mirror.py` closes exactly
  that gap: one symlink per addon (anything with a `__manifest__.py`)
  into a synthetic `odoo/addons/` tree, the same trick odoo-nix's own
  `ide.enable` mirror uses locally for sibling OCA repos, just scoped to
  this repo's own addons since everything else is already resolvable one
  way or the other.
- **TS only ever imports OCB core** (`@web`, `@html_editor`, `@web_tour`
  -- no OCA JS), so the TS side needs nothing beyond the one absolute
  prefix, `/opt/odoo/addons`.

`pyrightconfig.ci.json` and `tsconfig.ci.json` are full standalone
configs, not `"extends": "./..."` variants of the local ones -- checked
directly against this repo's own installed `typescript`, `extends` does
**not** merge an object-valued key like `compilerOptions.paths`, it
replaces it outright, which would have silently dropped every
`@app_builder_*` alias the moment a CI-only override touched `@web/*`.
`scripts/typecheck.mjs` takes `TSC_PROJECT` so the same script drives
both (`TSC_PROJECT=tsconfig.ci.json` in CI); the vendor/ours split
(previously "does the path start with `../`") was rewritten to actually
resolve each reported path against the repo root, since CI's vendor
paths are absolute (`/opt/odoo/...`), not relative.

One more container fact worth having found before it broke silently:
`codename` for `py3.10-*18.0` is **jammy** (`oca-ci`'s own build matrix),
which ships **Node 20**, not 22 -- unlike odoo-nix's local dev shell,
pinned to `nodejs_22`. `scripts/build_ts.mjs` originally used
`fs.globSync`, added in Node 22; rewritten to a plain
`readdirSync(..., { recursive: true })` walk (stable since 20.1) so the
same script runs unmodified in both places. Filed as a "Known trap"
below too, since the next script added under `scripts/` will hit the
same ceiling if it reaches for a glob helper without checking.

None of this has been run inside the actual container -- there was no
way to do that from here. It is grounded in the container's real,
directly-inspected sources rather than assumed, and every path/script
that could be exercised locally was (the mirror script actually makes
`odoo.addons.app_builder_base` importable; both tsconfigs parse and
resolve exactly as expected, failing only on the container-specific
absolute paths that do not exist in this sandbox). The first real CI run
is still the first real verification.

## Order of work and rough size

| # | PRs | What lands |
| --- | --- | --- |
| 0 | 2 (workspace/odoo-nix, addon repo) | shell tooling, path generator, tsconfig/pyright configs, transpiler guard test, CI job |
| 1b | ~6 | `tools/` strict |
| 1c | ~8 | models annotated, typed helper, `wire.py` per addon + generator |
| 2b-d | ~10 | JS -> TS in the cluster order above, facade, typed rpc |
| 3 | 2 | enforcement hooks, docs, ratchet |

Phases 1 and 2 are independent after Phase 0 and can interleave; Phase 2d
depends on 1c for the wire types, so 1c should land before the component
clusters.
