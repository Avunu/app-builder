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
  **Corrected by the first real file that tried it (`studio_package.py`,
  see "Known traps"): this syntax does not actually type-check under this
  real OCB/pyright combination for `Many2one`/`One2many`/`Many2many`
  alike.** The house convention is now the opposite of this bullet: leave
  the field declaration exactly as originally written (no LHS annotation,
  no subscript), and `cast()` at each real *read* site instead, the same
  idiom `pycodegen.py` already established in Phase 1b for a plain-
  string-comodel relational field. The `TYPE_CHECKING`-guarded import for
  the comodel class is still exactly right -- only the field declaration
  itself changes.
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
- **Never coerce a `_t(...)` value while a module body is running**
  (`String(_t(...))`, a template literal, `+`, `.trim()` -- anything that
  calls its `toString`). Odoo's module loader starts every non-lazy module
  the moment it is defined, while the asset bundle is still being
  evaluated; translations only arrive later, when the web client's
  `localization` service starts. Until then `_t` returns a
  `LazyTranslatedString`, whose `toString` *throws* `translation error`.
  The throw escapes `odoo.define`, which the bundle calls at its top level,
  so it aborts **the rest of the bundle**: on the live dev server this took
  126 modules with it, `@web/main`/`@web/start` included -- every backend
  page rendered blank. Keep module-load values lazy (the `Translated` type,
  `console/l10n.ts`) and stringify where they are read. `tsc` cannot see
  this; the tours and the hoot suite do (Phase 3, below).
- eslint's `no-unsafe-*` findings were real, not a tooling bug. The
  earlier entry here (and `eslint.config.mjs`'s own comment) blamed
  typescript-eslint's program construction for "spurious" findings; a
  program built exactly the way `tsc -p` builds it, handed to eslint
  through `parserOptions.programs`, reported the identical 245. The actual
  cause: untyped vendor JS (`allowJs`, `checkJs: false`) can carry
  TypeScript's `error` type -- `translation.js`'s own JSDoc names
  `Markup`/`LazyTranslatedString`, types that file never declares, so
  `_t`'s whole return type collapses to `error` -- and `checkJs: false`
  suppresses the diagnostic that would have said so. `tsc` then reports
  nothing, because an `any` flowing into typed code is legal; the
  `no-unsafe-*` rules exist precisely to flag it. `_t` alone accounted for
  154 of ~200. Typed at the boundary now -- `_t` in `console/l10n.ts`,
  `user.hasGroup` in `console/odoo.ts`, the RPC bus in `console/compat.ts`,
  hoot's `MockServer.env` per test file -- and the last 51 findings (event
  bus, `user.hasGroup`, `JSON.parse`, mock-server handles, three
  `Translated`-in-a-template sites, two dead declarations) are gone.
  **eslint is enforced: 0 findings**, via the `eslint-ts` pre-commit hook
  and a `typecheck`-job step (`TSC_PROJECT=tsconfig.ci.json`, `eslint.
  config.mjs` reads it). Two config choices, both reasoned rather than
  reflexive: `no-unused-vars` ignores rest-siblings (`const { a, ...rest }`
  is how a key is stripped from an object), and `require-await` is off
  under `static/tests/` (test doubles implement the async service
  interfaces with synchronous bodies). The CI step has not run in the
  container, like the rest of that job.
  When eslint and `tsc` disagree, check the type the checker actually
  resolves (`checker.getTypeAtLocation`, `type.intrinsicName ===
  "error"`) before calling either one wrong.
