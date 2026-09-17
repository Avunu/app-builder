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
  into the program too. `owl.d.ts`, `odoo.d.ts`, `hoot.d.ts`, `libs.d.ts`,
  `qunit.d.ts`, `registry.d.ts` and
  `registries/services_registry.d.ts` do not do this and are the ones
  `tsconfig.json` includes; `useService`/`services` gets its own narrow,
  hand-written facade instead (Phase 2c), never Odoo's auto-generated one.
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
`app_builder_base/tests/test_assets.py` (the transpiler guard), local
pre-commit hooks + `SKIP=` in `pre-commit.yml`.

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
- **TypeScript (2b, cluster 1, partial):** `compat.ts`, `identity.ts`,
  `geometry.ts` converted (leaf-first, as planned), plus a new
  `types.ts` for the node-table shapes (`StudioNode`, `NodeTable`,
  `PlainRect`, `BoxRect`, `Point`, `Token`) they all share --
  transcribed from `canvas_stamp.py`'s actual construction of a node,
  not guessed from usage. `noUncheckedIndexedAccess`,
  `exactOptionalPropertyTypes` and the rest of `strict` are on and
  clean for all three. Remaining leaves in cluster 1 (`options`,
  `zones`, `outline_zones`, `outline_tree`, `canvas_views`, and their
  `.test.js` files) are still JS.

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