- **Typed relational fields (`field: Cls = fields.Many2one("model")`,
  TYPING.md's own Phase 1c plan text) do not actually type-check, for any
  of `Many2one`/`One2many`/`Many2many` -- superseded by the finding
  below, once a real model file (`studio_package.py`) tried it.** Two
  independent, compounding failures, both confirmed with isolated
  probes (with and without `fields.Many2one[Cls](...)`-style explicit
  subscripting, neither fixes either failure): the *declaration* itself
  fails (`Many2one[Cls]`/`One2many[Cls]`/`Many2many[Cls]`, the
  constructed field-descriptor instance's own type, is never assignable
  to the declared attribute type `Cls` -- not a descriptor-protocol
  special case pyright applies to a class-body assignment); and
  `_Relational.__get__` (`odoo/fields.py`) carries no return annotation
  of its own, so every *read* of the field independently infers a
  messy, partially-`Unknown` union regardless of the declaration.
  `odoo/odoo/modules/module.py`'s own `TYPED_FIELD_DEFINITION_RE`
  (originally cited as proof this syntax works) is Odoo's own
  source-*scanning* tool for a different purpose entirely, not a
  type-checker -- citing it as confirmation was an unverified
  assumption that the first real attempt broke. Fix, the new house
  convention: leave the field declaration exactly as it was (no LHS
  annotation, no subscript, `from __future__ import annotations` still
  present as usual), and `cast("Cls", record.field_name)` at each real
  *read* site instead -- the same idiom `pycodegen.py` already
  established in Phase 1b for a plain-string-comodel relational field
  (`record.selection_ids`). `TYPE_CHECKING`-guarded imports for the
  comodel class are still exactly right; only the declaration's own
  annotation is dropped. Confirmed to recur immediately one level
  deeper too: `IrModelFields.model_id`/`IrModelSelection.field_id`
  (core Odoo's own plain-string-comodel relational fields) hit the
  identical gap the moment this file read them.
- Same-addon cross-file imports (real or `TYPE_CHECKING`) must stay
  **relative** (`.studio_package_apply`, `..tools.lxml_types`), never
  the fully-qualified `odoo.addons.app_builder_base....` form -- this
  repo is reachable under two different pyright module identities at
  once (`app_builder_base.*` via `pyrightconfig.json`'s own `include`;
  `odoo.addons.app_builder_base.*` via `extraPaths`' merged odoo-nix
  tree, which mirrors this same repo). Importing a same-addon name
  absolutely analyzes it under the *other* identity than this file's
  own relative `..tools` imports use, so two types that print
  identically (confirmed with `ModelSpec`, imported both ways at once)
  are NOT the same type to pyright, and every call passing one where
  the other is expected fails. The fully-qualified `odoo.addons....`
  form stays correct, and is the only option, for genuinely external
  repos reached only through the merged tree (`base`, `web`, ...) --
  `pycodegen.py`'s own `IrModel`/`IrModelFields` imports, already
  landed, are exactly that case and need no change.
- `app_builder_base/tools/typed.py`'s `model(env, cls)` needs a real,
  runtime-bound `cls` (it reads `cls._name` at runtime) -- it cannot be
  called with a class imported only under `TYPE_CHECKING` (a real
  `NameError` at runtime, not just a type error). Two real model
  classes with a genuine circular reference (`StudioPackage` <->
  `StudioPackageApply`/`StudioPackageModel`, see the dependency map in
  "Implemented so far") therefore cannot use `typed.model()` for each
  other while only one side of the cycle is converted -- `cast("TheOther
  Class", self.env["the.other.model"])` against the unchanged original
  call is the right fix for exactly this circular case, leaving
  `typed.model()` for every reference that is either non-circular or a
  core-Odoo lookup.
- `self._assert_studio_manager()`/`self._assert_studio_user()`/
  `self._assert_studio_group(...)` (`studio_security.py`'s own guard
  methods, "called first in every studio method reachable over RPC" per
  its own docstring) are invisible to pyright on every real caller:
  every `studio.*` model that composes `studio.security.mixin` does so
  through Odoo's own registry-level `_inherit = ["studio.security
  .mixin"]`, never a literal Python base class, so nothing in the
  class's own MRO carries those methods as far as the type checker can
  see. `studio_package.py` alone needed `cast("StudioSecurityMixin",
  self)._assert_studio_manager()`/`._assert_studio_user()` at 8 call
  sites. Given `studio_security.py`'s own docstring, this will recur in
  nearly every remaining Phase 1c model file -- worth a shared
  `typed.py` helper (e.g. `def security(self: BaseModel) ->
  StudioSecurityMixin: return cast("StudioSecurityMixin", self)`) once
  a second file confirms the same shape, rather than building it from
  this one file's evidence alone.
- `fields.Selection([...])`'s own inline-list form hits a real,
  pre-existing (confirmed against the untyped original too, not
  introduced by this migration) vendor-stub gap:
  `Selection.__init__`'s own `selection` parameter (`odoo/fields.py`)
  carries no annotation at all, only a bare `SENTINEL` default, so
  pyright infers the parameter's effective type from that default alone
  and rejects the field's own normal `list[(value, label)]` literal
  form. Fix: a narrow `# pyright: ignore[reportArgumentType]` on the
  declaration line, one per inline `Selection([...])` list -- likely to
  recur in every model file with one.
- `@api.model_create_multi` (`odoo/api.py`) is a bare passthrough
  decorator (`def model_create_multi(method: T) -> T`) that does not
  widen `create()`'s own declared `list[ValuesType]`-only signature to
  also cover the single-dict calling form it genuinely accepts at
  runtime (the decorator wraps a lone dict into `[vals]`, calls the real
  method, and unwraps the result back to one record) -- the same shape
  of decorator-stub gap already documented for `@tools.ormcache`. Fix: a
  narrow `# pyright: ignore[reportArgumentType]` at each `create({...})`
  call site, keeping the exact original single-dict call rather than
  rewriting it to `create([{...}])` -- changing the argument shape
  actually passed at runtime is outside a typing-only pass's mandate,
  however harmless that particular rewrite would likely be.
- `Environment.cr` is declared `BaseCursor` (`odoo/api.py`), which has
  no `.execute`/`.commit` of its own -- those live only on the real
  `Cursor` subclass every live request actually gets. The same shape of
  "declared type too abstract for what is really there at runtime" gap
  already documented for `Environment.user`. Fix: `cast("Cursor",
  self.env.cr)` at each real call site (raw SQL via `.execute()`, an
  explicit `.commit()`) -- `Cursor` importable `TYPE_CHECKING`-only from
  `odoo.sql_db`.
- The `_inherit`-mixin-invisible-to-pyright pattern (above) recurs
  identically for `super()`, not only `self`: a subclass overriding a
  `studio.serializer` method and calling `super()._should_skip(...)` (to
  extend rather than fully replace the base behavior) fails with
  `Cannot access attribute "..." for class "object"` the moment the
  class's own real Python base is *only* `models.AbstractModel` --
  confirmed as a genuine, pre-existing pyright error against the
  untyped original in `base_automation_serializer.py`, not introduced by
  typing it. `app_builder_base/tools/typed.py` now carries the matching
  pair for `studio.serializer` specifically: `serializer(self)` (the
  `self`-side fix, mirroring `security()`) and `serializer_super(sup)`
  (the `super()`-side fix, `cast()` on the proxy object itself -- a
  documented runtime no-op, so the real MRO dispatch `super()` performs
  is unchanged). Confirmed recurring across at least three of wave 1's
  own files before the helpers existed to use.
- A field reached only through Odoo's `_inherits`/`delegate=True`
  mechanism (e.g. `ir.cron.model_id`/`.name`, delegated from
  `ir_actions_server_id`) is not resolvable by casting `record` to the
  real, concrete delegating class either -- the attribute is never
  declared in that class's own Python body, so pyright cannot see it
  there any more than it can see it on the generic `BaseModel`.
  Different from the `_inherit`-mixin trap above (there, a real
  composing class exists to cast to; here, none does). Fix: `cast("Any",
  record)` at the one read site, honest about there being no real class
  in this codebase's own tree that actually carries the attribute.
  Likely to recur for any other `_inherits`/`delegate=True` chain (most
  of `ir.actions.*`'s own delegation hierarchy uses the same mechanism).
- `fields.Reference(...)` (and, by the same construction, any other
  `Field` subclass with no `__get__` override of its own) inherits its
  read type from its base descriptor class rather than what it actually
  returns at runtime -- `ir.ui.menu.action`, a core `Reference` field,
  reads back as `str | Literal[False]` (`Reference` extends `Selection`,
  `Selection(Field[str | Literal[False]])`) instead of the real
  recordset `Reference.convert_to_record` produces. The same shape as
  the already-documented `Environment.cr`/`Environment.user`
  "declared type too abstract for what's really there" gap, just not
  previously called out for `Reference` specifically. Fix: `cast` at the
  read site to the honest type (`BaseModel` here, since the target model
  varies per record) -- no behavior change.
- `app_builder_base/tools/lxml_types.py`'s `LxmlElement.iter()` was
  declared zero-argument (every prior reader only ever walked the whole
  subtree) -- extended to `iter(self, tag: str | None = None)` the
  moment a real reader (`ir_ui_view.py`'s `node.iter("button")`) needed
  lxml's real tag-filtered form. Real lxml also accepts `*tags`
  (multiple tag names/wildcards); narrowed to the one-tag form actually
  called anywhere in this codebase rather than the fuller variadic
  signature nothing yet needs -- extend further only once a second real
  reader needs it, the same "narrow, extend on real need" discipline
  this Protocol has followed since Phase 1b.
- `StudioSerializer._sort_key`'s own base declaration (`-> tuple[int,
  str]`) was too narrow the moment real subclass overrides existed --
  every one of wave 1's own five overrides returns a wider, differently
  -shaped tuple (`(int, int, str)`, `(int, int, int, str)`, `(int, bool,
  str)`, `(int, int, str, str)`), each a real, deliberate tie-break, and
  none of them trip `reportIncompatibleMethodOverride` (that check only
  fires across a real Python base-class relationship, confirmed
  empirically -- `_inherit`-only composition is invisible to it the same
  way it's invisible to everything else in this trap list). Widened the
  base to `tuple[int | str | bool, ...]`, the honest common shape every
  real override already satisfies without its own divergent annotation
  -- the same "downstream evidence corrects an earlier, too-narrow base
  signature" move already made once for `StudioSerializer._for_model`
  (wave 0's own `BaseModel | None` narrowed to `StudioSerializer |
  None`). `studio_package.py`'s own two local dict types (`buckets`/
  `csv_rows` in `_render_files`) needed the identical widening, since
  they store `_sort_key`'s return value directly -- the only real
  caller, and it never indexes into the tuple, only compares/sorts by
  it whole, so the widening cost it nothing.
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
- **Owl components, four facts cluster 4 (the first real components
  converted) established, all confirmed directly against
  `node_modules/@odoo/owl/dist/types/runtime/component.d.ts` rather than
  guessed:**
  - `override` is needed for *any* class member sharing a name with one
    declared in `Component`'s own class body -- `static template`
    (required, `string`), `static props`/`static defaultProps` (both
    optional) and the instance method `setup(): void` all four need it.
    An earlier framing of this rule as "needed because the base member
    is optional" is imprecise (two independent agents caught and
    corrected it identically): `template` is *required* and still needs
    `override`. `static components` needs *no* `override` because it is
    not a `Component` class-body member at all -- it lives on the
    separate `StaticComponentProperties`/`ComponentConstructor` types
    Owl's registry/`xml` machinery uses instead.
  - Owl components initialize fields in `setup()`, called synchronously
    right after construction, never in a constructor this code writes
    its own. TS's `strictPropertyInitialization` only inspects a real
    constructor, so it cannot see that `setup()` always runs first --
    every field `setup()` unconditionally assigns (even to a literal
    `null`/`false`) needs a definite-assignment assertion (`field!: T`);
    a field only ever assigned later, in a lifecycle method like
    `attach()`, is instead typed `T | undefined` with no assertion,
    since that genuinely is its state before that method first runs.
  - `typeof Component` (Owl's bare, unparameterized component-class
    type) is **not** assignable from a concrete `Props`-parameterized
    subclass, in either direction: assigning a real component class to a
    field/parameter typed `typeof Component` fails ("Two different types
    with this name exist, but they are unrelated" -- contravariant
    constructor-parameter checking against the generic
    `new <Props=any,Env=any>(...)` signature). Fix: write the field as
    `typeof Component<any, any>` instead of the bare form, with an
    `eslint-disable-next-line @typescript-eslint/no-explicit-any` on
    that line -- confirmed with a standalone probe before applying it
    tree-wide, to every registry-item-shape field that names a component
    class (`PaneRegistration.Component`/`.sidebar`,
    `PaneResolverResult.Component`/`.sidebar`, `CogMenuItem.Component`,
    `SystrayRegistryItemShape.Component`,
    `ViewWidgetsRegistryItemShape.component`,
    `fieldEditorComponent()`'s own return type) and to `odoo.ts`'s new
    `"app_builder.field_editor"` category entry.
  - `ev.target` is `EventTarget | null`, not `Element` -- the JS idiom
    `target.closest && target.closest(...)` (checking whether
    `.closest` exists at all) does not translate, since `EventTarget`
    has no `.closest` property, not even an optional one. Fix: `const
    target = ev.target instanceof Element ? ev.target : null;`, then
    plain `target && target.closest(...)` from there.
- A vendor `.js` component class with no `@extends {Component<Props>}`
  JSDoc (e.g. `@web/core/confirmation_dialog/confirmation_dialog.js`)
  does not carry `Component`'s own instance members into TS's inferred
  type at all under this project's `checkJs: false` -- `InstanceType<typeof
  ConfirmationDialog>` has no `.render`/`.props`/`.env`, confirmed with a
  standalone probe (the identical class, declared directly in a `.ts`
  file instead, infers correctly). Surfaces as `DialogService.add`
  rejecting the vendor class against *any* `Component<P>` instantiation,
  `P = any` included, with the confusing message "is missing the
  following properties from type 'Component<...>': props, env, __owl__,
  render". Not fixable by widening `P` -- the vendor class itself is
  what fails the structural check. Fix: a narrow, hand-typed re-export
  of the vendor class, cast once (`ConfirmationDialogImpl as unknown as
  new (...args: any[]) => Component<ConfirmationDialogProps>`), the same
  "narrow, hand-traced facade over a vendor boundary" move `odoo.ts`
  already makes for `OrmService`/`NotificationService`/`ActionService` --
  every real caller then imports the typed re-export from `odoo.ts`
  instead of the vendor module directly.
- `Domain.toList(context)` (`@web/core/domain.js`) is JSDoc'd with
  `context` unbracketed (`@param {Object} context`, meaning required),
  and TS enforces that -- but plenty of real vendor callers
  (`field.js`, `utils.js`, several in `search_model.js`) call it with
  zero arguments anyway. The same JSDoc-vs-runtime looseness already
  tracked for `Registry.get`/`queryFirst`/`useDragAndDrop`/`moveTo`, now
  on a required-vs-effectively-optional parameter rather than an arity
  or shape mismatch. Fix at the call site: pass `{}` explicitly, the
  same "evaluate without context" idiom `domain.js`'s own `toJson()`
  uses internally.
- `querySelector`/`querySelectorAll` infer their default, non-generic
  return type as the DOM lib's own `Element`, which has no `.click()` --
  a real gap only surfaces once a real caller needs a DOM method
  `Element` does not have (`identity.ts`'s `tabFor`/`findTab`, both
  genuinely always finding a `<a class="nav-link">`, widened to
  `HTMLElement` with an explicit `querySelector<HTMLElement>(...)` once
  `canvas.ts` needed `.click()` on what they return). A test written
  against the old, wider return type may need a matching `as
  HTMLElement` at its own comparison site (`identity.test.ts`), since
  `@odoo/hoot-dom`'s own `queryOne` stays the plain, non-generic
  `Element` it has always been (see cluster-3's own `drag.test.ts`
  finding on this).
- `ReturnType<typeof _t>` used to be `any` (the vendor `error` type, see
  above), which is why unioning it with anything tripped
  `no-redundant-type-constituents`. `_t` is imported from
  `console/l10n.ts` now and returns `Translated` (`string | String`), so
  `ReturnType<typeof _t>` is that union too.
- `usePopover`'s own `open(target, props)` (`@web/core/popover/
  popover_hook.js`) forwards `props` to the popover service unchanged --
  neither it nor `Popover` itself injects a `close` into the *rendered*
  component's own props (`Popover`'s own `close` prop is for its
  click-away/escape chrome, not forwarded into `componentProps`), unlike
  `DialogService.add`, which does inject one. A component meant to be
  opened through `usePopover` that unconditionally calls
  `this.props.close()` (`field_editor_fallback.ts`'s own `onKeydown`, on
  Escape) is relying on something no real opener in this tree actually
  supplies -- a real, pre-existing gap, not introduced by this migration
  and not fixed by it (flag, don't fix). The type-level fix at each real
  opener: `Omit<FieldEditorProps, "close">` for the props object, not the
  full shape.
- `field(default_factory=list)`/`field(default_factory=dict)` (dataclasses)
  infer `list[Unknown]`/`dict[Unknown, Unknown]` even when the field's own
  annotation says `list[SomeClass]`/`dict[K, V]` -- pyright does not
  propagate the field's declared type into the zero-arg factory's own
  return type. Fix: `field(default_factory=list[SomeClass])` /
  `field(default_factory=dict[K, V])` -- the parametrized generic itself a
  real, callable, zero-arg factory at runtime (Python 3.9+), behaviorally
  identical to the bare form (confirmed both by pyright, 0 errors, and by
  actually running it: `Term().occurrences == []`). Hit twice independently
  in the same wave (`pogen.py`'s `Term.occurrences`, `canvas_stamp.py`'s
  `StampResult.nodes`/`.elements`), so treated as a general trap rather
  than a one-off.
- lxml ships no type stubs in this environment (a compiled extension with
  no `.pyi`/`py.typed` marker; `lxml-stubs`/`types-lxml` is not an
  installed dependency here) -- `from lxml import etree` alone reports
  both `reportMissingTypeStubs` and `reportAttributeAccessIssue`. The
  obvious rewrite, `import lxml.etree as etree`, trades this for a worse
  problem: ruff's own `PLR0402` (`fix = true` project-wide) silently
  auto-fixes it straight back to the broken `from lxml import etree` form
  on every save. Fix: keep `from lxml import (etree,)`, with
  `# pyright: ignore[reportMissingTypeStubs]` on the `from lxml import (`
  line and `# pyright: ignore[reportAttributeAccessIssue,
  reportUnknownVariableType]` on the `etree,` line -- both required, both
  on those exact physical lines (confirmed a `# pyright: ignore` on a
  *preceding* comment line does not suppress the diagnostic below it).
  For the element type itself, `app_builder_base/tools/lxml_types.py`'s
  `LxmlElement` is the one shared, hand-traced `Protocol` every real
  `tools/` reader imports rather than re-declaring -- three independent
  local copies existed briefly before being reconciled into it (see
  "Implemented so far").
- `BaseModel.sorted(self, key=None, reverse=False)` (`odoo/models.py`)
  carries no type annotation at all on `key` in the merged tree, so a
  lambda passed as `some_recordset.sorted(key=lambda r: ...)` has no
  context to infer its own parameter's type from and reports fully
  `Unknown` throughout (the lambda's parameter, its return, and every
  attribute read inside its body). Fix: a small, separately-defined,
  explicitly-annotated function in place of the inline lambda -- the
  function's own signature needs no inference, so the same
  `reveal_type`-confirmed field reads it already relied on stay exactly
  as typed (`pycodegen.py`'s `_selection_sort_key`, replacing
  `record.selection_ids.sorted(key=lambda s: (s.sequence, s.value))`).
  `.sorted` itself still needs a narrow
  `# pyright: ignore[reportUnknownMemberType]` at the call site when the
  recordset it's called on is itself only reachable via a `cast` (see
  the next trap) -- a separate diagnostic, about the method reference's
  own partially-unknown signature, not about the `key` argument.
- Five attributes of `ir.model.fields` (`IrModelFields`, in the merged
  tree's `odoo/addons/base/models/ir_model.py`) -- `.ttype`,
  `.relation`, `.relation_table`, `.column1`, `.column2` -- read back as
  `str | bool` under pyright (`.column1`/`.column2` additionally carry a
  genuine `Unknown` component: `str | Unknown | bool`) instead of the
  `str | Literal[False]` every other `Char`/`Selection` field on that
  same real class gets (confirmed clean on ten siblings: `.name`,
  `.field_description`, `.help`, `.related`, `.domain`, `.on_delete`,
  `.currency_field`, `.compute`, `.depends`, `.relation_field`).
  Confirmed by direct `reveal_type` probe, and confirmed it is not about
  the field *name*: a synthetic `models.Model` declared inline with
  identically-named `Char` fields (`relation`, `column1`, `ttype`) infers
  the expected `str | Literal[False]` every time. Traced as far as
  `Many2many.relation`/`.column1`/`.column2` (`odoo/fields.py`) being
  unrelated class attributes of the *field descriptor* class itself
  (e.g. `relation = None  # name of table`) that happen to share these
  exact names with real `IrModelFields` columns -- the only coincidental
  overlap found, not a conclusively confirmed root cause, so worth
  re-checking if it resurfaces elsewhere rather than assumed solved.
  Fix, since a real row only ever holds a `str` (or the empty-string/
  `False` "unset" spelling any `Char` field can have) at these five
  attributes, never a real `bool`: `cast("str", record.<attr>)` at each
  read, with a `# pyright: ignore[reportUnknownMemberType]` alongside
  the two (`column1`/`column2`) whose source expression also carries the
  genuine `Unknown` component the cast alone doesn't silence
  (`pycodegen.py`'s `_field_spec_from_record`). The same file's own
  `record.selection_ids` (a `fields.One2many("ir.model.fields
  .selection", "field_id", ...)`, a plain string comodel with none of
  OCB's typed-relation syntax) hits the same shape of gap one level up
  -- pyright cannot resolve the element type from the declaration at
  all and falls back to `M@_Relational | list[Unknown] | list[Unknown |
  bool]`, with `.sorted` unresolved on two of the three arms -- fixed
  the same way, `cast("IrModelSelection", record.selection_ids)` plus
  the matching ignore.
- `Environment._` (`odoo/api.py`) -- the translation callable every real
  caller knows as `env._(...)`/`self.env._(...)` -- has its `source`
  parameter annotated (`str | LazyGettext`) but its `*args`/`**kwargs`
  are not, in the merged tree; confirmed directly with `reveal_type`.
  Every real call site (`env._("...", key=value)`,
  `env._("...", positional)`) therefore reads as `reportUnknownMemberType`
  under this project's strict `tools/` execution environment. Fix:
  `# pyright: ignore[reportUnknownMemberType]` at each call site (21 in
  `manualfield.py`, the first file in this migration to call `env._`
  directly rather than only pass it as a value). This will very likely
  recur in most Phase 1c model files, which call `self.env._(...)`
  constantly -- worth deciding then whether the house convention stays
  "ignore at every call site" or a single typed wrapper (e.g. `def
  translate(env: api.Environment, source: str, *args: object, **kwargs:
  object) -> str: return env._(source, *args, **kwargs)`) is worth
  introducing to avoid dozens of near-duplicate ignores per file.
  **Confirmed, first Phase 1c file (`studio_security.py`): the plain
  module-level `_` (`from odoo import _`, i.e. `odoo.tools.translate
  .get_text_alias`) has the identical gap** -- `reveal_type` shows `(source:
  str, ...) -> str`, the same unannotated-`*args`/`**kwargs` shape, under a
  file-scoped strict-equivalent `executionEnvironment` probe. Given how
  pervasive plain `_("...")` calls are (every translatable string in every
  model file), fixing this per call site was deliberately deferred rather
  than solved on file 1 -- see the new "two-stage ratchet" note below;
  revisit once several more model files confirm the same scale of
  recurrence, the same "promote only once a real, cross-file pattern is
  confirmed" discipline `lxml_types.py` was built under.
- A method decorated with `@tools.ormcache(...)` (e.g. `IrModel._get_id`)
  reads as `() -> ((...) -> Any)` under pyright, not its real signature --
  confirmed with `reveal_type` and traced to the installed `decorator`
  package's own stub (`decorator/__init__.pyi`), which types
  `decorator(caller, _func=None, kwsyntax=False)`'s return as
  unconditionally `Callable[[Callable[..., Any]], Callable[..., Any]]`
  even when `_func` is supplied the way `ormcache.__call__` actually
  calls it (`decorator(self.lookup, method)`, `odoo/tools/cache.py`) --
  a real stub-vs-runtime gap in a third-party stub, not this codebase's
  to fix. Fix: a narrow `# pyright: ignore[reportCallIssue]` at each call
  site of an `@ormcache(...)`-decorated method called directly (rather
  than through a plain, undecorated wrapper) -- `manualfield.py`'s
  `IrModel._get_id(relation)`. Likely to recur anywhere else in this
  codebase that calls an `@ormcache`/`@tools.ormcache`-decorated ORM
  method directly.
- A `dict[str, Callable[..., T]]` registry built from inline lambda
  values reports `reportUnknownLambdaType` on every lambda parameter
  under strict mode, regardless of the dict's own declared value type --
  a lambda's parameter cannot carry an annotation at all (a Python syntax
  limit), and pyright does not infer one from the surrounding dict
  literal's declared type either. The same underlying gap as `.sorted(key
  =lambda ...)` above, just a second manifestation of it (a dict literal
  rather than a single keyword argument). Fix, identical in shape: small,
  separately-defined, explicitly-annotated named functions in place of
  the inline lambdas (`scaffold.py`'s `SCAFFOLD_BUILDERS`, nine
  `_build_*` functions replacing nine lambdas).
- `Environment.user` (`odoo/api.py`) carries no return annotation of its
  own; pyright infers one from its body (`self(su=True)['res.users']
  .browse(self.uid)`), which bottoms out at the bare `BaseModel` every
  `Environment.__getitem__` call returns -- the same untyped hole
  `typed.model()` exists for, but `self.env.user` is an *already-obtained
  record*, not a model *name* to turn into a handle, so `typed.model()`
  doesn't apply here (it would return an empty `res.users` recordset, not
  the current user's own record). Fix: a direct, narrow `cast("Users",
  self.env.user)` at the point of use, `Users` imported `TYPE_CHECKING`-only
  from `odoo.addons.base.models.res_users` (`studio_security.py`'s
  `_assert_studio_group`). Cast inline inside a boolean expression rather
  than into a variable above it, when the original code short-circuited
  around the property read -- `self.env.user` is cheap and side-effect-free
  (`browse` never queries), but preserving the exact original evaluation
  order costs nothing and removes any doubt about a behavior change. Likely
  to recur anywhere else `self.env.user`'s own methods/fields (not just
  `.id`/`.login`, which `BaseModel` doesn't have either) are read directly.
- **Two-stage ratchet for `models/`, discovered on the first Phase 1c
  file.** The plan's own text says "`# pyright: strict` at the top the
  moment a file passes; `reportUnknownMemberType`-class rules on last" --
  tested literally on `studio_security.py` via a temporary file-scoped
  `executionEnvironment` probe (same individual-rule mechanism `tools/`
  uses, not a bare `# pyright: strict` comment, per the composition trap
  already documented in "Where it starts from"/1a). Result: escalating a
  file to the full strict-equivalent rule bundle immediately surfaces
  `odoo._`'s own unannotated-varargs gap (see above) -- confirming the
  plan's own instinct that `reportUnknownMemberType`-class rules need to
  come *after* something, not immediately per-file. Rather than solve
  that infrastructure question (a shared translation wrapper, or blanket
  per-call-site ignores) off a single file's evidence, **Phase 1c's own
  stage 1 is: full annotations (signatures, `Self`, typed relational
  fields, `typed.model()`/direct casts for the ORM's own untyped holes)
  verified clean under this project's existing top-level `standard` mode
  plus the `ANN`/`TC`/etc. ruff rules -- no per-file strict escalation
  yet.** Stage 2 (flipping on the strict-equivalent bundle, file by file
  or in bigger groups) is deferred until enough files have gone through
  stage 1 to see the real, cross-file shape of "every `Any` OCB leaks"
  (translation calls being the first confirmed one) rather than guessing
  at shared infrastructure from one data point -- the same "promote only
  once a real pattern is confirmed across readers" discipline
  `lxml_types.py` was built under. **Confirmed on the second Phase 1c
  file (`studio_serializer.py`): under `models/`'s current top-level
  standard-mode config, `record._fields[fname]`-class reads already
  resolve with *zero* pyright errors even with no cast/ignore at all**
  (`reportUnknownVariableType`/`reportUnknownMemberType` are strict-only
  rules, off by default in standard mode) -- the narrow
  `# pyright: ignore[...]` idiom `compat.py`/`manualfield.py` established
  is therefore not load-bearing in `models/` *yet*, unlike in `tools/`
  where its own `executionEnvironment` already enables those rules. Kept
  anyway, everywhere this pattern recurs, so the idiom is already in
  place, byte-identical to `tools/`'s own, the day stage 2 turns those
  rules on -- confirmed the ignore comment itself causes no
  `reportUnnecessaryTypeIgnoreComment` complaint or other diagnostic
  when the named rule isn't actually firing, so carrying it early is
  free.
- `Environment.get(...)` (inherited, unparameterized `Mapping.get` --
  `Environment` itself never overrides `get`, only `__getitem__`/
  `__contains__`) returns `Unknown | None`, confirmed with `reveal_type`
  -- a *different* untyped hole from `Environment.__getitem__`'s own
  (which `typed.py`'s `model()` helper exists for): `.get()`'s real
  contract is `BaseModel | None` (`None` on a model-name miss, instead
  of `__getitem__`'s KeyError-on-miss shape). Handled narrowly, by
  annotating the *call site's* own return type rather than a new shared
  helper (`studio_serializer.py`'s `_for_model`, its only caller so far)
  -- the same "promote only once a pattern recurs" discipline as above;
  revisit once a second `models/` file calls `env.get(...)` the same way.
- `Field.default`'s pyright-inferred type, for any field carrying a
  callable default, is the alarming-looking `((model: Unknown) -> Never)
  | None` rather than the honest `Callable[[BaseModel], object] | None`
  -- confirmed with `reveal_type` against the real merged tree, traced to
  a self-referential-narrowing artifact inside OCB's own `Field.__init__`
  (`odoo/fields.py`; `self.default` is narrowed against itself earlier in
  the same method, before the `lambda model: value` branch that actually
  sets it). Not a bug in this codebase, not fixable from this side, and
  confirmed zero practical effect: `Never` is a bottom type, so code that
  calls the callable and uses its result (`studio_serializer.py`'s own
  `_should_skip`) round-trips clean regardless, with no cast needed.
  Recorded so a future reader does not re-derive this from a
  frightening-looking `reveal_type` result.
- A module-level `TypeAlias` built directly from another module's
  exported type (e.g. `Element: TypeAlias = LxmlElement`, re-exporting
  `lxml_types.py`'s own `LxmlElement` under a locally-conventional name)
  needs its source import at real, top-level scope -- `TYPE_CHECKING`-
  guarding it trips ruff's `TC004` ("move import out of type-checking
  block: used for more than typing"), since the assignment itself runs
  at import time, not only inside deferred annotations the way a bare
  type-only usage would. Only the *alias assignment itself* needs the
  real import; every place the alias is then *used* (a parameter/return
  annotation) is still deferred as normal by `from __future__ import
  annotations`, exactly like any other name.

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

- **TypeScript (2b, cluster 4, wave 1: cog_menu_item, systray_item,
  pending_widget, apply_dialog, canvas, flows/{create_package_flow,flow},
  record_pane/row_editor, sidebar/{field_editor_fallback,remove_flow},
  canvases/search_lists_canvas).** The first real Owl components
  converted in this migration -- eleven files, drafted in parallel (a
  Workflow, ultracode being on for the session) against a hand-built
  leaf-first dependency graph, then reconciled and verified centrally
  against the real `tsc`/`eslint`/`prettier`/`build_ts`/transpile-guard
  toolchain the same way every earlier cluster was. The four new,
  general Owl-component facts this wave established (the `override`
  rule's correction, `setup()`-field initialization,
  `typeof Component<any, any>`, `ev.target instanceof Element`) are in
  "Known traps" above rather than repeated here, since every later
  cluster's own components will hit all four.

  **Shared-type growth**, every one landing in `console/odoo.ts`/`types.ts`
  because a real file in this wave needed it, none invented ahead of a
  reader:

  - `odoo.ts`'s `ActionController` -- Phase 2c's own cut covered only
    `cog_menu_item`'s reads (`.action.res_model`, `.currentState.resId`);
    `systray_item.ts` needed real `currentController` fields Phase 2c's
    note had simply not traced against that file (`.virtual`,
    `.props.resModel`/`.type`/`.resId`, `.action.type`/`.views`/`.id`),
    confirmed against `action_service.js`'s own `_makeController`/
    `_getViewInfo`/`_controllersFromState` directly. A type-accuracy gap
    in already-landed shared code, not a runtime bug -- nothing shipped
    broken, but the narrower type would have rejected this file's real,
    correct reads the moment it converted.
  - `odoo.ts` gained three new registry categories this wave's files
    are the first real registrants of: `cogMenu` (core's own category;
    `CogMenuItem`, with the same "vendor `.d.ts` says sync `boolean`,
    every real registration is actually `async`" JSDoc-vs-runtime gap
    already catalogued for `Registry.get`/`queryFirst`), `systray`
    (core's own; `SystrayRegistryItemShape`), and `view_widgets` (core's
    own; `ViewWidgetsRegistryItemShape`/`StaticWidgetInfo`/
    `DynamicWidgetInfo`, transcribed from the real vendor
    `view_widgets_registry.d.ts` -- not in `tsconfig.json`'s `include`,
    unlike its `fields_registry.d.ts`/`views_registry.d.ts` siblings --
    with one correction to that file's own imprecise `extractProps`
    parameter naming, confirmed against `widget.js`'s real call). Plus
    one category this addon owns: `"app_builder.field_editor"`
    (`typeof Component<any, any>`, `field_editor_fallback.ts`'s
    fallback and `app_builder_model`'s own full popover both register
    into it -- whichever registers first wins). Each of the three core
    categories was hit by a *different* file in this wave independently
    proposing the identical augmentation locally (the same "carry it in
    the one file that needs it until the facade exists" precedent
    `pane_registry.ts` set in cluster 3) -- reconciled centrally into
    `odoo.ts` rather than kept as three separate, duplicate `declare
    module` blocks.
  - `odoo.ts` gained a typed re-export of `ConfirmationDialog`
    (`@web/core/confirmation_dialog/confirmation_dialog.js`) plus
    `ConfirmationDialogProps`, for the reason in "Known traps" above
    (the vendor class's own inferred type does not carry `Component`'s
    members under `checkJs: false`) -- the first vendor *component*, not
    just vendor *service*, this migration has needed to re-export typed.
    Both real callers (`apply_dialog.ts`'s `onDiscard`, `sidebar/
    remove_flow.ts`) now import it from `odoo.ts` instead of the vendor
    module directly.
  - `types.ts` gained a `FlowSpec`/`FlowStep`/`FlowValues` family
    (`PaneRegistration.flow` was left `unknown` specifically pending
    this conversion, its own comment said so) and a
    `FieldEditorInitial`/`FieldEditorProps` family (the whole-tree
    contract `field_editor_fallback.ts`'s own module docstring names in
    full -- `app_builder_model`'s still-`.js` full popover builds the
    identical shape, confirmed by reading `field_popover.js` directly,
    so this lives in `types.ts` rather than the fallback component's
    own module for the same cross-addon-importability reason
    `PaneRegistration`/`PaneContext` already do). Both families were
    proposed by the file that needed them and consumed as anticipated by
    a sibling file in the same wave (`flow.ts` importing `FlowSpec`/
    `FlowStep`/`FlowValues`, `field_editor_fallback.ts` importing
    `FieldEditorProps`) -- real, same-wave cross-consumption, not typing
    ahead of a reader.
  - `console_model.ts`'s `activePage`/`rememberPage(page)` were widened
    from `unknown` to `TabMemory | null` (`identity.ts`) -- `canvas.ts`'s
    own `onPatched` is the first real reader, and both of `activePage`'s
    only writers (`rememberPage`, and the `null` it starts as) already
    proved the shape unambiguously; narrowed centrally, dropping the
    per-file cast the drafting agent used instead (a difference from
    `CanvasPayload.models`, below, where the same "first real reader"
    situation was judged too speculative a shape to promote yet).
  - `identity.ts`'s `tabFor`/`findTab` were widened from `Element | null`
    to `HTMLElement | null` (see "Known traps" above) once `canvas.ts`
    needed `.click()` on what they return; `identity.test.ts`'s own
    `tabFor(...)).toBe(link)` assertion needed a matching `link as
    HTMLElement` cast at the one call site this touched, `link` itself
    still being `@odoo/hoot-dom`'s plain, non-generic `queryOne` result.
  - `shell/pane_registry.ts`'s `PaneResolverResult.Component`/`.sidebar`
    got the `typeof Component<any, any>` fix (see "Known traps") --
    `flow.ts`'s own `setPaneResolver("flow", ...)` return value is the
    first real assignment of a concrete component class into either
    field.
  - `drag.ts`'s local `const ICONS = TYPE_ICONS as Record<string,
    string>;` cast was dropped once `pending_widget.ts` (this wave)
    started exporting `TYPE_ICONS` with a real `Record<string, string>`
    annotation at the source -- the cast existed only because the
    export was untyped JS before.

  **Not promoted, deliberately, despite a real first reader**:
  `CanvasPayload.models` stays `unknown` in `types.ts`; `canvas.ts`'s
  `computeViewProps` is its first real reader (traced to
  `studio_view_canvas.py:canvas`'s own per-model `{fields: fields_get(...)}`
  dict), but the shape is typed locally in `canvas.ts` itself
  (`CanvasModelEntry`, cast at the one read site) rather than promoted
  to shared vocabulary -- unlike `activePage` above, a dict keyed by
  arbitrary model names with exactly one real reader is exactly the kind
  of shape this migration has repeatedly preferred to let a *second*,
  independent caller confirm before naming centrally, rather than widen
  a shared cross-addon type from a single file's own usage.

  **Real, behavior-relevant findings, none of them latent bugs worth
  fixing**: `field_editor_fallback.ts`'s `get inverse()` fallback object
  was missing `suggested` from `InverseOptions`, a real (if unreached in
  practice -- the branch that would read it is gated behind
  `can_create`, which the same fallback also sets `false`) shape
  mismatch against the real contract, fixed to match `console_model.ts`'s
  own canonical empty `InverseOptions`. `record_pane/row_editor.ts`'s
  `fieldSelectorProps` read `this.row.follow !== false`, but `row.follow`
  was never a real field of `Row`/`RowJSON` (`catalogue.py` has no such
  member) -- the same class of finding as cluster 1's `row.placeholder`:
  always `undefined`, so the check has always unconditionally resolved
  to `true` (which also happens to be `ModelFieldSelector`'s own
  `defaultProps.followRelations`). Typed to what it actually, always
  evaluates to, with a comment, rather than widening `RowJSON` for a
  field with no real Python source. Left untouched, out of this
  migration's own scope: `search_lists_canvas.xml`'s "Group by" row's
  remove button calls `removeSearchElement('filter', entry.name)` for an
  entry drawn from `search.group_bys` -- looks like a genuine
  pre-existing bug (removing a group-by asks the server to remove a
  same-named *filter* instead), found while tracing this file's own
  types, but it lives in the `.xml` template, not the file converted, so
  it is flagged here rather than silently fixed.

  Verification for all eleven files: `tsc`/`eslint`/`prettier` clean
  (eslint findings triaged against the same "cross-check against
  `tsc`/pre-existing-baseline first" policy "Known traps" already
  documents -- the only real, fixable findings were `no-floating-promises`/
  `no-misused-promises` on a fire-and-forget `doAction`/`discard`/`remove`
  call, fixed with the same `void` operator already established in
  `console_model.ts`/`drag.ts`; `no-unused-expressions` on four `a &&
  a.method()` guards in `canvas.ts`'s `detach()`, fixed with optional
  chaining; `no-empty-object-type`/`no-base-to-string`/
  `no-unnecessary-type-assertion`/`unbound-method`/`require-await`, one
  each, fixed locally). `build_ts.mjs` re-run to confirm idempotency.
  Every file's emitted `.js` checked against transpiling its
  pre-conversion original: five of the eleven show a *dependency-list*
  difference from before conversion (never a name difference) --
  `apply_dialog`/`cog_menu_item`/`create_package_flow`/`remove_flow`/
  `systray_item` all lose a direct vendor import (`@web/core/utils/hooks`
  for `useService`, `@web/core/confirmation_dialog/confirmation_dialog`
  for `ConfirmationDialog`) and gain `@app_builder_view/console/odoo` in
  its place -- the deliberate Phase 2c "route framework-boundary imports
  through one facade" policy working as intended, not a regression. The
  full tree-wide transpiler guard (`test_assets.py`'s own check, run
  directly rather than through Odoo's test runner) passed clean across
  all 74 shipped `.js` files.

- **TypeScript (2b, cluster 4, wave 2: sidebar/{add_tab,outline,
  properties_tab,view_tab}, record_pane/record_pane, top_bar,
  panes/changes_pane).** Seven more real Owl components, drafted in
  parallel the same way as wave 1. Two of the seven agent runs hit real
  tooling trouble this time -- `sidebar/outline.ts`'s own drafting agent
  exceeded the structured-output retry cap entirely (5 failed schema
  validations, no journal result at all), and `sidebar/add_tab.ts`'s
  returned a bare placeholder (`"test"`) in the schema fields instead of
  its real work. Both agents had, in fact, done the real conversion and
  written it to the shared workflow scratchpad (its designated place for
  intermediate files, not the project tree) before failing only the
  final structured-output call -- recovered from there instead of
  re-running either agent, after checking each file's head and tail
  looked like complete, well-formed TypeScript. A third agent
  (`record_pane.ts`) filled its `content` field with a prose description
  of what it did (*"the full file content is below... its content, in
  full, is: ..."*) rather than the file itself; also recovered from the
  same scratchpad. Two more (`top_bar.ts`, `view_tab.ts`) prefixed real
  code with a similar narrative sentence, harmlessly, since the real
  `.ts` content still followed on the same string and both compiled
  as-is. Lesson for future waves: always check the shared scratchpad for
  a same-named `.ts` file before deciding an agent's result needs a
  re-run -- the structured-output call failing does not mean the
  underlying work was lost.

  One real, load-bearing gap found in reconciliation, not by any one
  agent alone: `sidebar/add_tab.ts`'s own `openEditor` built a
  `const props: FieldEditorProps = {...}` missing `close` -- a real
  `tsc` error, not a false positive. `sidebar/properties_tab.ts`'s own
  independently-drafted agent had already hit and solved the identical
  problem (`Omit<FieldEditorProps, "close">`, with the fuller writeup now
  in "Known traps" above on why `close` is never really supplied), so
  the same fix was applied to `add_tab.ts` rather than re-derived.

  **Shared-type growth**, all landing because a real file in this wave
  needed it, several because *multiple* files in the same wave
  independently confirmed the identical shape:

  - `wire.ts`'s `EditingContext.catalogue`/`.options`/`.groups` were
    widened from `unknown` to `CatalogueJSON`/`OptionGroupJSON[]`/a new
    `SelectableGroupEntry[]` -- `sidebar/view_tab.ts` and `sidebar/
    properties_tab.ts` each independently asserted the identical
    `catalogue`/`options` cast (traced to `studio_view_editor.py:
    editing_context`'s own `"catalogue": catalogue.catalogue_json(...)`,
    `"options": view_options.groups_json(...)`), and
    `properties_tab.ts` alone needed `groups` (traced to
    `_selectable_groups`, the same file). Two independent real readers
    confirming the same shape in one wave is stronger grounds than the
    single-reader cases below, so this one widened the shared type
    directly rather than staying local.
  - `wire.ts`'s `RecordChildrenJSON.kinds` widened from `string[]` to
    `[string, string][]` (`Step._states()`,
    `app_builder_ui/models/studio_automation_surface.py`, returns
    `[value, label]` pairs, not bare strings) and `RecordRowJSON` gained
    an optional `depth` (only the menu surface's own `rows()` override
    sends it) -- both traced and confirmed against the real Python
    sources before widening, `record_pane.ts` being the first real
    reader of either.
  - `record_pane_model.ts`'s `RecordPaneEntry` (cluster 2) gained
    `label`/`empty`/`rowActions` (plus a new, exported `RowActionSpec`)
    -- previously left under its own index signature, per `types.ts`'s
    own `PaneRegistration` comment naming exactly these three as
    "unmodeled until one of those is converted", which `record_pane.ts`
    now is. `RecordPaneModel.addChild`'s return type was deliberately
    **not** narrowed past `Promise<unknown>` despite tracing its one
    known real implementation (`add_step`, returning a
    `RecordDescription`) -- `children.add` names a different method per
    surface, and not every surface's implementation was checked, so
    narrowing tree-wide would risk being wrong for a surface not yet
    read; `record_pane.ts` casts locally at its own one call site
    instead.
  - `odoo.ts` was *not* touched for `FormViewDialog`
    (`@web/views/view_dialogs/form_view_dialog.js`, the same
    no-`@extends`-JSDoc vendor-boundary problem `ConfirmationDialog`
    already has a fix for there) -- `record_pane.ts` is the only real
    renderer of it so far, so the identical cast/re-export pattern is
    carried locally in that file, deliberately deferred the same way
    cluster 3 deferred `app_builder.panes`'s own registry augmentation
    until `odoo.ts` existed to hold it. Promote the day a second file
    needs it.

  Verification: `tsc`/`eslint`/`prettier` clean (the same triage policy
  as wave 1 -- `no-unsafe-*` and the newly-added `no-redundant-type-
  constituents`/`ReturnType<typeof _t>` case accepted as noise, four
  real, fixable findings applied: two `no-misused-promises` async-
  `confirm`-callback sites in `properties_tab.ts` pulled into a small
  `finishRemoveOwned` helper called with `void`, two `onSave: async
  (values) => {...}` sites in the same file rewritten to plain functions
  with an internal `void`, one `no-floating-promises` `.then()` chain
  `void`-prefixed, one `no-unnecessary-type-assertion` matching the
  identical `field_editor_fallback.ts` pattern). `build_ts.mjs` re-run
  to confirm idempotency. Transpile-equivalence: all seven show the same
  *dependency-list-only* difference wave 1's five did (losing
  `@web/core/utils/hooks`/`@web/core/confirmation_dialog/
  confirmation_dialog`, gaining `@app_builder_view/console/odoo`) --
  module identity unchanged in every case, the deliberate Phase 2c
  routing working as intended. Full tree-wide transpiler guard passed
  clean across all 74 shipped `.js` files.

- **TypeScript (2b, cluster 4's own tests: `outline.test.ts`,
  `record_sidebar.test.ts`, `systray_item.test.ts`).** Converted right
  after cluster 4's two waves, the same "cluster's own tests as a
  distinct follow-up step" rhythm clusters 2/3 already used --
  `systray_item.test.ts` was in fact unblocked as soon as wave 1 landed
  (it only exercises `systray_item.ts`), but bundled with the other two
  for one pass rather than split further. All three drafted in parallel
  with no tooling trouble this time (contrast wave 2's two recovered
  agents) and reconciled with **zero** real `tsc`/production-code fixes
  needed -- every type each test needed already existed, confirming
  `odoo.ts`'s `ActionController`/`ActionService` (wave 1) and
  `record_pane_model.ts`'s widened `RecordPaneEntry` (wave 2) are
  complete for what their own tests exercise, not just for production.

  A real design-consistency gap flagged, not fixed (out of each test's
  own scope): `record_pane.ts`'s `RecordSidebar`/`RecordPane` both type
  `Props.model`/`Props.shell` to the full `RecordPaneModel`/`StudioShell`
  classes rather than a narrow owner interface the way `ConsoleModel`
  (`ConsoleModelOwner`, cluster 2) and `CanvasDrag` (`CanvasDragModel`,
  cluster 3) were each narrowed specifically so their own tests could
  build a minimal fake. `record_sidebar.test.ts` worked around it the
  same way `record_pane.ts` itself already works around an analogous
  mismatch (`entry as unknown as RecordPaneEntry`): a local `FakeModel`
  interface (grepped from `record_pane.ts`'s own `this.model.` reads),
  cast `as unknown as RecordPaneModel`/`as unknown as StudioShell` at
  the `mountWithCleanup` boundary. Worth a `RecordPaneModelOwner`-style
  interface the day a second caller (a `RecordPane` test, say) needs the
  same narrowing -- not done now, since `record_pane.ts` itself is
  already-converted, real code outside a test file's own scope to edit.

  Two small, genuine, behavior-neutral completeness gaps in the original
  JS fixtures, found only because the type is now enforced (neither is a
  bug in the component under test, both in test-fixture data the
  component never actually reads): `record_sidebar.test.ts`'s fixture
  record never set `sentence` (required on `RecordDescription`, but
  `RecordSidebar` reads a *different* field of the same name on
  `RecordRowJSON` instead) or `advanced.context.studio_package_id`
  (never read since no test clicks "Advanced…") -- both given inert
  defaults rather than left to a bare `as`.

  Verification: `tsc` clean with no fixes; `eslint` findings all in the
  two already-accepted noise categories (`no-unsafe-*`, and
  `require-await` on a fake's own async method that satisfies an async
  interface without needing to await anything -- the identical, already
  pre-existing pattern `console_model.test.ts`'s own eleven
  `require-await` findings are, not new noise); one real,
  worth-documenting `no-base-to-string` in `record_sidebar.test.ts`'s
  own `visible()` fake fixed with a targeted disable comment, matching
  the same finding already accepted in the real
  `RecordPaneModel.visible` this fixture stands in for.
  Transpile-equivalence: all three are an exact `OK` match against their
  pre-conversion originals, name *and* dependency list -- tests call
  vendor hooks directly rather than through `odoo.ts` (that routing
  policy is for production console files only), so there was no
  dependency-list shift to expect here the way wave 1/2's production
  files had. Full tree-wide transpiler guard passed clean.

- **TypeScript (2b, cluster 4, wave 3: panes/home_pane, panes/views_pane,
  shell/shell).** The last three components before cluster 4's own final
  file (`console.js`, wave 4). All three drafted in parallel with no
  tooling trouble; `home_pane.ts`'s own drafting agent went a step
  further than any prior wave and built a throwaway scratch overlay of
  the whole repo under `/tmp` (real `node_modules`/`odoo` symlinked back
  in) to run `npm run typecheck`/`build_ts`/`eslint`/`prettier` against
  its own draft directly, rather than only reasoning about whether it
  would compile -- confirmed clean before ever returning it.

  Three real, load-bearing gaps found only in central reconciliation
  (`shell.ts` itself, once applied, did not compile clean on the first
  pass -- the other two files did):

  - `static override props = { "*": true }` (`shell.ts`'s own
    `StudioConsole`, "accept any prop" for an action-framework host
    component) failed against `Schema`: TS widens the object literal's
    `true` to `boolean` by default, and `boolean` is not assignable to
    `BaseType` (`true | "*" | {new (...): any}`, `validation.d.ts`) --
    only the *literal* `true` is. Fixed with `as const` on the object
    literal, which changes nothing about the emitted `.js` (an object
    literal compiles identically either way) -- purely a type-level
    fix, the first time this migration has hit "the value's own literal
    type, not its declared type, is what a vendor schema actually
    needs."
  - `odoo.ts`'s `ActionService` was missing `restore()` entirely, and
    `doAction`'s own first parameter was typed `ActionDescription` only
    -- `shell.ts` is the first real caller anywhere in this tree to call
    `doAction` with a plain action id (`number`) or call `restore()` at
    all. Traced directly against `action_service.js`'s own real
    `ActionRequest` typedef (`ActionId | ActionXMLId | ActionTag |
    ActionDescription`) and `restore(jsId)`'s real implementation
    (`jsId` genuinely optional, falling back to "the previous
    controller"): widened `doAction`'s parameter to `ActionDescription
    | number` (the `string` variants stay unadded until a real caller
    needs one) and added `restore(jsId?: string): Promise<unknown>`.
    `systray_item.test.ts`'s own `ActionService` stub needed a matching
    no-op `restore()` added to stay structurally complete.
  - `shell/shell_model.ts`'s `StudioShell.env` (cluster 2) was typed
    `{services: {orm, notification}}` -- narrower than the real Owl
    `env` every caller actually constructs `StudioShell` with
    (`shell.ts`'s own `new StudioShell(this.env, ...)`, which does
    carry `services.field` and `bus`), because `StudioShell` itself
    never previously read either. `panes/views_pane.ts` is the first
    real file to construct a *different* class (`ConsoleModel`) from
    `StudioShell.env`, and `ConsoleModel`'s own constructor needs both.
    Widened `StudioShell.env`/its constructor parameter to a new,
    exported `ShellEnv` (services `orm`/`notification`/`field` plus
    `bus`) -- the same shape `console_model.ts`'s own private
    `ConsoleEnv` already names for the identical real object -- which
    let `shell.ts`'s own local `ConsoleEnv` interface (a different,
    unrelated type of the same name, `services.field` added to match)
    and `views_pane.ts`'s `makeModel` both simplify: the latter's own
    `ConstructorParameters<typeof ConsoleModel>[0]` cast-through-an-
    unexported-type workaround is now a plain, direct pass-through.

  **Shared-type growth, the same "reconcile a locally-carried registry
  category into `odoo.ts`" move wave 1 first made for
  `cogMenu`/`systray`/`view_widgets`:** `views_pane.ts` is the first
  real reader of `app_builder.canvas` (the registry `canvas.ts`/
  `canvases/search_lists_canvas.ts` already register into, and
  `app_builder_report`'s own still-`.js` `report_canvas.js` also uses) --
  carried its own local `declare module` block, per the established
  "carry it locally until the facade exists" precedent, reconciled into
  `odoo.ts` centrally and dropped from `views_pane.ts`.

  **Real, behavior-relevant findings, none of them fixed:**
  `home_pane.ts`'s own `onModelFields` method is genuinely dead code
  (grepped the whole tree -- no template, no other caller); its own
  `this.orm = useService("orm")` is set but never read (every real RPC
  in that class goes through `this.model.xxx` instead). `top_bar.ts`'s
  own `healthDot()` doc comment named `home_pane.js` as "still
  untyped" -- a one-line touch-up now that it is not, applied
  centrally since it was flagged as out of the drafting file's own
  scope to fix.

  Verification: `tsc`/`eslint`/`prettier` clean (same triage policy as
  every prior wave -- no new real findings beyond the three gaps
  above). `build_ts.mjs` re-run to confirm idempotency.
  Transpile-equivalence: all three show the same dependency-list-only
  shift every production file in cluster 4 has shown since wave 1
  (`@web/core/utils/hooks` lost, `@app_builder_view/console/odoo`
  gained) -- module identity unchanged. Full tree-wide transpiler guard
  passed clean across all 74 shipped `.js` files. With this wave, every
  file in `console/` is converted except `console.js` itself (wave 4,
  the entry point).

- **TypeScript (2b, cluster 4, wave 4: `console.ts`).** The last file --
  a 25-line entry point (registers `StudioConsole` into core's own
  `registry.category("actions")`, twice, under two tags, and imports
  every pane/flow module so their own registrations run). Small enough
  to convert directly rather than through a drafting agent.

  One real gap, the same class already established for `cogMenu`/
  `systray`/`view_widgets`/`app_builder.canvas`: `"actions"` is core
  Odoo's own registry category, and this is the first file in the tree
  to register into it, so `registry.category("actions")` did not
  compile at all until declared. Transcribed
  `ActionsRegistryItemShape` in full from the real vendor
  `@types/registries/registries.d.ts` (not in `tsconfig.json`'s
  `include`, the same reason as its siblings) -- a union of a plain
  handler function or a component class, intersected with
  `displayName?`/`path?`/`target?`, matching `shell.ts`'s own
  `static target`/`static path` (neither a `Component` class-body
  member, so neither needs `override` -- already established, not a
  new finding). One vendor type could not be transcribed faithfully:
  `target`'s own real type (`ActionMode`) is referenced in the vendor
  `.d.ts` but not declared anywhere findable in the vendor's own
  `@types` tree -- typed as the plain `string` `shell.ts` actually
  assigns instead of guessing at an unlocatable type.

  Verification: `tsc`/`eslint`/`prettier` clean. `build_ts.mjs`
  idempotent. Transpile-equivalence: an exact `OK` match, name and
  dependency list both unchanged -- `console.ts` does not call
  `useService`/`ConfirmationDialog`/etc. itself, so it never routes
  anything through `odoo.ts` and has no dependency-list shift to show
  the way every other cluster-4 production file did. Full tree-wide
  transpiler guard passed clean across all 74 shipped `.js` files.

  **Cluster 4 is complete.** Every file under `app_builder_view/static/
  src/console/` is now TypeScript; the only `.js` left anywhere in this
  addon's `static/` tree is `linguist-generated` esbuild output sitting
  beside its real `.ts` source. Fourteen waves' worth of work across
  four commits (wave 1: 11 files, wave 2: 7 files, cluster 4's own
  tests: 3 files, wave 3: 3 files, wave 4: 1 file -- 25 real files plus
  three test files, 28 total), every one drafted read-only (mostly in
  parallel via the Workflow tool, three directly), reconciled and
  verified centrally against the real `tsc`/`eslint`/`prettier`/
  `build_ts`/transpile-equivalence/tree-wide-transpiler-guard toolchain
  the same way every earlier cluster was. Next: `app_builder_model`,
  `app_builder_ui`, `app_builder_report`, `app_builder_approval` static
  (2b's own plan, step 4's second half), then tours (2b step 5).

- **TypeScript (2b step 4, second half: `app_builder_model`,
  `app_builder_ui`, `app_builder_report`, `app_builder_approval` static).**
  Nine files across four sibling addons -- the same `tsconfig.json`
  (`*/static/src/**/*`) and path aliases already cover all of them, no
  new config needed. Eight independent files drafted in parallel;
  `app_builder_model/console_items.ts` (the one file with a same-addon
  dependency, on `field_popover.ts`) converted directly afterward.

  Wave-quality note, the same class of tooling trouble wave 2 first
  hit: two of the eight agents' structured-output calls returned
  unusable `content` (one a bare `"test"` placeholder, one the
  unmodified original `.js` -- extension changed, nothing else --
  despite otherwise-solid findings text) but both had written real,
  complete work to the shared scratchpad backup; recovered from there,
  the same as before. Three same-basename files
  (`app_builder_ui/console_items.js`, `app_builder_report/console_items.js`,
  `app_builder_approval/console_items.js`) all sharing one scratchpad
  filename ("console_items.ts") is a real, if not fully realized this
  time, name-collision risk the instructions themselves created --
  worth passing agents the *addon-qualified* basename
  (`app_builder_ui__console_items.ts`) next time this many
  same-named files convert in one wave, rather than relying on their
  own journal `content` being good enough not to need the scratchpad
  fallback at all (two of the three were; the third needed it and
  happened not to collide).

  A first for this migration: `app_builder_model/field_popover.ts`'s
  own `FieldPopover` is a real component **subclassed by another real
  component** (`ConsoleFieldEditor`, in `console_items.ts`) -- every
  prior Owl subclass in this tree has extended `Component` directly.
  `FieldPopover` was made generic over its own Props
  (`class FieldPopover<P extends FieldPopoverProps = FieldPopoverProps>
  extends Component<P>`, rather than fixed to `Component<FieldPopoverProps>`)
  specifically so `ConsoleFieldEditor extends FieldPopover<FieldEditorProps>`
  can widen it cleanly: `FieldEditorProps` (`types.ts`) is exactly
  `FieldPopoverProps` plus two additional, both-optional keys
  (`initial`, `mode`) the console's own contract adds and the popover's
  simpler original life did not need, so it structurally satisfies
  `P extends FieldPopoverProps` with no cast anywhere in either file.

  Two real, pre-existing bugs found, neither fixed (report, don't fix):
  `field_popover.ts`'s own `get inverse()` had the identical missing-
  `suggested` gap `field_editor_fallback.ts` found and fixed in cluster
  4 wave 1 -- fixed the same way here too, since it is the identical,
  already-established, safe correction (unreachable in practice,
  `can_create: false` on the same fallback gates the only branch that
  reads it). `field_popover.ts`'s own `onKeydown` submits on every bare
  Enter anywhere in the popover, including inside the compute-body
  `<textarea>` -- unlike `field_editor_fallback.ts`'s own `onKeydown`,
  which excludes `TEXTAREA` -- a real, live usability bug, reproduced
  as-is.

  Shared-type growth, all in `wire.ts`'s `RecordRowJSON`, the same
  "surface-specific optional field, traced to the real Python `rows()`
  override that sends it" pattern wave 2 established for `depth`:
  `view_id?: number | false` (the reports surface's own `_row()`,
  `app_builder_report/models/studio_report_surface.py`, needed by
  `app_builder_report/console_items.ts`'s "Edit layout" row action) and
  `parent_id?: number | false` (the menu surface's own `rows()`,
  `app_builder_ui/models/studio_menu_surface.py`, needed by
  `app_builder_ui/console_items.ts`'s tree-reparenting row actions --
  load-bearing there, not speculative, confirmed by two independent
  drafting agents proposing the identical addition for the identical
  real reason).

  Verification: `tsc`/`eslint`/`prettier` clean (real fixes applied:
  three `no-floating-promises`/`no-misused-promises` fire-and-forget
  sites `void`-wrapped in `build_app_flow.ts`/`report_canvas.ts`, the
  same established pattern; one confirmed-pre-existing dead function
  (`build_app_flow.ts`'s own `slug()`, never called even in the
  original `.js`) documented, not removed, the same
  `onModelFields`/`slug` precedent wave 3 set). `build_ts.mjs`
  idempotent. Transpile-equivalence: the four files that call
  `useService` show the same expected dependency-list-only shift
  (`@web/core/utils/hooks` lost, `@app_builder_view/console/odoo`
  gained) every console-tree file has shown since Phase 2c; the
  other five are an exact match. Full tree-wide transpiler guard
  (now genuinely covering all `app_builder*` addons, not just
  `app_builder_view`) passed clean across all 74 shipped `.js` files.

- **TypeScript (2b step 5: tours).** The last step of Phase 2b -- twelve
  `web_tour` files across all five addons, ~2350 lines total. Converted
  in two parts: `app_builder_approval/approvals_pane_tour.ts` directly
  first, specifically to validate a new shared type before committing to
  a parallel wave of the other eleven (the same "probe first, then fan
  out" caution used earlier in this migration for the
  `typeof Component<any, any>` variance fix) -- it turned out to need
  the fix as-is, with zero further iteration, so the remaining eleven
  were then drafted in parallel with high confidence.

  **One real, necessary shared-type gap, found before any file could
  compile at all**: `registry.category("web_tour.tours")` is core
  Odoo's own category, and nothing in this tree had registered into it
  yet -- the identical "core category outside `tsconfig.json`'s
  `include`" situation already hit for `cogMenu`/`systray`/
  `view_widgets`/`actions`. Transcribed `TourStep`/`ToursRegistryShape`
  from the real vendor `web_tour/static/src/@types/registries.d.ts`
  into `odoo.ts`, with two corrections to that file's own account,
  each confirmed against the real running tour service rather than
  guessed (the same JSDoc-vs-runtime-gap discipline already applied
  repeatedly elsewhere in this migration):
  - `url: string` (required) -- every one of the twelve real tours in
    this tree omits it entirely (`console_tour.js`'s own comment:
    "Deliberately no `url`: ... a url here would override the one
    `start_tour` passes"), and the real consumer
    (`tour_service.js`'s own `if (tour.url && ...)`) treats it as
    genuinely optional. Widened to `url?: string`.
  - `run`'s function arm, typed `() => void | Promise<void>` with no
    `this` and no parameter -- but the real call site
    (`tour_step_automatic.js`'s own `this.run.call({anchor:
    this.element}, actionHelper)`) binds `this` to `{anchor: Element}`
    and passes one argument (a real `TourHelpers` instance, left
    `unknown`: no tour in this tree reads it). Several real tours read
    `this.anchor` inside a `run` function. Widened to
    `run?: string | ((this: { anchor: Element }, helpers: unknown) =>
    void | Promise<void>)` -- also making `run` itself optional, since
    a pure wait-for-trigger step (no action, just confirming something
    is on screen) omits it in real tours.

  This is also the first time in the whole migration that a shared
  type change was validated end-to-end (probe file, real `tsc` run,
  eslint, prettier, build, transpile-equivalence) *before* fanning a
  wave out in parallel, rather than reconciling problems discovered
  across eleven simultaneous drafts afterward -- worth doing again for
  any future wave whose very first file depends on a not-yet-proven
  new shared type.

  Once the shared type existed, every one of the twelve files needed
  it via pure **contextual typing** -- `registry.category("web_tour.tours")
  .add(name, { steps: () => [...] })`'s own generic signature checks
  the whole object literal automatically, with no explicit
  `TourStep`/`ToursRegistryShape` import and no local `declare module`
  block in any of the twelve files. Nine of the twelve needed zero
  code changes beyond the file extension (every `run` a plain command
  string, no DOM queries, no `this.anchor` reads) -- the cleanest wave
  of this entire migration.

  The three that did need real type-adding work, each a straightforward
  application of an already-established idiom:
  - `console_outline_tour.ts`: `.dataset["name"]` (bracket access,
    `noPropertyAccessFromIndexSignature`), an `HTMLElement` cast for a
    `.nextElementSibling`/`.previousElementSibling` read (`.dataset`
    is `HTMLElement`-only, not on the base `Element` type the DOM lib
    gives those), and a `!` assertion for a real, tour-guaranteed
    non-null row lookup -- all three already-established idioms from
    `outline.ts`/`outline.test.ts`.
  - `console_new_field_tour.ts`: an `HTMLInputElement` cast on
    `this.anchor` (the trigger selector already guarantees it's an
    `<input>`) and a `!` assertion on a `document.querySelector`
    result the tour's own construction guarantees is present by that
    step. One reconciliation needed: the drafting agent's own first
    pass replaced the assertion with a new `if (!note) { throw new
    Error(...) }` guard instead -- a real, if practically unreachable,
    behavior change (a descriptive `Error` instead of the original's
    raw `TypeError` on the never-taken failure path). Reverted to a
    documented `!` assertion during reconciliation, matching this
    migration's own strict "type-adding pass only" rule.
  - `console_drag_tour.ts`/`console_kanban_tour.ts`: `moveTo`'s real
    position union has no `"center"` literal even though every real
    tour drag uses it (the same `@odoo/hoot-dom` gap `drag.test.ts`
    already found and fixed in cluster 3) -- each file reused that
    established `DragHelpersWithCenter`-shaped local fix rather than
    importing `drag.test.ts`'s own copy (which lives under
    `static/tests/`, not an importable module) or inventing a shared
    one -- correctly, per this migration's own "promote only once a
    third real reader appears" rule (`drag.test.ts` is the first,
    these are the second and third *files*, but the fix stays
    file-local by design, not centralized, the same way `console_kanban
    _tour.ts`'s own `findFirst` -- a `queryFirst` arity-JSDoc-gap
    workaround -- was scoped narrower than `drag.test.ts`'s own
    equivalent, returning `Element | null` rather than `HTMLElement |
    null` since this file never needs an `HTMLElement`-only member off
    a query result).

  One process note, not a code finding: `console_kanban_tour.ts`'s own
  drafting agent reported having written a temporary copy of its draft
  directly into the real project tree (to run the real toolchain
  against it) and deleted it afterward -- a more thorough variant of
  the "stray direct write despite read-only instructions" pattern this
  migration has now seen roughly eight times. Confirmed via `git
  status` that no artifact survived; treated as harmless, per the
  established precedent for this recurring pattern, but the tool file
  itself was still applied from the scratchpad backup as usual, not
  trusted blind because of the claim.

  Verification: `tsc`/`eslint`/`prettier` completely clean across all
  twelve files -- zero eslint findings of any kind, not even the
  usual `no-unsafe-*` noise. `build_ts.mjs` idempotent.
  Transpile-equivalence: all twelve are an exact `OK` match, name and
  dependency list both unchanged -- tours call vendor hooks/`registry`
  directly and never route through `odoo.ts`'s `useService`, so there
  was no dependency-list shift to expect the way most `console/`
  production files have shown since Phase 2c. Full tree-wide
  transpiler guard passed clean across all 74 shipped `.js` files.

  **Phase 2b is now complete.** Every `.js` file under any addon's
  `static/src/` or `static/tests/` in this whole addon suite has a
  real `.ts` source; every remaining `.js` file anywhere in the tree
  is `linguist-generated` esbuild output sitting beside it. Next:
  Phase 3 (enforcement, CI, docs) -- wiring the real `tsc` check into
  CI (already true via `scripts/typecheck.mjs`, confirm it is actually
  invoked there), deciding whether/when to turn on the `eslint`
  pre-commit hook now that the known `no-unsafe-*` program-construction
  bug (TYPING.md's own "Known traps") is either fixed or worked
  around, and Phase 1's own Python-side strict-typing work if it has
  not already proceeded in parallel.

- **Python (1a: configuration, finished; 1b: two more `tools/` files).**
  `catalogue.py` (the first real conversion, done at the very start of
  this whole migration) left the rest of Phase 1a's own configuration
  unfinished -- `pyrightconfig.json` had no `strict` setting for
  `tools/` at all (that one file passed on its own local `# pyright:
  strict` comment alone), and `.ruff.toml` had none of `ANN`/`TC`/`FA`/
  `PGH003`/`PYI`. Both finished now, plus `typing_extensions` added to
  all nine addons' `external_dependencies` (the plan's own last 1a
  item).

  **A real config gap, found only by testing, not by reading the
  plan's own text closely enough the first time:** the plan says
  `strict = ["*/tools"]` as if `pyrightconfig.json`'s top-level
  `"strict": [...]` glob array were the mechanism -- it compiles and
  looks right, but it does not compose with this project's own
  `"reportPrivateUsage": "none"` override (needed the moment a `tools/`
  helper reads `env[model]._fields`, since Odoo's own underscore-
  prefixed ORM attributes are framework-internal, not
  declaring-class-internal the way that rule checks): a file matched
  by the top-level `"strict": [...]` glob gets the *entire* strict
  rule bundle applied as a fixed unit, silently overriding any other
  top-level rule setting for that file regardless of where it's
  declared -- confirmed by testing a per-file `# pyright: strict`
  comment too (the mechanism `catalogue.py` itself already used),
  which has the identical override behavior. The one mechanism that
  does compose: individual `report*` rules set directly inside a
  path-scoped `executionEnvironment` block (no `typeCheckingMode` key
  there at all -- that key is rejected as "unrecognized setting" at
  that level, confirmed empirically). `pyrightconfig.json` now carries
  the full list of rules whose default differs between `standard` and
  `strict` (pyright's own documented table), applied by hand to each
  `tools/` directory's own `executionEnvironment`, with
  `reportPrivateUsage` left at `"none"` there too -- cross-checked
  against `catalogue.py`'s own already-passing file to confirm the
  hand-built rule list reproduces the identical zero-error result
  before trusting it, the same "probe before committing" discipline
  Phase 2's own tours wave used for a new shared type. `catalogue.py`'s
  own now-redundant local `# pyright: strict` comment was dropped in
  favor of the directory-wide config doing the same job.

  Two more small `tools/` files ratcheted to confirm the new config
  actually works end-to-end, not just in isolation: `checksum.py`
  (zero prior annotations; `hash_file`'s real return type is
  `str | Literal[False]`, an explicit Odoo-style sentinel its own
  docstring already names in prose) and `compat.py` (the first `tools/`
  file to touch a real Odoo type, `api.Environment` -- despite
  `catalogue.py`'s own docstring framing `tools/` as "odoo-free by
  design," that describes `catalogue.py` itself, not a rule for the
  whole directory; `compat.py`'s own module docstring already explains
  why it exists as the one deliberate exception, an Odoo-version
  compatibility shim). `compat.py` surfaced one genuine, unfixable-
  from-this-side gap: OCB's own `BaseModel._fields` is declared
  `dict[str, Field]` -- the bare, unparameterized generic, not
  `dict[str, Field[Any]]` -- so the expression is `Unknown` before any
  annotation on this file's own side could apply. A narrow, two-rule
  `# pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]`
  on that one line, not a config-level suppression (unlike
  `reportPrivateUsage`, this is not a pervasive, tree-wide pattern with
  hundreds of real call sites -- a vendor stub gap local to this one
  read, the same PGH003 "narrow, not blanket" spirit the ruff rule
  just added now enforces).

  Baseline, for scale: a full-tree `pyright` run immediately after 1a's
  config landed reports 6022 errors across 166 files (up from 3246
  under the old, incomplete config -- the difference is `tools/`'s own
  fourteen remaining files newly surfaced under strict mode, not a
  regression: non-`tools/` error count is unchanged). `tools/` itself:
  2786 errors across fourteen files (~5800 lines) once `catalogue.py`/
  `checksum.py`/`compat.py` are excluded. Next: the rest of 1b, in the
  plan's own dependency order (`modelspec`, `domainspec`, `placement`,
  `manifest`, `pogen`, `xml_writer`, `pycodegen`, `pyparse`, `scaffold`,
  `gitrepo`, `migrationgen`, then `app_builder_view/tools/`'s own
  `view_options`, `canvas_stamp`, `manualfield`).

- **Python (1b wave 1: nine independent `tools/` leaves).** Built a real
  dependency graph first (`grep` for internal imports): `modelspec` is
  the one file four others (`pycodegen`, `pyparse`, `scaffold`,
  `app_builder_view/tools/manualfield`) depend on, so it was left for its
  own focused pass; the remaining nine `tools/` files -- `domainspec`,
  `placement`, `manifest`, `pogen`, `xml_writer`, `gitrepo`,
  `migrationgen` (all `app_builder_base`), `view_options`, `canvas_stamp`
  (both `app_builder_view`) -- have no internal dependency on each other
  or on `modelspec`, so they were drafted in parallel as one wave.

  New `TypedDict` wire types, the same `to_json()`-mirroring pattern
  `catalogue.py` established: `ConditionJSON` (`domainspec.py`'s
  `Condition.to_json`), `LogEntryJSON` (`gitrepo.py`'s `log()`, proposed
  as the eventual `wire.ts` mirror once a console file consumes
  `studio_workspace.changes()`). `manifest.py` proposed `Manifest`/
  `ManifestValue` type aliases for `studio_package.py`'s own eventual
  reuse, not yet claimed by a second reader.

  **`pogen.py`**, beyond the `field(default_factory=list[Occurrence])`
  fix ("Known traps"), needed one more real fix: `polib`'s own real
  runtime accepts `None` for an occurrence's line number (confirmed by
  constructing one directly and rendering it -- produces `#: <path>`
  with no trailing `:<line>`), but its inferred signature (built from an
  untyped `**kwargs`, `polib.py` ships no stub either) resolves
  `occurrences` to `list[tuple[str, str]]`, rejecting `None` for the
  second element. A narrow, inline
  `# pyright: ignore[reportAttributeAccessIssue]` on that one
  assignment, deliberately keeping the original `None` value rather than
  substituting `""` -- a stub-vs-runtime gap local to this one line, not
  a tree-wide pattern, so not promoted to "Known traps" the way the
  lxml gap was (`polib` has exactly one reader in this tree).

  **lxml Protocol reconciliation.** All three files that touch an arch
  element (`xml_writer.py`, `placement.py`, `canvas_stamp.py`) hit the
  "lxml ships no stubs" trap independently; two of the three
  (`xml_writer.py`'s `XmlElement`/`XmlAttrib`, `canvas_stamp.py`'s own
  `LxmlElement`) each hand-rolled an almost-identical local `Protocol`
  before this was noticed, and the third (`placement.py`) had aliased
  the element type to bare `Any` instead, which is strictly weaker under
  strict mode than a real `Protocol`: `Any` silently permits any typo'd
  attribute or wrong-shaped call anywhere in the file, defeating the
  point of `reportUnknownMemberType`/friends for the entirety of a file
  that has *no* real reason to lose that checking. Reconciled into one
  canonical `app_builder_base/tools/lxml_types.py` (`app_builder_base` is
  the lower addon in the dependency direction -- `app_builder_view`
  already depends on it, not the reverse -- so this is the correct home
  even though `canvas_stamp.py` lives in the other addon), covering the
  union of every method the three real readers call, including
  `placement.py`'s own `find`/`findall`/`remove`/`insert`/`xpath`
  surface that neither of the other two touched.

  `tag`'s own type needed a real, non-mechanical decision, not a
  straight merge: `xml_writer.py`'s version used the more precise
  `str | Callable[..., object]` (a comment or processing-instruction
  node's tag is one of lxml's own factory callables, not a string), and
  a first instinct was to adopt that as the canonical, stricter choice
  everywhere. Tracing `canvas_stamp.py`'s own real call sites first
  (per this migration's standing rule, verify against real usage before
  generalizing a type) found a genuine reason its own author chose
  `Any` instead: `stamp()` assigns `element.tag` straight into
  `StudioNode["tag"]` (declared plain `str`) at a point already
  guaranteed safe by an invariant `_walk` established earlier (every
  listed element already passed `isinstance(child.tag, str)`) -- but
  that guarantee lives in a plain `list[tuple[...]]` pyright cannot
  carry narrowing through, so the union type would fail that assignment
  without an extra, runtime-unnecessary `cast`. `Any` is the one type
  honest enough to satisfy both files' real constraints simultaneously
  (confirmed directly: `pyright` on all four files together, `0 errors`,
  after standardizing on `Any`), so that is what the canonical
  `LxmlElement.tag` uses -- `xml_writer.py`'s narrower alternative was a
  nice-to-have with no real call site that needed it, not a requirement.

  Verification: `pyright`/`ruff check`/`ruff format --diff` clean across
  all ten files (the nine wave-1 files plus `lxml_types.py`); a
  full-tree `pyright` run over both `tools/` directories together
  confirms zero errors attributable to any of them (the remaining 2032
  errors are entirely `modelspec.py`/`pycodegen.py`/`pyparse.py`/
  `scaffold.py`/`manualfield.py`, the not-yet-converted backlog, plus 13
  pre-existing `reportUnusedImport` findings in the two `tools/
  __init__.py` files' own registration-style re-exports -- a Phase 1b
  cleanup item, not something this wave introduced or fixed).
  `domainspec.py`/`pogen.py`/`placement.py`/`xml_writer.py` were also
  smoke-tested against real runtime behavior directly: real project
  tests use `odoo.tests.TransactionCase`, which needs a full Odoo test
  database, but these four import cleanly with a plain `sys.path` insert
  and no Odoo bootstrapping at all, so a direct import plus manual
  function calls gave real-runtime confidence without standing up a DB.
  `view_options.py` could not be (needs full
  Odoo bootstrapping for `odoo.tools.translate`) but pyright already
  validated its types. Next: `modelspec.py` (959 lines, the one file
  four others depend on), then `pycodegen`, then `pyparse`/`scaffold`/
  `manualfield` together.

- **Python (1b: `modelspec.py`, the shared foundation).** 959 lines, the
  one `tools/` file `pycodegen.py`, `pyparse.py`, `scaffold.py` and
  `app_builder_view/tools/manualfield.py` all import from -- converted
  alone rather than alongside another file, both for its size and
  because getting its public dataclass/function shapes right matters
  more than usual (four still-untyped readers already depend on them).
  Its six `@dataclass(frozen=True, slots=True)` classes already carried
  real field-level annotations before this pass (this file's own floor
  is already py3.10, which evaluates `X | None` at runtime with no
  `from __future__ import annotations`) -- what was missing was
  `from __future__ import annotations` itself plus every plain function/
  method signature.

  Reused, rather than rediscovered, `view_options.py`'s own precedent
  (wave 1) for `available_field_types(spec=None, translate=catalogue
  .identity)`: `catalogue.identity` does not satisfy `catalogue
  .Translator` (`Callable[[Label], str]`) as a default value --
  specializing `identity`'s `Callable[[_T], _T]` at `_T = Label` gives
  `Callable[[Label], Label]`, and `Label = str | LazyGettext` is wider
  than `str` -- deliberately, per `catalogue.identity`'s own docstring
  (which already named both `view_options.py` and `modelspec.py` as
  intended to keep this default: both are pure-data modules with no
  Odoo environment in scope to resolve a lazy translation, so `catalogue
  ._default_translate`, which raises on an unresolved one, would be a
  real behavior change here, not a type-adding one). Same fix, same
  reasoning: `# pyright: ignore[reportArgumentType]` on that one
  parameter line.

  Two new `TypedDict`s, both real, already-shipped wire data (sent to
  the console verbatim, not internal-only): `PlacementJSON` (`{form,
  list, search, group_by, widget}`, what `default_placement`/
  `clean_placement` build) and `FieldTypeJSON` (`available_field_types`'
  per-entry shape, embedding both `PlacementJSON` and `catalogue
  .WidgetJSON`). `clean_placement`'s own construction needed a `cast`
  back to `PlacementJSON`, not because the dict is wrong -- it is built
  from exactly `PLACEMENT_SLOTS` plus `widget`, the identical fixed
  shape -- but because it writes through a `for slot in (...)` loop's
  dynamic key, which a `TypedDict` does not accept as a write target;
  the loop's own guarantee is invisible to pyright, so the cast says by
  hand what construction already proves.

  One small, deliberate helper added -- `_field_from_stored`, factoring
  `spec_from_json`'s per-field `FieldSpec(**{**f, ...})` merge-splat out
  to its own function: pyright loses track of a merged dict-display's
  value type through that spread even when the source is a clean
  `Mapping[str, Any]`, and reports every `FieldSpec` keyword as unknown.
  Confirmed behavior-neutral (see verification below), a type-only
  extraction, not a new code path.

  Considered and deliberately **not** added: a `FieldSpecJSON`/
  `ModelSpecJSON` TypedDict for `spec_to_json`'s `asdict()` output --
  genuinely `Any`-shaped both ways (arbitrary `asdict()` output in, an
  arbitrary client payload out), and TYPING.md's own TS-side "Implemented
  so far" already tracks `FieldSpec`/`SelectionSpec` themselves as the
  wire-shape source of truth for that boundary; a second TypedDict here
  would describe the same shape twice instead of once.

  **Verification, including a check beyond what any prior wave in this
  migration ran:** `pyright`/`ruff check`/`ruff format --diff` clean;
  full-tree `pyright` over both `tools/` directories dropped from
  wave-1's 2032 errors to 1561, with the only surviving hit outside the
  four still-untyped files (`scaffold.py`/`pycodegen.py`/`pyparse.py`/
  `manualfield.py`) being the pre-existing, already-documented
  `tools/__init__.py` `reportUnusedImport` backlog item. Beyond the
  usual sys.path smoke test (no Odoo DB needed -- this file has zero
  odoo imports), a **byte-for-byte behavioral-equivalence check**: the
  original, pre-typing file (`git show HEAD:...`) and the newly-typed
  one loaded as two isolated packages side by side, both exercised
  through an identical script -- `FieldSpec`/`ModelSpec` construction,
  `spec_to_json`/`spec_from_json`/`field_spec_from_json` round-trips,
  `validate_spec` (clean and invalid specs), `diff_specs` (normal,
  `before=None`, `after=None`), `available_field_types()` (with and
  without a currency field present), `apply_preset`, `default_placement`/
  `clean_placement`, `is_builder_method`, `field_type_for(None)`,
  `canonical_source` -- with both runs' JSON-serialized output diffed.
  Identical. Next: `pycodegen.py`.

- **Python (1b: `pycodegen.py`).** 632 lines, the file that renders a
  `ModelSpec` into the machine-owned block of a generated model file --
  the second `tools/` file (after `modelspec.py`) that four still-
  untyped readers (`pyparse.py`, `app_builder_base/models
  /studio_model_draft.py`, `app_builder_ui/models
  /studio_graduate_code.py`, `app_builder_model/models
  /studio_app_builder.py`, `app_builder_approval/models
  /studio_approval.py`) import from. Built this time as a two-stage
  workflow -- one agent drafted the typed file, a second, independent
  agent re-ran every verification step itself from scratch (own pyright/
  ruff runs, its own `reveal_type` probes against the real merged tree,
  its own from-scratch behavioral-equivalence script) rather than
  trusting the draft's self-report -- and both agents' full verification
  was then redone a third time in the main loop before committing. All
  three independent passes agree, including on the exact full-tree error
  count (1168) and file-by-file attribution.

  The first file in this migration where the "one Odoo-aware function"
  (`spec_from_ir_model`/`_field_spec_from_record`, the module's own
  docstring's words) needed *specific* Odoo model recordset types, not
  the generic `api.Environment` `compat.py` used: `IrModel`/
  `IrModelFields`/`IrModelSelection`, imported `TYPE_CHECKING`-only from
  `odoo.addons.base.models.ir_model` in the merged tree at
  `../../.devenv/state/pythonpath` (already configured via
  `pyrightconfig.json`'s `extraPaths`, nothing new to wire up). This is
  where both new "Known traps" entries above came from -- the
  unannotated `.sorted(key=...)` lambda gap and the five `IrModelFields`
  attributes that read `str | bool` instead of the usual `str |
  Literal[False]`.

  No new shared types: unlike `modelspec.py`, this file renders Python
  *source text* (strings), not JSON, so there is no wire shape here
  comparable to `PlacementJSON`/`FieldTypeJSON`. One new private,
  unexported helper, `_selection_sort_key`, purely to give `.sorted()` a
  real, non-lambda, explicitly-typed `key` function (see "Known traps").

  Verification: `pyright`/`ruff check`/`ruff format --diff` clean;
  full-tree count across both `tools/` directories dropped from
  `modelspec.py`'s 1561 to 1168 (`pycodegen.py`'s own prior 392-error
  standalone count accounts for the drop almost exactly), with the
  remainder entirely `scaffold.py`/`pyparse.py`/`manualfield.py` plus
  the pre-existing 13-error `tools/__init__.py` backlog item -- nothing
  new anywhere outside this file. Runtime smoke-tested (no DB) across
  every odoo-free function; `spec_from_ir_model`/`_field_spec_from_record`
  cannot be (need real `ir.model`/`ir.model.fields` rows), same as every
  prior file's Odoo-aware function. Byte-for-byte behavioral-equivalence
  check against the original file, independently run three times (draft
  agent, verify agent, main loop), covering `render_model`'s full
  pipeline across five hand-built specs (every renderable field type
  plus one unsupported one, an `_inherit` extension, a transient model,
  an empty model, sql_constraints, methods, a sequence-backed `create`
  override) plus every other public function -- identical all three
  times. Next: `pyparse.py`.

- **Python (1b: final wave -- `pyparse.py`, `scaffold.py`,
  `manualfield.py`).** The last three `tools/` files, converted in
  parallel once their shared dependencies (`modelspec.py`, `pycodegen.py`)
  were both done and each was confirmed independent of the other two
  (`pyparse.py` and `scaffold.py` each import only `modelspec`/
  `pycodegen`; `manualfield.py` imports only `modelspec`). Built as a
  three-item pipeline workflow, each file going through its own draft ->
  independent-verify pair, then re-verified a third time in the main loop
  before committing -- the same process `pycodegen.py` established, run
  three times over. **Every `tools/` file in both `app_builder_base` and
  `app_builder_view` is now strict-mode typed**, closing out Phase 1b
  entirely: a full-tree `pyright` run over both directories now reports
  only the pre-existing 13-error `tools/__init__.py` `reportUnusedImport`
  backlog (documented since wave 1), down from wave 1's 2032.

  **`pyparse.py`** (451 lines) is `pycodegen.py`'s exact mirror --
  parsing a studio-generated block back into a `ModelSpec` via the `ast`
  module -- and is the first file in this migration typed against
  Python's own stdlib `ast` node types (`ast.ClassDef`, `ast.Assign`,
  `ast.Call`, `ast.keyword`, etc.) rather than a vendor/Odoo boundary;
  typeshed's own bundled `ast` stubs made this mostly straightforward,
  with two `cast()`s needed for "already true by construction, invisible
  to pyright across a function/string-template boundary" situations
  (mirroring `pycodegen.py`'s own such casts, not `ast`-specific). One
  real, dead function removed: `_segment` (an unused helper subsumed by
  `_verbatim`, confirmed via a whole-repo grep for callers, flagged by
  plain `reportUnusedFunction` under this directory's strict rules --
  removed rather than suppressed, since a narrow `# pyright: ignore` is
  reserved for real typing gaps, not dead code). One pre-existing,
  unrelated gap flagged, not fixed: `_selection()`'s tuple-unpack has no
  shape validation, so a malformed selection literal crashes with a raw
  `ValueError`/`TypeError` rather than this file's own consistent
  `UnsupportedConstruct` -- a real behavior change to fix, out of scope
  for a type-only pass. Verification included the strongest form this
  migration has used yet: real `pycodegen.render_model -> pyparse
  .parse_model` round-trips (`parse(render(spec)) == spec` and
  `render(parse(source)) == source`, the exact fixed-point property
  `pycodegen.py`'s own docstring states this pairing exists for) across
  every field type, model attribute and refusal path, independently
  built twice (draft agent, verify agent) plus a third smoke test in the
  main loop -- all in agreement.

  **`scaffold.py`** (1088 lines, the largest `tools/` file) builds the
  default form/list/kanban/calendar/search/pivot/graph/activity/timeline/
  report archs for a newly scaffolded model, and is the third of the
  three files `lxml_types.py`'s own `LxmlElement` Protocol was built
  anticipating (after `xml_writer.py`/`placement.py`) -- imported and
  reused as intended, no new local Protocol. Two design decisions worth
  recording: `ScaffoldOptions` (a hand-rolled, non-dataclass class with a
  `__getattr__` returning `bool` for any of a closed, registry-derived
  set of feature names) needed no restructuring at all -- pyright treats
  a class's own `__getattr__` as the fallback type for every otherwise-
  undeclared attribute read on its instances, confirmed with a standalone
  probe before trusting it in the real file. `SCAFFOLD_BUILDERS`'s nine
  inline lambdas needed the "give it its own signature" fix (see "Known
  traps"). New: a narrow, locally-declared `ModelLike` Protocol (`_fields:
  dict[str, Field[Any]]` only -- every real reader in this file touches
  nothing else on the live model parameter), the same "narrow, hand-traced
  boundary" discipline as `lxml_types.py` itself; two `TypedDict`s
  (`FeatureJSON`, `ReportLayoutJSON`) for `features_json`/
  `report_layouts_json`'s real wire shapes.

  **`manualfield.py`** (397 lines, `app_builder_view/tools/`) translates
  the picker's vocabulary into a live `ir.model.fields.create()` payload
  -- genuinely Odoo-aware throughout (every function takes `env`), unlike
  every other `tools/` file's "mostly pure, one exception" shape. Reused
  `compat.py`'s established `_fields: dict[str, Field[Any]]` idiom and
  `pycodegen.py`'s `IrModel`/`IrModelFields` `cast()` idiom (including the
  five-attribute `str | bool` cast) throughout, rather than reinventing
  either. Surfaced both new "Known traps" entries above (`env._`'s
  unannotated varargs, the `@ormcache`-decorated-method stub gap) --
  the first genuinely recurring, since most of Phase 1c's model files
  will call `self.env._(...)` directly. One self-flagged, and confirmed
  correct, deviation from the task's own suggested precedent: `compat.py`
  itself currently fails a plain `ruff check` (`TC002`, its `api`/`Field`
  imports are not `TYPE_CHECKING`-guarded, a pre-existing gap from an
  earlier wave, not this task's to fix) -- `manualfield.py` guards its own
  equivalent imports instead, matching the more recent, more comparable
  `pycodegen.py` precedent.

  Verification for all three: `pyright`/`ruff check`/`ruff format --diff`
  clean; full-tree count confirmed identically by both the draft and
  verify agent for each file, then a third time in the main loop;
  independent, from-scratch byte-for-byte behavioral-equivalence checks
  (real ORM fakes for `manualfield.py`'s `env`-touching functions, real
  round-trips for `pyparse.py`, real arch-building calls for
  `scaffold.py`) run twice per file by the two agents and spot-confirmed
  a third time in the main loop -- identical every time. **Phase 1b is
  now complete.** Next: Phase 1c (models -- full annotation, `Self` for
  recordset methods, `TYPE_CHECKING`-guarded relational field imports,
  RPC `TypedDict`s in `wire.py`, per-file strictness ratchet), per
  TYPING.md's own original Phase 1 plan.

- **Python (1c kickoff: `typed.py`, the dependency map, and the first
  model file).** Phase 1c's own scope is ~16.3k lines across 47 model
  files in 8 addons (a full re-survey found 9 more lines/files than the
  plan's own original estimate: `app_builder_base/models/serializers/`, a
  subpackage of 8 files/1058 lines the first line-count pass missed by
  globbing `models/*.py` without recursing).

  **`app_builder_base/tools/typed.py`** (new): `model(env, cls)` replaces
  `self.env["model.name"]` throughout. `Environment.__getitem__` returns
  the bare `BaseModel` regardless of which model was asked for; this
  reads the real name off the class itself (`cls._name`) instead of
  asking for it a second time as a string, so the model name and the
  class it names can never drift apart at a call site, and the one cast
  this needs lives here instead of at every one of them. One real
  implementation wrinkle: `cast(cls, ...)` (the value, following the
  plan's own literal example text) trips ruff's `TC006` ("add quotes to
  type expression"), which auto-fixes it to the broken `cast("cls", ...)`
  -- `"cls"` is not a valid forward reference, it is a parameter holding
  a runtime value. Fixed by casting to the type parameter `M` itself,
  by name (`cast("M", ...)`), the standard generic-helper idiom and
  arguably more correct anyway: the return type genuinely *is* `M`, not
  "whatever `cls` happens to hold." Verified against a real class from
  the merged tree (`IrModel._name` resolves to a plain `str`, as
  expected) and a fake-ORM smoke test.

  Also fixed, in passing, a small pre-existing gap `compat.py` carried
  from an earlier wave (its `api`/`Field` imports were not
  `TYPE_CHECKING`-guarded, failing a plain `ruff check` -- flagged twice,
  independently, by wave-3's own agents as out-of-scope-but-worth-fixing;
  fixed now since `typed.py` sits right beside it).

  **Dependency map.** Before converting anything, mapped every model
  file's own `_name`/`_inherit` and every real reference to another
  `app_builder`-defined model (via a `fields.Many2one/One2many/Many2many`
  comodel string or a literal `self.env["studio...."]` key -- dynamic
  `self.env[some_variable]` dispatch onto an arbitrary *target app*
  model, which most "surface" files do constantly, is not a graph edge
  and was excluded). Full per-file breakdown is not reproduced here (it
  would rot fast); the headline structure:
  - Addon-level layers confirmed from real `__manifest__.py` `depends`
    (corrects an assumption in the original 1c plan text):
    L0 `app_builder_base` → L1 `{app_builder_view, app_builder_ui,
    app_builder_mail, app_builder_approval}` → L2 `{app_builder_model
    (needs app_builder_view), app_builder_approval_formula (needs
    app_builder_approval), app_builder_report (needs app_builder_ui +
    app_builder_view)}`. `app_builder_model`'s one file never actually
    references any `app_builder_view` model in Python despite the
    manifest dependency (that dependency is for JS/menu assets, not
    model references) -- worth remembering so that dependency does not
    over-block its own conversion.
  - File-level wave order within that (6 waves, roots to leaves): wave 0
    = `studio_security.py`, `studio_serializer.py`, `res_users.py`
    (nothing in scope depends on anything else); wave 1 adds
    `studio_package.py`, `studio_domain.py`, and everything that only
    extends `studio.serializer` directly (`base_automation_serializer
    .py`, `tier_serializers.py`, all 8 of `serializers/*.py`); waves 2-5
    build outward through the surface-mixin hierarchy
    (`studio_record_surface.py` → `studio_security_surfaces.py`/
    `studio_menu_surface.py`/`studio_automation_surface.py`/
    `studio_report_surface.py`/`studio_approval_surface.py`) and the
    view/report/approval leaves.
  - **Three real circular references found**, not resolved, just noted
    for whoever converts each pair: `studio_package.py` ↔
    `studio_package_model.py` and `studio_package.py` ↔
    `studio_package_apply.py` (aggregate-root/child FK pairs -- convert
    `studio_package.py` first, forward `TYPE_CHECKING` imports for the
    other two's classes); `studio_view_editor.py` ↔ `studio_view_edit.py`
    (convert the shallower `studio_view_edit.py` first, one forward
    `TYPE_CHECKING` ref back into `StudioViewEditor`).
  - Most `studio.*` classes are `AbstractModel` (no table of their own,
    never instantiated standalone) -- `typed.model()`'s own semantics
    (an empty recordset handle for a real, table-backed model) need a
    second look for these once one is actually converted: methods still
    need typing, but "the model" isn't a thing with rows to type against
    the way `studio.package`/`studio.package.model`/`studio.view.edit`
    (real tables) are.
  - RPC-heaviest files (`@api.model`-decorated public method count,
    `wire.py` `TypedDict` candidates once that phase starts):
    `studio_view_editor.py` (74, the de facto RPC surface for the whole
    console, including `canvas()` -- the plan's own named "model case"
    for this, in `studio_view_canvas.py`), `studio_record_surface.py`
    (42), `studio_automation_surface.py` (33), `studio_workspace.py`
    (32), `studio_serializer.py` (26).

  **`studio_security.py`** (66 lines, wave 0, the literal security root
  every other mixin inherits) -- the first model file converted, and
  where the two new "Known traps" above (the plain `_` import, `env
  .user` -> `BaseModel`) were found. `Literal[True]` for the three guard
  methods (`_assert_studio_user`/`_assert_studio_manager`/
  `_assert_studio_group`): each either returns `True` or raises, never
  reaches a `False`, confirmed by checking every real call site (~110
  across the whole suite) -- all bare statement-level calls for the
  side effect, none reading the return value, so the precision costs
  nothing and states the real invariant, the same spirit as
  `checksum.py`'s own `str | Literal[False]`. Verified: `pyright`
  (0 errors under stage-1/standard mode) / `ruff check` / `ruff format
  --diff` clean; the diff reviewed by hand to confirm it is exactly
  annotations plus the one inline cast, with the boolean expression's
  original short-circuit evaluation order deliberately preserved rather
  than simplified into an eagerly-evaluated intermediate variable; the
  module imports and registers cleanly against the real merged tree.
  Next: the rest of wave 0 (`studio_serializer.py`, `res_users.py`),
  then wave 1.

- **`res_users.py`** (15 lines, wave 0) needed zero changes: no methods
  (a pure `_inherit` extension adding one `fields.Char`), and the plan's
  own "relational fields typed with Odoo's own syntax" only covers
  relational fields -- `Char`/`Boolean`/etc. aren't generic the way
  `Many2one[M]` is, so a scalar field's class-body declaration has
  nothing to re-annotate; its real read/write typing already comes from
  `Field`'s own descriptor `__get__`/`__set__` overloads with no per-field
  annotation needed. Confirmed clean under stage 1 (standard mode + `ANN`)
  exactly as committed, with no diff.

- **`studio_serializer.py`** (549 lines, wave 0, 26 `@api.model` methods
  -- the base class every concrete serializer subclass, in `serializers/
  *.py` and elsewhere, inherits) -- the third model file, and the first
  one built as a draft-then-independently-verify two-agent pipeline (the
  pattern that served Phase 1b well for files this central). Both agents'
  full verification, plus a third spot-check in the main loop, agree.

  Real, non-studio business models (a `record` of whatever model the
  serializer is currently emitting, or a `comodel` string it is pointed
  at) are typed `BaseModel` throughout, `TYPE_CHECKING`-imported from
  `odoo.models` -- the honest type for a model genuinely known only at
  runtime, not a gap to fix; `app_builder_base/tools/typed.py`'s
  `model()` helper deliberately does NOT appear anywhere in this file,
  since nothing here looks up a *known, literal* `app_builder` model name
  the way that helper exists for. Reused, not reinvented: the
  `record._fields`/compat.py-style ignore idiom (6 call sites), the
  canonical `lxml_types.LxmlElement` (aliased locally as `Element`, see
  the new "Known traps" note on why that one import can't be
  `TYPE_CHECKING`-guarded) and the `_element`-constructor cast wrapper
  `placement.py`/`xml_writer.py` already established, and the
  `cast("...", ...)`-for-a-real-but-type-system-invisible-invariant
  idiom `studio_security.py` set (here: `cast("str", self._studio_model)`
  in `_serialize`, since the base class declares it `str | None` but
  every concrete subclass overrides it with a literal string before
  `_serialize` is ever reachable). `Self` was traced and deliberately
  not used anywhere -- no method here actually returns a recordset of
  the serializer's own type. Three new "Known traps" surfaced (all
  above): `Environment.get`'s own separate untyped hole,
  `Field.default`'s startling-looking-but-harmless inferred type, and
  the `TypeAlias`-needs-a-real-import nuance.

  Verification (both agents independently, plus a third check in the
  main loop): `pyright` clean under the unmodified top-level config
  (confirmed `pyrightconfig.json` untouched -- no stage-2 escalation
  slipped in) -- and, worth noting, the untyped original already carried
  one real pyright error (`"etree" is unknown import symbol`) plus 54
  ruff `ANN`-class findings, both now zero; `ruff check`/`ruff format
  --diff` clean; a hand-built fake-ORM behavioral-equivalence harness
  (no live DB needed -- every method here is pure ORM introspection over
  an already-loaded record) run independently three times in total (once
  per agent, once by the main loop, each a from-scratch harness, none
  reusing another's script) comparing the original and typed file's
  output across every real branch (every `_should_skip` path including
  the Char/False/'' quirk and the callable-default-raising path, every
  `_field_node` ftype, `_assert_complete`'s three outcomes,
  `_reference_xmlid`'s two paths) -- byte-for-byte identical every time.
  Line-by-line diff review, independently by both agents and the main
  loop, confirms every changed line is an annotation, a comment, the
  `_fields` idiom, the `etree.Element` -> `_element` swap, or the one
  `cast`. **Wave 0 is now complete** (`studio_security.py`,
  `studio_serializer.py`, `res_users.py`). Next: wave 1 (`studio_package
  .py`, `studio_domain.py`, and everything that extends `studio
  .serializer` directly -- `base_automation_serializer.py`,
  `tier_serializers.py`, all 8 of `app_builder_base/models/serializers/
  *.py`).

- **`studio_package.py`** (1853 lines, wave 1, the single most-depended-
  upon file in the whole addon suite -- two real circular references,
  both children of this one aggregate root, orbit it). The most heavily
  verified file this migration has produced: the usual draft-then-
  independently-verify two-agent pipeline, PLUS a third, structural
  check in the main loop -- an AST-level comparison of the original and
  typed files with every type annotation, `cast()`, and `typed.model()`
  call mechanically stripped/normalized away, diffing what remains.
  Every real difference the structural diff found was either an import
  statement or a provably-safe "read a value once into a local variable,
  reuse it" extraction (confirmed side-effect-free: a field read on an
  already-fetched record, cached before several repeated uses, nothing
  mutating it in between) or a necessary rename to avoid a new import
  shadowing an existing local name (`IrModel` the class vs. `IrModelSudo`
  the `.sudo()`-bound local in `_python_depends`) -- zero real logic
  changed anywhere, independently confirmed three separate ways. This is
  also the file four of this session's "Known traps" entries above came
  from (typed relational fields' real failure mode, same-addon imports
  must stay relative, `typed.model()`'s TYPE_CHECKING-only-class
  limit, the `_inherit`-mixin-invisible-to-pyright pattern, `fields
  .Selection([...])`'s stub gap, `@api.model_create_multi`'s stub gap,
  `Environment.cr`'s too-abstract declared type) -- all confirmed, not
  merely proposed, by the independent verify agent redoing each one
  with its own fresh probe rather than trusting the draft's account.

  Two real, pre-existing design gaps surfaced and deliberately left
  unfixed (this migration's "flag, don't fix" rule, doubly warranted
  here given the file's operational weight): `_render_files`' CSV path
  calls `serializers._for_model("ir.model.access")` with no `is not
  None` guard before using the result -- already true, silently, in the
  untyped original (nothing there could check it either); typing it
  preserves the exact same implicit assumption rather than adding or
  removing a runtime guard. Relatedly, `_csv_row`/`_render_csv` (only
  ever defined on the one real `"csv"`-format serializer,
  `serializers/ir_security.py`, not yet converted) are not part of
  `StudioSerializer`'s own declared contract -- a real, duck-typed-by-
  convention gap between `_studio_format: Literal["xml", "csv"]` and
  what a `"csv"` value actually requires the subclass to supply. Both
  are now visible in the type system as an honest `Any`/a cast to the
  one concrete class involved, exactly where they already were, not
  papered over.

  Two follow-up improvements applied immediately, once wave 1's own
  findings made them concrete rather than speculative:
  - **`app_builder_base/tools/typed.py` gained a second helper,
    `security(self)`**, generalizing the `cast("StudioSecurityMixin",
    self)` idiom `studio_package.py` needed 8 times into one place --
    matching the same "promote once a real, recurring pattern is
    confirmed" bar `lxml_types.py` was held to, except here the bar was
    already cleared within a single file (8 call sites, and `studio
    _security.py`'s own docstring already says the guard is called from
    nearly every studio RPC method, so the rest of Phase 1c will hit
    this constantly). `studio_package.py`'s own already-verified 8
    inline casts were deliberately left as they are rather than
    retrofitted to the new helper -- behaviorally identical either way,
    and rewriting an already-verified 1853-line file for a style-only
    win was not worth the risk. Every file converted from here on
    should use `typed.security(self)` from the start.
  - **`studio_serializer.py`'s own `_for_model` return type tightened**
    from `BaseModel | None` (wave 0's own choice) to `StudioSerializer |
    None`, once `studio_package.py` became the first real caller and
    needed `cast("StudioSerializer", serializer)` at every one of its
    ~7 call sites to reach any serializer-specific method. `StudioSerializer
    | None` is the more honest type in the first place -- every real
    ``"studio.serializer.*"`` registry entry is `_inherit`-composed from
    `StudioSerializer` by the dispatch convention `_for_model`'s own
    docstring already describes, the same "true by construction,
    invisible to the type system" shape as every other cast in this
    migration -- not a new invariant invented to suit one caller.
    Re-verified clean after the change: `studio_serializer.py` itself,
    and `studio_package.py` as its first real consumer (whose own
    casts against the old, wider signature become redundant but
    harmless, and were left alone for the same reason as the
    `security()` retrofit above).

  Next: the rest of wave 1 (`studio_domain.py`, `base_automation
  _serializer.py`, `tier_serializers.py`, all 8 of `app_builder_base
  /models/serializers/*.py`).

- **Wave 1 is now complete**: `studio_domain.py` plus the 9 remaining
  `studio.serializer` subclasses (`base_automation_serializer.py`,
  `tier_serializers.py`, all 8 of `app_builder_base/models/serializers/
  *.py`) -- 10 files, confirmed mutually independent, converted as one
  pipeline (draft -> independent-verify per file, the same two-agent
  shape as every file since `pycodegen.py`). Full-tree `pyright` across
  every addon: 3090 errors, down from wave 0's baseline.

  `studio_domain.py` (159 lines, the one non-serializer file in this
  wave) needed `typed.security(self)` at all four of its `@api.model`
  RPC entry points (the file most call sites of it yet in one place).
  Its own JSON-shaped payloads got real `TypedDict`s traced from what
  each method actually builds/consumes (`FieldSpecJSON`,
  `ReadDomainJSON`, `CheckDomainJSON`, `DomainRowJSON`, etc.) -- the
  first Phase 1c file to need this, following the exact `to_json()`-
  wire-type discipline Phase 1b established.

  The 9 serializer subclasses surfaced four of the six new "Known
  traps" above (the `super()`-composition-invisible pattern and its
  `typed.serializer()`/`typed.serializer_super()` fix; the
  `_inherits`/`delegate=True`-field gap; the `fields.Reference`
  too-abstract-type gap; `LxmlElement.iter()`'s real tag-filtered form)
  plus the `_sort_key` base-widening fix, applied immediately once
  confirmed (the same "fix the base once downstream evidence is real,
  not before" discipline as `_for_model`'s own fix in wave 0).
  `_csv_row`/`_render_csv` (`ir_security.py`'s `IrModelAccessSerializer`,
  the one real `"csv"`-format serializer) reconfirmed the same
  not-part-of-the-base-contract design gap `studio_package.py`'s own
  conversion already flagged -- still not fixed, a real product
  decision for a human, not a typing one.

  Both agents on every one of the 10 files did real, adversarial
  verification -- several verify-stage reports correctly caught draft
  agents overclaiming novelty ("first occurrence" claims that weren't,
  once the whole wave's findings were compared side by side in the main
  loop) or leaving an inert `# pyright: ignore` (a rule that is not
  actually enabled under the current standard-mode config, carried
  anyway per the established "front-load stage 2" precedent from
  `studio_serializer.py`'s own wave-0 conversion) -- none of which
  affected whether any file's own code was correct, only the accuracy
  of its self-reported narrative. **Phase 1c's wave 1 is complete.**
  Next: wave 2 (`studio_package_model.py`, `studio_package_apply.py` --
  closing the two circular references `studio_package.py` opened with
  `TYPE_CHECKING`-only forward imports -- plus `studio_owned_mixin.py`
  and `studio_record_surface.py`).

- **`studio_package_model.py`, `studio_package_apply.py`,
  `studio_owned_mixin.py`** (three mutually-independent files, wave 2's
  own first batch, converted as one pipeline). The two circular
  references `studio_package.py` opened are now closed from both sides:
  `package_id`/`studio_package_id` (the `Many2one` back to
  `studio.package` each of these three files declares) stay unannotated
  at the declaration per the established relational-field rule, with
  `cast("StudioPackage", ...)` at every real read site. `studio_package
  _apply.py` already had one real (non-`TYPE_CHECKING`) import from
  `studio_package.py` (`_mute_dev_watcher`) -- added `StudioPackage` to
  that same real import rather than a second, `TYPE_CHECKING`-only one,
  since `studio_package.py` itself never imports this file back for
  real, so there is no cycle to create. Verified with the strongest
  circular-import test this migration has run: not just this file set,
  but every dependent addon (`app_builder_view`, `app_builder_ui`,
  `app_builder_model`, `app_builder_report`, `app_builder_approval`,
  `app_builder_mail`, `app_builder_approval_formula`) imported cleanly
  against the real merged tree after applying all three.

  One real, pre-existing, latent bug found and left unfixed (flag, don't
  fix): `studio_owned_mixin.py`'s own `_search_studio_package_id` only
  special-cases a `list` value for its `in`/`not in` branch -- a caller
  passing a *tuple* (`[("studio_package_id", "in", (3, 4))]`, a domain
  shape some ORM callers use interchangeably with a list) would silently
  wrap it as a single malformed id rather than iterating it. No real
  caller in this codebase currently searches this field that way
  (confirmed by grep), so this is latent, not active -- left exactly as
  written.

- **`studio_record_surface.py`** (630 lines, 42 `@api.model` methods --
  the base class every "surface" subclass across `app_builder_ui`,
  `app_builder_report` and `app_builder_approval` will inherit; none of
  those five subclasses are converted yet, so this file's own contract
  is what they'll all be checked against). Full-tree `pyright`: 2999
  errors, under 3000 for the first time.

  Real, unprompted cross-validation this migration hasn't had before:
  the draft agent found and cross-checked every new `TypedDict` against
  `app_builder_view/static/src/console/wire.ts`'s own hand-kept
  `Record*JSON` interfaces (written during Phase 2's TypeScript
  conversion, well before this file's own). All matched except one real,
  minor discrepancy, noted for a human rather than fixed here (`wire.ts`
  is a different file, out of this task's scope): `wire.ts`'s own
  `RecordRowJSON.owner` is typed `string | false`, but tracing `_owner`'s
  real Python body shows `module` is always a plain, possibly-empty
  `str`, never `False` -- typed honestly to match the traced Python
  reality (`RecordOwnerJSON.module`/`RecordRowJSON.owner` both `str`);
  worth tightening `wire.ts` to match, next time that file is touched.

  Two more real, pre-existing gaps found and left unfixed: `_check_domain
  ()`'s three real return branches are internally inconsistent -- the
  early "unknown model" branch sends `{"valid": True, "count": 0}` with
  no `total` key at all, while the real search-success branch always
  sends `total` too; typed honestly with `total: NotRequired[int]`
  rather than inventing a `total=0` the early branch never actually
  sends. `_selection_choices()` builds its `[value, label]` entries as
  plain lists, while `catalogue.py`'s own `Row.to_json()` builds the
  semantically identical shape as tuples everywhere else in the same
  wire contract -- both serialize to an identical JSON array (not
  observable to the console), a real but harmless Python-level
  inconsistency, bridged with a narrow `cast()` rather than silently
  rewritten into a one-line behavior change outside this pass's mandate.

  `describe()`'s own return type deliberately stays `dict[str, object]`
  rather than a closed `TypedDict`: `_describe_extra`'s own base
  contract is `{}`, but real (not-yet-converted) subclasses already
  widen it with keys this base file has no way to enumerate
  (`studio_security_surfaces.py`'s `ir.rule` surface returns `{"matches":
  check}`; `studio_automation_surface.py`'s automation surface returns
  `{"matches": ..., "children": {...}}`) -- the same genuinely-open-ended
  shape `wire.ts`'s own `RecordDescription` interface already models
  with an index signature Python's `TypedDict` has no equivalent for.

  Verification matched every prior file's bar: `pyright`/`ruff check`/
  `ruff format --diff` clean; `pyrightconfig.json` confirmed unchanged;
  every one of the file's 12 literal `self.env[...]` lookups confirmed
  routed through `typed.model()` (none missed, none extra) while every
  genuinely dynamic one (`self.env[self._surface_model]`,
  `self.env[model_name]`, `self.env[row.comodel]`) was correctly left
  alone; all 9 real `typed.security(self)` call sites confirmed; a
  complete line-by-line review of the full diff. One trivial fix applied
  before landing: a stray comment referencing "this file's own
  `newSharedTypes` note" -- an artifact of the drafting agent's own
  report-writing process leaking into a shipped source comment, caught
  by the verify agent and corrected in the main loop before commit.

  This closed the `app_builder_base`-only portion of wave 2's own
  dependency-map file list. The rest of wave 2 -- `studio_view_edit.py`
  (`app_builder_view`), `studio_automation.py`/`studio_security_surface
  .py` (`app_builder_ui`), `studio_report.py` (`app_builder_report`),
  `tier_formula_serializer.py` (`app_builder_approval_formula`) and
  `mail_serializers.py` (`app_builder_mail`) -- was converted next, as a
  6-file parallel batch (one draft agent per file, independent -- none
  of the 6 import each other -- plus one adversarial verify agent over
  the whole batch). Full-tree `pyright` dropped from 2990 to 2923 errors
  (a drop of 67, not just 6 -- converting these files' own type surface
  also resolved downstream errors in files that import from them).
  `pyrightconfig.json`/`pyrightconfig.ci.json`/`pyproject.toml` confirmed
  unchanged. This closes wave 2 in full.

  **`studio_view_edit.py`** (262 lines) resolves this migration's third
  and last mapped circular reference (`studio_view_editor.py` <->
  `studio_view_edit.py`) the same way `studio_package.py`'s own two
  pairs were resolved: the shallower side converts first, importing the
  other side's class (`StudioViewEditor`) `TYPE_CHECKING`-only and
  relative (same-addon), `cast()` at each of the 4 real
  `self.env["studio.view.editor"]` lookups, never `typed.model()`.
  `studio_view_editor.py` itself (2960 lines, 74 `@api.model` methods --
  the largest, most RPC-heavy file in the whole suite) stays unconverted
  and out of scope; its own inferred (unannotated) return types are
  accepted as-is on the calls this file makes into it. Three new
  file-local `TypedDict`s (`HistoryEntryJSON`, `UndoRedoEntryJSON`,
  `StackForJSON`) for its three distinct RPC wire shapes.

  **`studio_automation.py`/`studio_security_surface.py`** (85/105 lines,
  `app_builder_ui`) and **`studio_report.py`** (260 lines,
  `app_builder_report`) all wrap Odoo's own `ir.actions.act_window` list
  view in a scoped, package-aware action dict -- three near-identical but
  independently-defined, file-local `TypedDict`s
  (`AutomationActionJSON`/`SecuritySurfaceActionJSON`/`ReportActionJSON`),
  deliberately not unified into one shared cross-addon type for this
  batch (no such shared helper existed before, confirmed by grep, and
  three addons each owning their own action shape is the existing
  pattern, not a gap this pass should close unprompted).
  `studio_report.py` additionally found and fixed a new instance of the
  `_inherit`-mixin-invisible-to-pyright gap on a *core* Odoo class rather
  than one of this project's own: `IrActionsReport.name` is declared on
  `ir.actions.actions`, which core itself composes only via
  `_inherit = 'ir.actions.actions'` -- fixed with
  `cast("IrActions", report).name`, same shape as every other `_inherit`
  gap this migration has already fixed, just the first one found on a
  core model rather than a `studio.*` one.

  **`tier_formula_serializer.py`** (`app_builder_approval_formula`) and
  **`mail_serializers.py`** (`app_builder_mail`) both independently
  discovered, while converting, that `typed.serializer_super()`
  (added earlier this phase, see above) **never actually type-checks at
  any real call site** -- pyright only infers a bare `super()` call's
  static type as the builtin `super` type when it is chained directly
  into attribute access (`super().attr`); passed as a plain argument to
  another function, as `serializer_super(super())` necessarily does,
  pyright instead infers the synthesized concrete base class
  (`AbstractModel`), which does not satisfy `serializer_super`'s own
  declared `sup: super` parameter. Confirmed independently by both
  drafting agents and a third time by the verify agent with an isolated
  `reveal_type(super())` repro -- not a fluke of one file. There is no
  fix: no annotation says "whatever pyright infers for a bare `super()`
  passed as an argument," so the helper's whole premise cannot work,
  unlike every other gap `typed.py` fixes. Both files worked around it
  differently in the draft pass (one dropped the helper for a direct
  `cast("StudioSerializer", super())`, matching the 8 other already-
  converted serializer files that never used the helper in the first
  place; the other kept the helper but wrapped its argument in an extra
  `cast("super", super())`, a pattern used nowhere else) -- the verify
  agent flagged the inconsistency without picking a winner. Resolved in
  the main loop, not by an agent: converged `mail_serializers.py` onto
  the same direct-cast idiom, and **removed `serializer_super()` from
  `typed.py` entirely** -- a dead helper with zero working callers
  anywhere in the tree is worse than no helper, and the established,
  actually-working convention (`cast("StudioSerializer", super())`
  inline, no wrapper) already covers the same gap in every one of the 10
  files that needed it. `typed.py` now has three helpers
  (`model()`/`security()`/`serializer()`), not four.

  Note for a future pass, not acted on now: `typed.serializer()` (the
  plain `self`-cast helper, as opposed to the `super()` one just
  removed) is *not* broken the same way -- `self` really is a `BaseModel`
  at every call site, so pyright has no trouble with it -- but it also
  has zero real callers today; every one of the 5 real `self`-cast sites
  across the serializer files uses `cast("StudioSerializer", self)`
  inline instead of the helper. Worth a deliberate decision later
  (adopt the helper everywhere, or remove it too for the same reason
  `serializer_super()` was removed) rather than a default either way.

  This closes Phase 1c wave 2 in full.

- **Wave 3** (9 files across 5 addons, converted as one batch -- 8 draft
  agents in a pipeline plus a dedicated 9th for the one big file, then
  two parallel verify agents, one per batch): `studio_model_draft.py`/
  `studio_security_surfaces.py` (`app_builder_base`), `studio_package_model
  .py` (`app_builder_view` -- the pure-`_inherit`-extension file, a
  different Python class from the already-converted `app_builder_base`
  one of the identical name), `studio_graduate_code.py`/
  `studio_menu_surface.py`/`studio_owned.py` (`app_builder_ui`),
  `ir_actions_report.py`/`studio_report_surface.py` (`app_builder_report`),
  `studio_approval.py` (`app_builder_approval`). Full-tree `pyright`
  dropped from 2923 to 2741 (182 errors). `pyrightconfig.json`/
  `pyrightconfig.ci.json`/every addon's own `pyproject.toml` confirmed
  unchanged.

  **`studio_owned.py`** needed zero changes -- confirmed to be, on closer
  reading, *seven* (not the dependency map's five) zero-method
  `_inherit`-composition classes wiring `studio.owned.mixin`/
  `studio.captured.on.create` onto core models, with nothing for pyright
  to check. Same "if already clean, make no changes" call as
  `res_users.py` (wave 0).

  **`studio_package_model.py`** (`app_builder_view`) is a pure `_inherit
  = "studio.package.model"` extension with no `_name` of its own -- a
  new shape of the `_inherit`-invisibility gap: not a mixin's method on
  `self`, but a DIFFERENT file's `_name`-sharing class's own FIELDS
  (`source`/`model`/`package_id`, all declared in the real
  `StudioPackageModel` over in `app_builder_base`) being invisible to
  pyright on this file's own `self`. Fixed the same way every other
  `_inherit`-invisibility case in this migration is fixed --
  `cast("StudioPackageModelBase", self)` at each real read, the base
  class imported `TYPE_CHECKING`-only and aliased (this file's own class
  is *also* named `StudioPackageModel`, a real Python name collision
  otherwise). `action_compose()`'s own override legitimately widens the
  base's declared `-> NoReturn` to a real return type for the branch
  that actually returns -- no override-compatibility check fires for
  `_inherit`-only composition (the same confirmed-elsewhere deviation
  `_sort_key`'s widening relied on in wave 1).

  **`studio_report_surface.py`** (`app_builder_report`) hit the identical
  same-name collision one level further: it declares its own
  `class StudioReport` (`_name = "studio.report"`, `_inherit =
  ["studio.record.surface", "studio.report"]`), which the registry
  merges with the *other*, already-converted `class StudioReport` in
  the same addon's `studio_report.py` at the SAME `_name` -- two
  distinct Python classes, same name, same file's own import statement
  would collide. Fixed with an aliased import
  (`from .studio_report import StudioReport as StudioReportBase`),
  `cast("StudioReportBase", self)` wherever this file's own methods
  need the other class's `_template_of`/`create_report`.

  **`studio_security_surfaces.py`**, **`studio_menu_surface.py`** and
  **`studio_report_surface.py`** are this wave's three
  `studio.record.surface` subclasses (the base, `studio_record_surface
  .py`, converted in wave 2) -- the first real test of that base's own
  declared override contracts against real subclasses. All matched
  cleanly, with one new, reusable pattern: **TypedDict subclassing**,
  for the three `_row()`/`rows()` overrides that add MORE keys to every
  dict than the base's own closed `RecordRowJSON` declares (`title`/
  `perms` for access rows; `depth`/`parent_id`/`opens`/`highlight` for
  menu rows, which are also `wire.ts`'s own long-predicted widening,
  now finally backed by a real override; `view_id`/`report_name`/
  `patched` for report rows) -- `class MenuRowJSON(RecordRowJSON): ...`
  etc., each with a REAL (never `TYPE_CHECKING`-only) import of
  `RecordRowJSON`, since a `class X(Y):` statement executes at import
  time unlike a plain `cast()` target. `studio_menu_surface.py` also
  hit `wire.ts`'s already-documented `Reference` field trap
  (`record.action`) at real call sites for the first time in a Python
  file since `Environment.cr`/`.user` established the pattern.

  **`studio_model_draft.py`** (1043 -> 1276 lines, ~46 methods, the
  `TransientModel` behind the console's entire "add/edit a field, live"
  workflow) got the same dedicated draft-then-independently-verify
  treatment as `studio_package.py` and `studio_record_surface.py`
  before it, given its size and centrality -- a full side-by-side
  method-by-method behavioral read against the original, not a sampled
  diff review. Verified clean with no defects: every `self.env[...]`
  literal routed through `typed.model()`, all 10 real security-gate call
  sites routed through `typed.security(self)`, every new TypedDict
  spot-checked against its real literal-dict call sites.

  This closes Phase 1c wave 3 in full.

- **Wave 4**: `studio_view_editor.py` alone (`app_builder_view`, 2960 ->
  3888 lines, ~90 methods) -- by a wide margin the largest and most
  RPC-heavy file in the whole suite (74+ `@api.model` methods, the de
  facto RPC surface for the entire console), given the same dedicated
  draft-then-independently-verify treatment as `studio_package.py`/
  `studio_record_surface.py`/`studio_model_draft.py` before it, except
  the verify stage itself was split three ways (one agent per
  roughly-1000-line range of the ORIGINAL file, each doing a full
  method-by-method behavioral read against `git show HEAD:...` for its
  own range) rather than one agent attempting the whole 2960-line diff
  -- the file was simply too large for a single careful read to stay
  reliable, the same reasoning that splits a review into dimensions
  rather than one pass. All three ranges PASSED with zero real defects.
  Full-tree `pyright` dropped from 2741 to 2626 (115 errors, after the
  two main-loop fixes below).

  ~25 new module-level `TypedDict`s for the RPC surface, cross-checked
  against `wire.ts`/`types.ts` per the now-established practice -- three
  real, minor Python/TS discrepancies found and typed honestly to match
  the traced Python reality rather than silently following `wire.ts`
  (same judgment call `studio_record_surface.py` made first): `wire.ts`
  has `OperationResult.created_name` optional+nullable where the real
  Python body always sends it; `wire.ts`'s search-field entry never
  allows a null `name` where the real body's `node.get("name")`
  genuinely can be `None`; `wire.ts`'s `EditingContext.packages` is
  `unknown` where the real body always sends a precise
  `{id, name, writable}[]`. Worth tightening `wire.ts` to match, next
  time that file is touched -- not done here, out of a Python-only
  task's scope.

  **Two genuinely reverse-direction `_inherit` gaps**, a new shape this
  migration had not hit before: this file is the *base* three sibling
  files extend (`studio_report_ops.py`, `studio_view_canvas.py`,
  `studio_view_new_field.py`, none converted yet -- the wave 5 follow-
  up), but its own methods already call INTO methods those siblings
  declare (`canvas`, `_canvas_draft`, `_splice_pending`,
  `_drop_field_definition`, `_mint_anchor`, `_python_owner` -- and,
  reaching into a different sibling model entirely,
  `studio.model.draft`'s own not-yet-converted `app_builder_view`
  extension's `set_anchor`). Fixed with two local, narrow `Protocol`s
  (`_ComposedViewEditor`, `_DraftHandle`) declaring only the methods
  this file's own body actually calls -- the same "narrow, real-call-
  site-driven contract" spirit as `lxml_types.py`'s own `LxmlElement`,
  just scoped to one file since the real target classes do not exist
  yet. Once wave 5 converts those three sibling files, whoever does it
  should check whether these two local Protocols can be replaced by
  real casts to the (by-then-real) sibling classes, or whether they are
  worth keeping as the documented contract those files must satisfy --
  a decision for that pass, not pre-empted here.

  **Two real `lxml_types.py` gaps** the draft agent found and correctly
  declined to fix out-of-scope (flagged instead, with local Protocol
  workarounds, `_RootTreeElement`/`_SiblingElement`) -- `getroottree()`
  (`_locator_for`'s positional-path fallback) and `getprevious()`
  (`_own_label`'s walk back through unnamed siblings). Fixed for real in
  the main loop immediately after the workflow returned, the same way
  `ir_ui_view.py`'s own conversion once extended `.iter()`: added both
  to the shared `LxmlElement` Protocol (`getprevious`) plus a new
  `ElementTree` Protocol for `getroottree()`'s own return (the narrow
  slice `_locator_for` needs, just `.getpath()`), then simplified
  `studio_view_editor.py` to use them directly, deleting its own three
  local workaround classes (`_RootTree`/`_RootTreeElement`/
  `_SiblingElement` -- `_ComposedViewEditor`/`_DraftHandle` stay, since
  those two are the reverse-`_inherit` case above, not an
  `lxml_types.py` gap).

  **One real regression surfaced, not introduced, and fixed in the main
  loop**: typing `_assert_arch_version`/`_find_extension`/
  `_get_or_create_extension`'s own `view`/`base_view` parameters as the
  real `View` class (this file's own conversion) exposed a latent gap
  in `studio_view_edit.py`'s EARLIER conversion (wave 2): 5 call sites
  there pass `self.base_view_id` (a plain-string-comodel Many2one read,
  TYPING.md's own relational-field trap) straight through, uncast --
  which was silently accepted when the callee's own parameter was
  untyped, and became 5 real `reportArgumentType` errors the moment the
  callee gained a real declared type. Not a new bug introduced by this
  conversion; a pre-existing gap in `studio_view_edit.py`'s own earlier,
  narrower cast coverage that this file's own conversion made visible
  (the exact situation `typed.py`'s own docstring warns every
  `_inherit`/cross-file gap eventually surfaces once enough of the
  graph is typed). Fixed directly in the main loop with `cast("View",
  ...)` at each of the 5 sites, matching that file's own already-
  established idiom at its other call sites -- a one-line, zero-
  behavior-change fix, not deferred, since leaving a previously-clean
  file at 5 errors would have broken this migration's own standing
  invariant ("every file already converted stays at zero").

  This closes Phase 1c wave 4 in full.

- **Wave 5** (11 files, the last of the dependency map): the three
  `_inherit`-only extensions of `studio.view.editor`
  (`studio_report_ops.py`, `studio_view_canvas.py`,
  `studio_view_new_field.py`, all `app_builder_view`, converted in
  dependency order -- the first two independently, the third reading
  the second's real final signatures); `studio_workspace.py` (real base
  in `app_builder_base`, then its two tiny pure extensions in
  `app_builder_approval`/`app_builder_ui`, same base-then-extension
  order); and five independent files -- `studio_app_builder.py`
  (`app_builder_model`), `studio_report_preview.py` (`app_builder_report`),
  `studio_approval_surface.py` (`app_builder_approval`),
  `studio_automation_surface.py` (`app_builder_ui`), and
  `app_builder_view/models/studio_model_draft.py` (a pure `_inherit`
  extension of the already-converted `app_builder_base` file of the
  identical name). Full-tree `pyright` dropped from 2626 to 2283 (343
  errors -- the largest single-wave drop of this whole phase).
  `pyrightconfig.json`/`pyrightconfig.ci.json`/every addon's own
  `pyproject.toml` confirmed unchanged. **This closes Phase 1c's
  model-file conversion in full: all 46 files under `models/` across
  the 8 addons now carry `from __future__ import annotations`, except
  the two (`res_users.py`, `studio_owned.py`) confirmed to need zero
  changes.**

  Four more same-`_name`-collision fixes this wave (rule 7 in the
  workflow's own shared conventions, by now a fully routine pattern):
  `studio_approval_surface.py` against `studio_approval.py`'s own
  `StudioApproval`; `studio_automation_surface.py` against
  `studio_automation.py`'s own (small, wave-2) `StudioAutomation`;
  `app_builder_view/models/studio_model_draft.py` against
  `app_builder_base`'s own `StudioModelDraft`; and, doubled up in the
  view-editor trio, each of `studio_report_ops.py`/`studio_view_canvas
  .py`/`studio_view_new_field.py` against the real
  `studio_view_editor.py` base, with `studio_view_new_field.py`
  additionally aliasing `studio_view_canvas.py`'s own class for its
  calls into `canvas()`/`_field_definition()`.

  **One real, severe behavior regression found by the verify agent and
  fixed in the main loop, not by the drafting agent**: the converted
  `studio_view_new_field.py`'s `update_manual_field` silently dropped
  `package.studio_capture([record, record.selection_ids],
  write_files=True)` -- the original's very last statement before its
  return, and per `studio_package.py`'s own docstring "the single entry
  point every builder module calls after it changes something." Without
  it, editing a manual field's label/required/readonly/selection
  through the console's properties panel would still write the live
  database row but never touch the package's on-disk source -- a
  change that looks like it worked and silently vanishes on the next
  fresh install from that package. The verify agent traced this to a
  real, existing test (`test_a_manual_field_definition_can_be_changed`,
  `app_builder_view/tests/test_new_field.py:454`) that asserts exactly
  the dropped call's own effect, so this was not a hypothetical risk.
  Restored verbatim in the main loop (one line, `cast("IrModelSelection",
  ...)` added for the same relational-field-cast reason every other
  `.selection_ids` read in this file already needed) -- the one time
  this whole migration's "flag, don't fix, across a file-scope
  boundary" rule for a DRAFT agent finding something in ITS OWN file
  turned out to matter for real: a severe logic bug, not a style
  nitpick, is exactly the case that discipline exists to catch before
  it ships.

  **Two Protocol-workaround reconciliations**, done in the main loop
  right after the workflow returned, the same "fix the forward
  reference once the real target exists" move wave 4's own
  `lxml_types.py` extension made: `studio_view_editor.py`'s own local
  `_DraftHandle` Protocol (forward-declaring `set_anchor`) and
  `studio_view_canvas.py`'s own local `_DraftWithPendingAnchored`
  Protocol (forward-declaring `_pending_anchored`) both existed only
  because `app_builder_view/models/studio_model_draft.py` was not yet
  converted when wave 4 needed to call into it. Now that it is (this
  same wave), both Protocols were deleted and replaced with a real,
  aliased `TYPE_CHECKING`-only import of that file's own real
  `StudioModelDraft` class (`StudioModelDraftView`, avoiding the
  already-imported `app_builder_base` base class's identical name) --
  confirmed each real method's signature matches what the Protocol had
  declared before deleting it. `studio_view_editor.py`'s OTHER local
  Protocol, `_ComposedViewEditor` (covering `canvas`/`_canvas_draft`/
  `_splice_pending`/`_drop_field_definition`/`_mint_anchor`/
  `_python_owner`), was deliberately left as-is: it is not a stand-in
  for one not-yet-converted file, but a genuine architectural
  convenience for a `self` that legitimately needs methods from TWO
  different sibling files (`studio_view_canvas.py` and
  `studio_view_new_field.py`) in one cast -- both siblings are now
  real and converted, but collapsing one Protocol into two separate
  aliased casts would be a pure style change with no correctness
  benefit, out of this pass's own "annotate, don't refactor" mandate.

## Phase 1d -- tests

Kicked off after Phase 1c closed in full. Scope confirmed directly, not
assumed: 66 test files across 7 addons (`app_builder_mail` has none),
19,052 lines total -- bigger by line count than the entire Phase 1c
model sweep. The plan's own mandate (above, "1d. Tests") is
deliberately lighter than Phase 1c's: `basic` mode, no `ANN` rule
(already exempted tree-wide, `.ruff.toml`'s own `"*/tests/*" = ["ANN"]`,
set back in Phase 1a and never touched since), annotate only where it
helps the checker read `self.env` results. Confirmed by measurement,
not assumption: a full-tree `pyright` immediately after Phase 1c closed
showed **2270 of 2283 total errors were inside a `tests/` directory** --
the other 13 are the pre-existing, unrelated `__init__.py` re-export
warnings noted throughout this document. Every one of Phase 1c's ~48
model files is genuinely error-free; Phase 1d's error surface is the
whole remaining count.

**Every one of the 66 test files imports `StudioCase` from
`app_builder_base/tests/common.py`** (confirmed by grep, not assumed) --
the one shared fixture base the entire suite depends on, so it went
first, converted directly in the main loop rather than delegated (small
enough, 359 lines, and too foundational to risk a subagent's own
judgment calls propagating uncorrected into 63 other files' worth of
casts against its return types).

**Two new, general-purpose helpers**, both instances of the identical
"one unannotated function, an optional parameter silently switches
between two different real return shapes, pyright infers the union of
both regardless of which branch a given call actually takes" gap
`typed.model()`/`Environment.get`/`assertRaises` already established as
a recurring class of Odoo-vendor-stub problem, not three unrelated
ones:

- **`typed.ref(env, xml_id) -> BaseModel`** (`app_builder_base/tools
  /typed.py`, general-purpose, not test-only -- `Environment.ref`
  (`odoo/api.py`) can only return `None` on the `raise_if_not_found=
  False` path this helper does not expose; with the default `True` it
  always either returns a real record or raises, but pyright cannot see
  that without an overload, so every call anywhere sees `BaseModel |
  None`). Needed its own `# pyright: ignore[reportUnknownMemberType]`
  since `typed.py` lives under `tools/`'s own strict
  `executionEnvironment` and `Environment.ref` is itself unannotated,
  same shape as `compat.py`'s own `env[model]._fields` ignore.
- **`common.py`'s own `raises(case, exception) ->
  _AssertRaisesContext[_E]`** (test-only, so it lives here rather than
  in `typed.py`) -- Odoo's own `BaseCase.assertRaises` (`odoo/tests
  /common.py:507`) is one unannotated function that either calls a
  given callable and returns `None`, or (every real call in this suite)
  returns a context manager when no callable is given; pyright's
  inferred return type is the union of both branches regardless of the
  call, so every `with self.assertRaises(X) as caught:` in the suite
  reported `reportOptionalContextManager` (142 of the 2270 errors, the
  single largest non-`reportAttributeAccessIssue` bucket). Fixed with a
  genuinely elegant trick rather than a `cast()`: type the helper's own
  `case` parameter as the ANCESTOR `unittest.TestCase`, not
  `StudioCase`/`TransactionCase`. Typeshed's own `unittest.TestCase
  .assertRaises` is correctly overloaded for exactly this shape (no
  callable -> `_AssertRaisesContext[_E]`, never `None`); Python still
  dispatches `case.assertRaises` through `case`'s REAL class at runtime
  regardless of the parameter's static type (identical behavior for
  this call shape, Odoo's own override included), so calling through
  the ancestor type changes nothing about which method runs -- only
  which stub pyright reads to type the result. No `cast()` needed at
  all. Verified with an isolated probe before adopting it (a toy
  `OdooLikeBase`/`StudioCase` pair reproducing the exact shape), not
  assumed to work.

`common.py`'s own conversion: `make_package`/`make_user`/
`register_module`/`build_demo_content` all now return real types
(`StudioPackage`/`Users`/`Module`/`IrModel`) via `typed.model()`, so
every one of the other 63 test files calling e.g. `self.make_package(
...)` gets a correctly-typed `StudioPackage` back with **no change
needed in that calling file** for that specific call -- the same
leverage-multiplication reasoning that made `studio_record_surface.py`
worth its own dedicated pass in Phase 1c. Every single-dict
`.create(vals)` call restructured to assign to a `vals` local first,
then `# pyright: ignore[reportArgumentType]` on the `create(vals)` line
itself -- the established `@api.model_create_multi` stub-gap idiom, but
applied more carefully than some Phase 1c files did: pyright attributes
the diagnostic to the call's own line, which a trailing comment after a
multi-line dict literal's closing brace does NOT reliably land on (a
trap a couple of Phase 1c draft agents already hit and self-corrected
in earlier waves) -- assigning to a named local first sidesteps the
whole question. Full-tree `pyright` dropped from 2283 to 1978 (305
errors) from this one file's own conversion plus the two helpers --
confirming the leverage bet before spending it on the other 63 files.

**The remaining 63 files, one large batch**: 63 draft agents (one per
file, pipelined) plus 7 verify agents (one per addon, since a test
file's own imports/fixtures are addon-scoped) -- 70 agents total, the
largest single workflow this migration has run. Full-tree `pyright`
dropped from 1978 to 13 -- the 13 being the pre-existing, unrelated
`__init__.py` re-export warnings already noted throughout this
document, present since before this migration started and untouched by
any of it until the bonus cleanup below. **Every Python file in every
one of the 8 addons -- every model, every tool, every test -- is now
pyright- and ruff-clean.**

Six of seven addons' batches passed verification outright (`app_builder_
approval`, `app_builder_approval_formula`, `app_builder_model`,
`app_builder_ui`, `app_builder_view` clean from the start;
`app_builder_report`'s own verify agent found and fixed two same-addon-
imported-fully-qualified mistakes itself, `app_builder_ui`'s trimmed one
overlong inline comment). **One real, load-bearing regression** found
by the `app_builder_base` verify agent and fixed in the main loop, not
by any agent: `app_builder_base/tests/e2e/probe_reflection.py` and
`probe_console_apply.py`'s draft conversions both added unconditional
**module-top-level** imports of `odoo.addons.<this-repo's-own-addons>`
classes (needed for `typed.model()`), but these two scripts are
standalone e2e probes (`python probe_X.py -c odoo.conf -d <db>`, run by
`run_probes.sh`, never through `TransactionCase`) where
`odoo.addons.<name>` is only resolvable *after*
`odoo.tools.config.parse_config()` runs inside `main()` -- a
module-level import executes and crashes with `ModuleNotFoundError`
before `main()` ever runs. The verify agent didn't just infer this: it
reproduced the crash directly, both with a bare
`python3 -c "import odoo.addons.app_builder_base"` before `parse_config`
and by `runpy.run_path`-simulating each script's own real invocation.
`pyright` could not see this at all (its own `extraPaths` resolves the
same import through a separate, `parse_config`-oblivious mechanism) --
a class of bug entirely outside this migration's own tooling, caught
only because the verify agent went one step further than "does pyright
pass" and asked "does this script actually run."

Two sibling files in the SAME batch, `probe_reimport.py`/
`probe_scaffold.py`, already had this right -- deferring the same
imports to inside `main()`, after `parse_config()` -- and the fix for
the two broken files matched that established shape, with one added
wrinkle each: both `probe_reflection.py`'s `actual_reflection(env,
spec)` and `probe_console_apply.py`'s `form_view(env, model_name)` are
module-level helper functions (called *from* `main()`, but defined
outside it) that also need the deferred names, so a plain "move the
import into `main()`" would leave them with a `NameError` instead of a
`ModuleNotFoundError`. Fixed by importing locally inside each helper
function too -- the exact same pattern `probe_reflection.py`'s own
`expected_reflection()` already used for its own `modelspec` import,
sitting right next to the broken `actual_reflection()` the whole time.
Re-verified against a real `ast.parse()` (syntax) plus `pyright`/`ruff`
after the fix; the verify agent's own two other findings against these
same files (idiom usage, cast reasoning) were otherwise sound and
needed no further changes.

**Bonus tree-wide cleanup**, done in the main loop after the 70-agent
batch returned, going one step past Phase 1d's own stated scope since
it closed the very last gaps standing between the repo and a fully
clean `pyright`/`ruff` run: `app_builder_view/__init__.py` (one
function, `uninstall_hook`) and `app_builder_view/exceptions.py` (two
exception `__init__`s) had never been touched by any phase so far --
not `models/` (Phase 1c), not `tools/` (Phase 1b), not `tests/` (Phase
1d) -- so `.ruff.toml`'s `ANN` rule still fired on both. Annotated
directly (both tiny, self-contained, no idiom decisions needed beyond
what Phase 1c already established). Separately,
`app_builder_base/tools/__init__.py` and `app_builder_view/tools/
__init__.py` both re-export their own submodules (`from . import
catalogue` etc., so `from ..tools import catalogue` resolves elsewhere
in the tree) -- a legitimate, common Python pattern pyright's
`reportUnusedImport` cannot distinguish from a genuinely dead import
without an explicit `__all__`. Added one to each, listing exactly the
re-exported names -- the last 13 pyright errors in the entire tree,
gone.

**Final state, confirmed by direct measurement, not estimation**:
`(cd <repo root> && direnv exec . npx pyright)` → `0 errors, 9
warnings, 0 informations` (the 9 warnings are `reportUnusedExpression`
on `__manifest__.py` files -- Odoo's own bare-dict-literal manifest
convention, `.ruff.toml` already exempts these from `B018`/`ANN`, not
a gap to close). `direnv exec . ruff check .` → `All checks passed!`
tree-wide. `direnv exec . ruff format --diff .` → clean, all 172
files. `pyrightconfig.json`/`pyrightconfig.ci.json`/every addon's own
`pyproject.toml`/`.ruff.toml` all confirmed unchanged throughout both
Phase 1c and Phase 1d.

**This closes Phase 1c and Phase 1d in full.** Every Python file this
project owns -- `tools/`, `models/`, `tests/`, and the two small
top-level files the bonus cleanup caught -- type-checks and lints
clean under this migration's own "stage 1" standard-mode ratchet.
Remaining, per TYPING.md's own original plan: the rest of Phase 3
(docs, the final ratchet); Phase 1e (runtime enforcement) was decided and
built afterwards -- see its own section below. Phase 2
(TypeScript) was already complete before Phase 1c's model sweep began
-- see "Phase 2b is now complete" above; an earlier draft of this
paragraph wrongly called it unstarted.

## Phase 1e -- runtime enforcement (typeguard), decided and built

The plan left this "optional, late: cheap on pure functions, worthless on
ORM code; decide after 1c". Decided by measurement, not opinion: typeguard
4.6 was hooked onto every `tools/` module in both addons (not `typed.py` /
`lxml_types.py`, below) and the whole suite was run under it -- recording
rather than raising, so one run gave the complete picture. 893 tests, 0
failures, and **four unique violations**:

- **One real annotation defect.** `modelspec.spec_to_json(spec: ModelSpec)`
  is `asdict(spec)`, and the editor's draft calls it with a `FieldSpec` for
  every field row. The signature was too narrow; `studio_model_draft.py`
  carried two `# pyright: ignore[reportArgumentType]` (and a comment
  explaining that `modelspec.py` was "out of scope") to get past it.
  Phase 1c's agents had flagged those sites as "narrower-than-declared" and
  correctly left them; nothing could say whether the annotation or the
  calls were wrong until something checked what actually arrives. Widened
  to `ModelSpec | FieldSpec`, both ignores and the comment deleted, pyright
  clean.
- **Three from one test** that drives an annotated function outside its
  annotation on purpose: `test_the_default_resolver_does_not_guess` calls
  `view_options.groups_json("form")` with the default resolver, which leaves
  labels lazy (`OptionGroupJSON` says `str`; `view_options.py` already
  admits this in a comment), and asserts exactly that. Not bugs -- a
  documented, tested contract the annotation cannot express. Marked
  explicitly at the call (`with unchecked():`, `tests/common.py`) rather
  than excused globally, so every other use stays strictly checked.

No `TypeHintWarning`s, no cast-and-comment lies found in the ORM-facing
code -- which is the point of scoping it: `tools/` are pure functions over
dataclasses, dicts and strings, where a runtime check is cheap and true.
On ORM code the static type (`Users`, `StudioPackage`) is a claim
`typed.model()` makes with a `cast`, and checking it at run time would
only compare the cast with itself.

**What it costs to make typeguard agree with code written for a static
checker** (each was hit, not predicted):

- `typed.py`: `TypeVar("M", bound="BaseModel")` with `BaseModel` imported
  under `TYPE_CHECKING` -- typeguard resolves the bound when it checks a
  `type[M]` argument, so 720 tests died with `NameError`. `typed.py` is all
  casts and has nothing to check; excluded.
- `lxml_types.py`'s `LxmlElement`/`ElementTree` `Protocol`s: hand-written
  stand-ins for stubless lxml. typeguard checks a `Protocol` argument
  structurally, which needs the protocol's own `TYPE_CHECKING`-only
  annotations to resolve (`MutableMapping`, `Field`) -- and a real lxml
  element does not carry those declared attribute types anyway. A checker
  lookup function passes over any `Protocol` defined in this repo. It has
  to be inserted *ahead of* typeguard's own (`insert(0, ...)`); appended,
  as the docs example does, it is never consulted for a `Protocol`.
- `manifest.py`: `Manifest: TypeAlias = "dict[str, ManifestValue]"` is a
  quoted alias, and `Manifest | None` in an annotation is `str | None` to
  anything that evaluates it (typeguard, or `get_type_hints`). The alias
  was quoted for no reason -- `ManifestValue` is defined above it -- so it
  is unquoted. (`ManifestValue` itself is genuinely recursive and stays
  quoted; typeguard copes.)
- Unresolvable annotations are set to `ForwardRefPolicy.ERROR`: the default
  is a warning and a skipped check, which reads exactly like a passed one.

**How it is wired.** Off unless `APP_BUILDER_TYPEGUARD` is set.
`app_builder_base/__init__.py` installs the hook before importing `tools`
(typeguard rewrites a module as it loads, so there is no installing it
afterwards); `app_builder_base/_typeguard_hook.py` holds it. `typeguard` is
in `test-requirements.txt`, so `oca_install_addons` puts it in both
containers, and `test.yml` sets the variable for the OCB flavor only
(`matrix.typeguard`; the two images do not differ for this). Locally:
`APP_BUILDER_TYPEGUARD=1 odoo test app_builder_base`, with `typeguard`
installed in the env -- it is deliberately not in the devenv's own
dependencies. The `pyright` ignores on its three imports say why.

**A hook that silently is not installed passes every test.** So
`tests/test_typeguard.py` proves it: with the variable set, a call that
breaks a `tools/` annotation must raise `TypeCheckError` (without the hook,
the same call is a bare `TypeError` from `asdict`, so the class tells the
two apart); without it, the test skips and says why rather than passing.
Found on the first run that it was not even registered in
`tests/__init__.py` -- the suite count did not move -- which is the same
failure one level up. Both states were run for real: hook on, the proof
passes; hook off, it reports the skip. The full suite under the final hook
(raising, `ALL_ITEMS` collection checks): 893 tests, 0 failures, about the
same wall time as without it (235 s). Not yet run in the container, like the
rest of `test.yml`.

## Phase 3 -- enforcement

**CI's pyright config had silently drifted from local's.** With the
Python tree at zero errors, the first real question was whether CI's
`typecheck` job would actually go green -- it runs `npx pyright -p
pyrightconfig.ci.json` and fails on any error, so it cannot have passed
at any point while this migration's error count was in the thousands.
Diffing the two configs found `pyrightconfig.ci.json` (a standalone
copy) missing both the `tools/` strict `executionEnvironments` and the
explicit `reportPrivateUsage: "none"`. Measured rather than assumed:

- `reportPrivateUsage` is already `"none"` in `standard` mode, so its
  absence changed nothing -- CI's rule set, pointed at local paths,
  reports the same `0 errors, 9 warnings` local does.
- The missing environments were a real enforcement hole: a scratch
  `tools/` file with one unannotated function got **4 errors** under the
  local config and **0** under CI's. CI was checking `tools/` less
  strictly than every developer's own editor.

Fixed by making `pyrightconfig.ci.json` `extends` the local config,
overriding only `extraPaths`/`venvPath`/`venv`. Two things verified
before relying on that: `extends` carries `executionEnvironments` over
intact (the same scratch file gets the same 4 errors), and the inherited
environments resolve imports through the *child's* `extraPaths`, not the
parent's (pointing the child at a nonexistent path breaks resolution
inside `tools/` too). The earlier "CI configs are standalone, not
`extends`" rule below was decided for `tsconfig.ci.json`, where
`extends` would *replace* `compilerOptions.paths` and drop every
`@app_builder_*` alias -- for pyright, the replaced key is `extraPaths`,
which is exactly the key CI needs replaced. `tsconfig.ci.json` stays
standalone. Also ran `scripts/ci_addons_mirror.py` for real and pointed
a scratch config (CI rules, the real mirror, local Odoo tree standing in
for `/opt/odoo-venv`) at it: `0 errors`. Still not a run inside the
actual container.

**The TypeScript migration had broken the whole backend, and nothing in
its verification could see it.** Found while working out why eslint could
not be enforced (Known traps has that half): typing `_t` honestly
(`console/l10n.ts`, returning `Translated` = `string | String`) made `tsc`
flag the pane registrations whose `label: string` it now contradicted --
and every one of them turned out to have been *made* to satisfy that type
during Phase 2b by wrapping the label in `String(...)`, at module top
level. The original `.js` stored the lazy value (`label: _t("Changes")`).
`String()` of a lazy translation before translations load throws
(`translation error`), the throw escapes `odoo.define`, and the rest of
the asset bundle never runs. Measured, not inferred, by driving headless
Chrome over the DevTools protocol against the running dev server and
asking `odoo.loader` directly:

- at `HEAD`: `create_package_flow` failed to load, 1061 of the bundle's
  1186 modules registered, the other 125 -- `@web/main` and `@web/start`
  among them, plus modules of 20 other addons -- never defined; the page
  mounted no navbar and no action manager, `document.body.innerText` was
  empty. **Every backend page was blank.**
- after the fix: all 1188 modules defined and started, no loader errors,
  no console errors, the web client lands on Discuss.

Phase 2b's own verification was `tsc`/`eslint`/`prettier`, build
idempotence and a transpile-equivalence check comparing each module's
name and dependency list -- all static, none of them evaluates a module in
the order the browser does, and the tours and hoot suite were not run.
The hoot suite could not even have told anyone: at `HEAD` its whole run
aborts on the same error (through `app_builder_ui`'s `pane()` helper, which
did the `String()` one call deeper).

The fix restores the original runtime behavior and makes the types say
so. `PaneRegistration.label`, `FlowSpec.title`/`doneLabel` and
`FlowStep.label` are `Translated`; the 28 module-level `String(_t(...))`
calls across six files (the Changes/Home/Views panes, the create-package,
build-app, adopt-model and open-view flows) are plain `_t(...)` again, as
is `pane()`'s `String(label)`; the few readers that need a primitive
(`shell_model.ts:setTitle`, `options.ts`'s choices) stringify at read
time. Found with a TypeScript-API scan for coercions whose enclosing
chain has no function boundary, plus the same for local helpers called at
module load -- but the scan only follows one call deep, so the browser is
the actual check: the live probe above, all 17 tour tests across the 8
tour classes (`tour succeeded` from the browser for each, none skipped),
and the hoot suite, 106 tests.

Two more regressions from the same migration surfaced along the way:

- **`app_builder_ui` imported `app_builder_view` at runtime without
  depending on it.** Converting `automations_menu_item` routed its
  `useService` through `@app_builder_view/console/odoo`; installed
  without `app_builder_view`, the module is missing from the bundle and
  the Automations menu item never starts. It calls `@web`'s own
  `useService` again and takes the facade's overloads as a type (`import
  type` is erased from the emitted `.js`); `app_builder_ui` and
  `app_builder_approval` take `TranslateFn` the same way rather than
  importing `l10n.ts`. `test_assets.py` gains
  `test_no_runtime_import_from_an_addon_not_depended_on`, which reads
  every shipped `.js` against its addon's transitive manifest `depends`
  -- run against the committed `automations_menu_item.js`, it names
  exactly this import.
- **Three `console_model` hoot tests had been failing, hidden behind the
  crash.** The JS original mutated the shared mock in place
  (`model.orm.call = ...`), which the console and its draft both hold;
  the TypeScript version replaced the reference (`model.orm = {...}`), so
  the draft kept the default stub, which answers `{}` to `action_apply`
  -- a mocked refusal came back `ok: true`. Test-only; a `swapOrm`
  helper replaces both references at the four sites the original
  mutated.

**The whole Python suite, run for the first time since Phases 1c and 1d**
-- every model and test file had been retyped under static checks only:
all 9 addons on a fresh database (`-u` all nine, `--test-tags` one per
addon), 892 tests, `0 failed, 0 error(s)`, tours and hoot suite included.
Running it needed one environment fact worth keeping: with `--test-tags`
and *no* `-u`, Odoo 18 builds `at_install` suites for every module in the
graph (`loading.py`: `test_enable and (needs_update or not updating)`),
which imports `base_tier_validation`'s tests and fails on
`odoo_test_helper`, absent from this environment. `-u <our addons>` limits
collection to the addons being updated -- the same thing odoo-nix's own
`odoo test` command does.

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
