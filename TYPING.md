# Typing

How the Python and the TypeScript in this repository are typed, checked, built and
loaded today, and the traps that cost time finding.

This file is the current state. How it got here — the plan, its phases, the file-by-file
log of the conversion and the CI setup that preceded odoo-nix — is in
[TYPING_HISTORY.md](TYPING_HISTORY.md). Comments in the code that cite "TYPING.md, Phase
2c", "cluster 4 wave 1" or "Implemented so far" refer to sections of that history; the
ones that cite "Known traps" refer to the section of that name below.

## What is checked, and by what

| What                              | Tool                           | Configuration                                                    | Run it                      |
| --------------------------------- | ------------------------------ | ---------------------------------------------------------------- | --------------------------- |
| Python types                      | pyright                        | `pyrightconfig.json`                                             | `node_modules/.bin/pyright` |
| TypeScript types                  | `tsc --noEmit`                 | `tsconfig.json`, through `scripts/typecheck.mjs`                 | `npm run typecheck`         |
| Unsafe `any` at the Odoo boundary | typescript-eslint (type-aware) | `eslint.typescript.config.mjs`                                   | `npm run lint:ts`           |
| Python style and annotations      | ruff                           | `.ruff.toml`                                                     | `odoo-nix gate lint`        |
| Runtime types of `tools/`         | typeguard, during the tests    | `APP_BUILDER_TYPEGUARD=1` (set under `ODOO_NIX_CI`, `flake.nix`) | `odoo-nix gate test`        |

All of them need the dev shell (`nix develop --no-pure-eval`): pyright and tsc read
Odoo's own sources through `.odoo-nix/odoo`, the link the shell makes to the pinned OCB,
and pyright reads the shell's Python through `.venv`.

The three type checks are hooks on the **manual** stage of `.pre-commit-config.yaml`,
because the lint gate's shell has neither Odoo nor that Python. Run all three the way CI
does (`.github/workflows/typecheck.yml`):

```sh
prek run -c .pre-commit-config.yaml --hook-stage manual -a
```

### Python

- `pyrightconfig.json` is the whole configuration: `standard` mode for the addons, a
  strict bundle for every `tools/` package (odoo-free by design) and for `models/`, and
  `basic` for `tests/`. The comments in that file say which `reportUnknown*` rules are
  left off for `models/` and why.
- Every module starts with `from __future__ import annotations`; `Self`, `NotRequired`
  and friends come from `typing_extensions`, which each addon declares in
  `external_dependencies`.
- A relational field is declared as Odoo declares it, with no annotation, and `cast()`
  at the place it is read. `env["some.model"]` goes through
  `app_builder_base/tools/typed.py:model(env, Cls)`, which holds the one cast.
- What an RPC method returns is a `TypedDict`. Those are the wire contract (below).

### TypeScript

- `tsconfig.json` is strict (`strict`, `noUncheckedIndexedAccess`,
  `exactOptionalPropertyTypes`, `noImplicitOverride`,
  `noPropertyAccessFromIndexSignature`) and erasable-only (`verbatimModuleSyntax`,
  `isolatedModules`, `erasableSyntaxOnly`): no enums, namespaces or parameter
  properties, so the emitted `.js` is always the `.ts` with its types deleted.
- `allowJs` with `checkJs: false` lets tsc read Odoo's JavaScript through the `@web/*`
  path aliases and infer from it. A few vendored files opt into checking with
  `//@ts-check`; `scripts/typecheck.mjs` fails only on diagnostics in this repository's
  own files and counts the rest.
- The framework boundary is fenced in two files:
  `app_builder_view/static/src/console/odoo.ts` (typed facades for `useService`, `user`,
  the dialog, and the registry categories this code registers into) and
  `console/l10n.ts` (`_t`). Code imports from those, not from `@web/...` directly,
  wherever a facade exists.
- A component keeps both `interface Props` and `static props`: Owl validates the second
  at runtime, and the templates are outside tsc's reach either way.

## How the TypeScript is built

The compiled `.js` is **not committed**: `.gitignore` excludes
`app_builder*/static/{src,tests}/**/*.js`. Each addon with TypeScript has a
`package.json` whose `build` script runs esbuild over `static/**/*.ts` and writes each
`.js` beside its source; `watch` does the same continuously. esbuild erases types and
checks nothing. The output stays under `static/src` and `static/tests`, not a `dist`
directory, because Odoo's own transpiler still has to load each file as an
`@odoo-module` under the path its imports name.

- **In the dev shell** entering the shell installs and builds; `devenv up` keeps
  rebuilding; `odoo module build` builds by hand.
- **In production** `nix build .#default` runs the same builds through odoo-nix's addon
  frontends layer and lays the output into the deployed tree and the wheels.

`app_builder_base/tests/test_assets.py` runs Odoo's transpiler over every emitted file
and fails on a surviving top-level `import`/`export`, which is what esbuild leaves for a
module that had nothing but types in it.

## How it is loaded

Every asset is **named in its addon's manifest**; there are no globs. Since the `.js` is
ignored by git, a glob would also load the `.js` that a renamed or deleted `.ts` left on
a developer's disk. `app_builder_view/tests/test_asset_bundles.py` fails when a source
file is in no bundle, in two, or listed with no source — so adding a `.ts`, `.xml` or
`.scss` means adding a line to the manifest.

There are two bundles:

- **`web.assets_backend`** holds only what every internal user needs: the systray item,
  the cog-menu items, the two facades they import (`odoo.ts`, `l10n.ts`) and
  `console/console_loader.ts`.
- **`app_builder_view.assets_console`** holds the console: the shell, the panes, the
  canvas, and what `app_builder_model`, `app_builder_ui`, `app_builder_report` and
  `app_builder_approval` add to it. `console_loader.ts` registers the console's client
  action as a function that calls `loadBundle` and runs the action again, against the
  component `console.ts` registered when the bundle arrived.

A file in `web.assets_backend` must not import, at runtime, a module that is only in the
console's bundle; `import type` is fine, being erased. The same test reads the imports
and refuses it.

The hoot runner fetches nothing on demand, so `web.assets_unit_tests_setup` includes the
console's bundle. Tours need nothing special: they open the console the way a person
does, which loads it.

## The wire contract

What the server sends is typed twice: as `TypedDict`s in Python and as interfaces in
`app_builder_view/static/src/console/wire.ts`. The two are kept in step **by hand**.
`orm.call<T>` asserts a shape and checks nothing, so a field renamed on one side
type-checks on both and fails in the browser. The generator the original plan called for
(Phase 2d) was not built; until it is, change both sides in the same commit.

`app_builder_view/tests/test_wire_contract.py` is the check in between. It lists which
interface mirrors which `TypedDict`, compares their keys, and fails on an interface in
`wire.ts` it has not been told about, so a new one is either pinned to its `TypedDict`
or listed with the reason it has none. It compares keys only: a `str` that became an
`int` is still matched by eye.

## Supported Odoo versions

Only **18.0** is built and tested. The canvas reads Odoo's own DOM (`.o_cell`,
`.o_wrap_label`, `.o_notebook .nav-link`) and overrides controller hooks by name
(`beforeLeave`, `beforeUnload`, `canResequence*`); those are strings, so a refactor
upstream breaks them without a type error. They are gathered in `console/compat.ts` and
pinned by `static/tests/compat.test.ts` and `canvas_views.test.ts`, which is why the
hoot suite and the tours are worth running on every OCB bump.
[FORWARD_COMPAT.md](FORWARD_COMPAT.md) has the audit of 19.0 and master.

## Known traps, so they are not rediscovered

Some entries below were written while the conversion was under way and mention the CI
container or `scripts/build_ts.mjs` of that time; the trap each describes is in the
tool, not in that setup, and still applies.

- `export {};` from type-only modules -> `test_assets.py` (Phase 0). Type-only modules
  should be `.d.ts` anyway (`wire.d.ts`).
- `@odoo/owl`'s npm version trails the vendored `owl.js`, which OCB patches ahead of the
  npm tag (`2.8.4` in the vendored file, `2.8.3` the latest ever published) -- pin the
  npm package to whatever is actually published, not what the vendored file's own
  `version` constant says, and expect the two to disagree. Re-check both when bumping
  OCB series.
- Two of Odoo's own core files opt into per-file checking with a `//@ts-check` pragma
  (`model/relational_model/{relational_model, dynamic_group_list}.js`, as of this OCB
  checkout), which **overrides** the project's `checkJs: false` for that file alone -- a
  documented but easy-to-forget TS behavior. Anything that imports `@web/views/view`
  (nearly everything here) pulls these in transitively via `allowJs`, so `tsc --noEmit`
  reports their pre-existing errors as if they were ours. `scripts/typecheck.mjs` groups
  tsc's output into diagnostic blocks and drops every block whose file path leaves this
  repo (always via a `../` path-alias hop) -- not a path allowlist, a "did tsc have to
  leave this repo to find it" test. Re-run `npm run typecheck` after any OCB bump to
  confirm the split still holds; a new `//@ts-check` file inside a path this repo _does_
  own would need a different fix.
- Odoo's own ambient `@types/*.d.ts` files are not all safe to bulk `include`:
  `services.d.ts` and most of `@types/registries/*.d.ts` exist specifically to `import`
  real service/registry _implementation_ modules and take their type with `typeof` --
  which pulls those real `.js` files into the program too. `tsconfig.json`'s own
  `include` comment has the current, authoritative list and why each entry is there (it
  has grown past the original "pure types only" rule as real files needed more --
  `views_registry.d.ts`/`fields_registry.d.ts` for `ViewsRegistryItemShape`/
  `FieldsRegistryItemShape`, `fields.d.ts` for the field-definition types those need);
  do not duplicate that list here where it will go stale. `useService`/`services`
  (`services.d.ts` itself) still gets its own narrow, hand-written facade instead (Phase
  2c), never Odoo's auto-generated one -- that one cascade really is the whole
  webclient, unlike a single view/field descriptor shape.
- No `owl.d.ts` in `include`, on either tsconfig: `@odoo/owl` is a real npm dependency
  (`package.json: types`) that resolves on its own, and OCB's ambient re-export of it
  (`declare module "@odoo/owl" { export * from "@odoo/owl/dist/types/owl"; }`) does not
  survive `moduleResolution: bundler` resolving its own wildcard `exports` subpath -- it
  silently resolves to nothing and shadows the real package's types with an empty
  ambient module. Symptom: `Module '"@odoo/owl"' has no exported member 'Component'` (or
  anything else real) the moment a file actually needs a named export from it, with no
  hint that the ambient file is the cause. Confirmed by removing it and watching the
  error disappear -- if it ever needs to come back for a different reason, re-test that
  resolution first.
- **Never coerce a `_t(...)` value while a module body is running** (`String(_t(...))`,
  a template literal, `+`, `.trim()` -- anything that calls its `toString`). Odoo's
  module loader starts every non-lazy module the moment it is defined, while the asset
  bundle is still being evaluated; translations only arrive later, when the web client's
  `localization` service starts. Until then `_t` returns a `LazyTranslatedString`, whose
  `toString` _throws_ `translation error`. The throw escapes `odoo.define`, which the
  bundle calls at its top level, so it aborts **the rest of the bundle**: on the live
  dev server this took 126 modules with it, `@web/main`/`@web/start` included -- every
  backend page rendered blank. Keep module-load values lazy (the `Translated` type,
  `console/l10n.ts`) and stringify where they are read. `tsc` cannot see this; the tours
  and the hoot suite do (Phase 3, below).
- eslint's `no-unsafe-*` findings were real, not a tooling bug. The earlier entry here
  (and `eslint.config.mjs`'s own comment) blamed typescript-eslint's program
  construction for "spurious" findings; a program built exactly the way `tsc -p` builds
  it, handed to eslint through `parserOptions.programs`, reported the identical 245. The
  actual cause: untyped vendor JS (`allowJs`, `checkJs: false`) can carry TypeScript's
  `error` type -- `translation.js`'s own JSDoc names `Markup`/`LazyTranslatedString`,
  types that file never declares, so `_t`'s whole return type collapses to `error` --
  and `checkJs: false` suppresses the diagnostic that would have said so. `tsc` then
  reports nothing, because an `any` flowing into typed code is legal; the `no-unsafe-*`
  rules exist precisely to flag it. `_t` alone accounted for 154 of ~200. Typed at the
  boundary now -- `_t` in `console/l10n.ts`, `user.hasGroup` in `console/odoo.ts`, the
  RPC bus in `console/compat.ts`, hoot's `MockServer.env` per test file -- and the last
  51 findings (event bus, `user.hasGroup`, `JSON.parse`, mock-server handles, three
  `Translated`-in-a-template sites, two dead declarations) are gone. **eslint is
  enforced: 0 findings**, via the `eslint-ts` pre-commit hook and a `typecheck`-job step
  (`TSC_PROJECT=tsconfig.ci.json`, `eslint. config.mjs` reads it). Two config choices,
  both reasoned rather than reflexive: `no-unused-vars` ignores rest-siblings
  (`const { a, ...rest }` is how a key is stripped from an object), and `require-await`
  is off under `static/tests/` (test doubles implement the async service interfaces with
  synchronous bodies). The CI step has not run in the container, like the rest of that
  job. When eslint and `tsc` disagree, check the type the checker actually resolves
  (`checker.getTypeAtLocation`, `type.intrinsicName === "error"`) before calling either
  one wrong.
- **Typed relational fields (`field: Cls = fields.Many2one("model")`, TYPING.md's own
  Phase 1c plan text) do not actually type-check, for any of
  `Many2one`/`One2many`/`Many2many` -- superseded by the finding below, once a real
  model file (`builder_package.py`) tried it.** Two independent, compounding failures,
  both confirmed with isolated probes (with and without
  `fields.Many2one[Cls](...)`-style explicit subscripting, neither fixes either
  failure): the _declaration_ itself fails
  (`Many2one[Cls]`/`One2many[Cls]`/`Many2many[Cls]`, the constructed field-descriptor
  instance's own type, is never assignable to the declared attribute type `Cls` -- not a
  descriptor-protocol special case pyright applies to a class-body assignment); and
  `_Relational.__get__` (`odoo/fields.py`) carries no return annotation of its own, so
  every _read_ of the field independently infers a messy, partially-`Unknown` union
  regardless of the declaration. `odoo/odoo/modules/module.py`'s own
  `TYPED_FIELD_DEFINITION_RE` (originally cited as proof this syntax works) is Odoo's
  own source-_scanning_ tool for a different purpose entirely, not a type-checker --
  citing it as confirmation was an unverified assumption that the first real attempt
  broke. Fix, the new house convention: leave the field declaration exactly as it was
  (no LHS annotation, no subscript, `from __future__ import annotations` still present
  as usual), and `cast("Cls", record.field_name)` at each real _read_ site instead --
  the same idiom `pycodegen.py` already established in Phase 1b for a
  plain-string-comodel relational field (`record.selection_ids`).
  `TYPE_CHECKING`-guarded imports for the comodel class are still exactly right; only
  the declaration's own annotation is dropped. Confirmed to recur immediately one level
  deeper too: `IrModelFields.model_id`/`IrModelSelection.field_id` (core Odoo's own
  plain-string-comodel relational fields) hit the identical gap the moment this file
  read them.
- Same-addon cross-file imports (real or `TYPE_CHECKING`) must stay **relative**
  (`.builder_package_apply`, `..tools.lxml_types`), never the fully-qualified
  `odoo.addons.app_builder_base....` form -- this repo is reachable under two different
  pyright module identities at once (`app_builder_base.*` via `pyrightconfig.json`'s own
  `include`; `odoo.addons.app_builder_base.*` via `extraPaths`' merged odoo-nix tree,
  which mirrors this same repo). Importing a same-addon name absolutely analyzes it
  under the _other_ identity than this file's own relative `..tools` imports use, so two
  types that print identically (confirmed with `ModelSpec`, imported both ways at once)
  are NOT the same type to pyright, and every call passing one where the other is
  expected fails. The fully-qualified `odoo.addons....` form stays correct, and is the
  only option, for genuinely external repos reached only through the merged tree
  (`base`, `web`, ...) -- `pycodegen.py`'s own `IrModel`/`IrModelFields` imports,
  already landed, are exactly that case and need no change.
- `app_builder_base/tools/typed.py`'s `model(env, cls)` needs a real, runtime-bound
  `cls` (it reads `cls._name` at runtime) -- it cannot be called with a class imported
  only under `TYPE_CHECKING` (a real `NameError` at runtime, not just a type error). Two
  real model classes with a genuine circular reference (`BuilderPackage` <->
  `BuilderPackageApply`/`BuilderPackageModel`, see the dependency map in "Implemented so
  far") therefore cannot use `typed.model()` for each other while only one side of the
  cycle is converted -- `cast("TheOther Class", self.env["the.other.model"])` against
  the unchanged original call is the right fix for exactly this circular case, leaving
  `typed.model()` for every reference that is either non-circular or a core-Odoo lookup.
- `self._assert_builder_manager()`/`self._assert_builder_user()`/
  `self._assert_builder_group(...)` (`builder_security.py`'s own guard methods, "called
  first in every builder method reachable over RPC" per its own docstring) are invisible
  to pyright on every real caller: every `builder.*` model that composes
  `builder.security.mixin` does so through Odoo's own registry-level
  `_inherit = ["builder.security .mixin"]`, never a literal Python base class, so
  nothing in the class's own MRO carries those methods as far as the type checker can
  see. `builder_package.py` alone needed
  `cast("BuilderSecurityMixin", self)._assert_builder_manager()`/`._assert_builder_user()`
  at 8 call sites. Given `builder_security.py`'s own docstring, this will recur in
  nearly every remaining Phase 1c model file -- worth a shared `typed.py` helper (e.g.
  `def security(self: BaseModel) -> BuilderSecurityMixin: return cast("BuilderSecurityMixin", self)`)
  once a second file confirms the same shape, rather than building it from this one
  file's evidence alone.
- `fields.Selection([...])`'s own inline-list form hits a real, pre-existing (confirmed
  against the untyped original too, not introduced by this migration) vendor-stub gap:
  `Selection.__init__`'s own `selection` parameter (`odoo/fields.py`) carries no
  annotation at all, only a bare `SENTINEL` default, so pyright infers the parameter's
  effective type from that default alone and rejects the field's own normal
  `list[(value, label)]` literal form. Fix: a narrow
  `# pyright: ignore[reportArgumentType]` on the declaration line, one per inline
  `Selection([...])` list -- likely to recur in every model file with one.
- `@api.model_create_multi` (`odoo/api.py`) is a bare passthrough decorator
  (`def model_create_multi(method: T) -> T`) that does not widen `create()`'s own
  declared `list[ValuesType]`-only signature to also cover the single-dict calling form
  it genuinely accepts at runtime (the decorator wraps a lone dict into `[vals]`, calls
  the real method, and unwraps the result back to one record) -- the same shape of
  decorator-stub gap already documented for `@tools.ormcache`. Fix: a narrow
  `# pyright: ignore[reportArgumentType]` at each `create({...})` call site, keeping the
  exact original single-dict call rather than rewriting it to `create([{...}])` --
  changing the argument shape actually passed at runtime is outside a typing-only pass's
  mandate, however harmless that particular rewrite would likely be.
- `Environment.cr` is declared `BaseCursor` (`odoo/api.py`), which has no
  `.execute`/`.commit` of its own -- those live only on the real `Cursor` subclass every
  live request actually gets. The same shape of "declared type too abstract for what is
  really there at runtime" gap already documented for `Environment.user`. Fix:
  `cast("Cursor", self.env.cr)` at each real call site (raw SQL via `.execute()`, an
  explicit `.commit()`) -- `Cursor` importable `TYPE_CHECKING`-only from `odoo.sql_db`.
- The `_inherit`-mixin-invisible-to-pyright pattern (above) recurs identically for
  `super()`, not only `self`: a subclass overriding a `builder.serializer` method and
  calling `super()._should_skip(...)` (to extend rather than fully replace the base
  behavior) fails with `Cannot access attribute "..." for class "object"` the moment the
  class's own real Python base is _only_ `models.AbstractModel` -- confirmed as a
  genuine, pre-existing pyright error against the untyped original in
  `base_automation_serializer.py`, not introduced by typing it.
  `app_builder_base/tools/typed.py` now carries the matching pair for
  `builder.serializer` specifically: `serializer(self)` (the `self`-side fix, mirroring
  `security()`) and `serializer_super(sup)` (the `super()`-side fix, `cast()` on the
  proxy object itself -- a documented runtime no-op, so the real MRO dispatch `super()`
  performs is unchanged). Confirmed recurring across at least three of wave 1's own
  files before the helpers existed to use.
- A field reached only through Odoo's `_inherits`/`delegate=True` mechanism (e.g.
  `ir.cron.model_id`/`.name`, delegated from `ir_actions_server_id`) is not resolvable
  by casting `record` to the real, concrete delegating class either -- the attribute is
  never declared in that class's own Python body, so pyright cannot see it there any
  more than it can see it on the generic `BaseModel`. Different from the
  `_inherit`-mixin trap above (there, a real composing class exists to cast to; here,
  none does). Fix: `cast("Any", record)` at the one read site, honest about there being
  no real class in this codebase's own tree that actually carries the attribute. Likely
  to recur for any other `_inherits`/`delegate=True` chain (most of `ir.actions.*`'s own
  delegation hierarchy uses the same mechanism).
- `fields.Reference(...)` (and, by the same construction, any other `Field` subclass
  with no `__get__` override of its own) inherits its read type from its base descriptor
  class rather than what it actually returns at runtime -- `ir.ui.menu.action`, a core
  `Reference` field, reads back as `str | Literal[False]` (`Reference` extends
  `Selection`, `Selection(Field[str | Literal[False]])`) instead of the real recordset
  `Reference.convert_to_record` produces. The same shape as the already-documented
  `Environment.cr`/`Environment.user` "declared type too abstract for what's really
  there" gap, just not previously called out for `Reference` specifically. Fix: `cast`
  at the read site to the honest type (`BaseModel` here, since the target model varies
  per record) -- no behavior change.
- `app_builder_base/tools/lxml_types.py`'s `LxmlElement.iter()` was declared
  zero-argument (every prior reader only ever walked the whole subtree) -- extended to
  `iter(self, tag: str | None = None)` the moment a real reader (`ir_ui_view.py`'s
  `node.iter("button")`) needed lxml's real tag-filtered form. Real lxml also accepts
  `*tags` (multiple tag names/wildcards); narrowed to the one-tag form actually called
  anywhere in this codebase rather than the fuller variadic signature nothing yet needs
  -- extend further only once a second real reader needs it, the same "narrow, extend on
  real need" discipline this Protocol has followed since Phase 1b.
- `BuilderSerializer._sort_key`'s own base declaration (`-> tuple[int, str]`) was too
  narrow the moment real subclass overrides existed -- every one of wave 1's own five
  overrides returns a wider, differently -shaped tuple (`(int, int, str)`,
  `(int, int, int, str)`, `(int, bool, str)`, `(int, int, str, str)`), each a real,
  deliberate tie-break, and none of them trip `reportIncompatibleMethodOverride` (that
  check only fires across a real Python base-class relationship, confirmed empirically
  -- `_inherit`-only composition is invisible to it the same way it's invisible to
  everything else in this trap list). Widened the base to
  `tuple[int | str | bool, ...]`, the honest common shape every real override already
  satisfies without its own divergent annotation -- the same "downstream evidence
  corrects an earlier, too-narrow base signature" move already made once for
  `BuilderSerializer._for_model` (wave 0's own `BaseModel | None` narrowed to
  `BuilderSerializer | None`). `builder_package.py`'s own two local dict types
  (`buckets`/ `csv_rows` in `_render_files`) needed the identical widening, since they
  store `_sort_key`'s return value directly -- the only real caller, and it never
  indexes into the tuple, only compares/sorts by it whole, so the widening cost it
  nothing.
- `Field[T]` gives `str | Literal[False]` for `Char` -- under strict, every
  `record.name` needs narrowing. That is the ORM's real contract; the `tools/` boundary
  should take `str`, not `str | False`, and models narrow before calling.
- A dataclass field typed `str` that is actually built from `_lt(...)` (`LazyGettext`)
  throughout its real call sites is not a hypothetical -- it is what `catalogue.py`'s
  `Row.label` etc. turned out to be (see "Implemented so far"). Before trusting a
  plain-looking field type in `tools/`, grep every constructor call, not just the file's
  own defaults.
- pyright over the merged 906-addon tree: keep `include` to the addon repo; the tree is
  `extraPaths` only, loaded on import.
- OCA CI is py3.10 while the workspace is 3.11: run pyright with
  `pythonVersion = "3.10"` so 3.11-only syntax fails locally, not in CI.
- The OCA CI container's addon layout (`oca_install_addons`) is not the odoo-nix
  workspace layout `tsconfig.json`/`pyrightconfig.json`'s relative paths assume -- see
  "CI: the OCA container's real layout" above for the CI-specific configs and the mirror
  script that cover the difference. Don't assume the `pre-commit.yml` `SKIP=` treatment
  generalizes to `test.yml` without checking a container's own layout directly, the way
  that section did.
- Any script under `scripts/` has to run on Node 20, not just whatever local dev happens
  to have (odoo-nix pins `nodejs_22`): the OCA CI container's Node comes from jammy's
  nodesource package, pinned at 20. `fs.globSync` (Node 22+) is the one this already
  caught (`scripts/build_ts.mjs`, rewritten to `readdirSync(..., { recursive: true })`,
  stable since 20.1); check any new Node API the same way before relying on it.
- Reading a nullable `this.<field>` again after a null-check loses the narrowing the
  moment any method/function call runs in between, even though the field itself was
  never reassigned -- distinct from the repeated-bracket-index trap above (that one is
  about index-signature/ array reads, this one about instance properties and plain
  variables). `Boolean(a && b)` has the identical problem for a free function's own
  parameters: it does not narrow `a`/`b` for what follows, since `Boolean(...)` is an
  opaque call as far as control-flow analysis goes, same as any other function
  reference. Fix every time: capture the narrowed value into a local `const` right after
  the check, before anything else runs, or (for the `Boolean(a && b)` shape
  specifically) rewrite as an early `if (!a || !b) return ...;` guard instead
  (`drag.ts`: `onDragStart`, `watchRow`/`rowAt`, `teardown`; `samePlace`).
- TS interface extension requires an _overriding_ property to be narrower than (or equal
  to) what it overrides, never wider -- so `interface B extends A { x: T | null }` does
  not compile if `A.x: T` (no `| null`). When a "resolved" shape and a "stored" shape
  genuinely need to disagree on a field's nullability (a resolver's own defaulting can
  produce `null`; nothing that builds the stored shape ever writes a literal `null`),
  the fix is one shared, wider type on _both_ interfaces rather than fighting the
  extension direction (`pane_registry.ts`'s `PaneRegistration`/`PaneEntry`,
  `makeModel`).
- A category name registered with Odoo's generic `Registry` (`registry.category(name)`)
  does not compile unless `name` is a known key of `GlobalRegistryCategories`
  (`registries.d.ts`) -- core's own categories (`views`, `fields`, ...) get this via a
  `.d.ts` under `@types/registries/`; a category this repo invents (`app_builder.panes`)
  needs the identical
  `declare module "registries" { interface GlobalRegistryCategories { "the.category": ItemShape } }`
  augmentation, legal from any real `.ts` module, not only a `.d.ts` -- put it in the
  one file that creates the category until Phase 2c's `console/odoo.ts` facade exists to
  hold it instead (`pane_registry.ts`).
- **Owl components, four facts cluster 4 (the first real components converted)
  established, all confirmed directly against
  `node_modules/@odoo/owl/dist/types/runtime/component.d.ts` rather than guessed:**
  - `override` is needed for _any_ class member sharing a name with one declared in
    `Component`'s own class body -- `static template` (required, `string`),
    `static props`/`static defaultProps` (both optional) and the instance method
    `setup(): void` all four need it. An earlier framing of this rule as "needed because
    the base member is optional" is imprecise (two independent agents caught and
    corrected it identically): `template` is _required_ and still needs `override`.
    `static components` needs _no_ `override` because it is not a `Component` class-body
    member at all -- it lives on the separate
    `StaticComponentProperties`/`ComponentConstructor` types Owl's registry/`xml`
    machinery uses instead.
  - Owl components initialize fields in `setup()`, called synchronously right after
    construction, never in a constructor this code writes its own. TS's
    `strictPropertyInitialization` only inspects a real constructor, so it cannot see
    that `setup()` always runs first -- every field `setup()` unconditionally assigns
    (even to a literal `null`/`false`) needs a definite-assignment assertion
    (`field!: T`); a field only ever assigned later, in a lifecycle method like
    `attach()`, is instead typed `T | undefined` with no assertion, since that genuinely
    is its state before that method first runs.
  - `typeof Component` (Owl's bare, unparameterized component-class type) is **not**
    assignable from a concrete `Props`-parameterized subclass, in either direction:
    assigning a real component class to a field/parameter typed `typeof Component` fails
    ("Two different types with this name exist, but they are unrelated" -- contravariant
    constructor-parameter checking against the generic `new <Props=any,Env=any>(...)`
    signature). Fix: write the field as `typeof Component<any, any>` instead of the bare
    form, with an `eslint-disable-next-line @typescript-eslint/no-explicit-any` on that
    line -- confirmed with a standalone probe before applying it tree-wide, to every
    registry-item-shape field that names a component class
    (`PaneRegistration.Component`/`.sidebar`, `PaneResolverResult.Component`/`.sidebar`,
    `CogMenuItem.Component`, `SystrayRegistryItemShape.Component`,
    `ViewWidgetsRegistryItemShape.component`, `fieldEditorComponent()`'s own return
    type) and to `odoo.ts`'s new `"app_builder.field_editor"` category entry.
  - `ev.target` is `EventTarget | null`, not `Element` -- the JS idiom
    `target.closest && target.closest(...)` (checking whether `.closest` exists at all)
    does not translate, since `EventTarget` has no `.closest` property, not even an
    optional one. Fix:
    `const target = ev.target instanceof Element ? ev.target : null;`, then plain
    `target && target.closest(...)` from there.
- A vendor `.js` component class with no `@extends {Component<Props>}` JSDoc (e.g.
  `@web/core/confirmation_dialog/confirmation_dialog.js`) does not carry `Component`'s
  own instance members into TS's inferred type at all under this project's
  `checkJs: false` -- `InstanceType<typeof ConfirmationDialog>` has no
  `.render`/`.props`/`.env`, confirmed with a standalone probe (the identical class,
  declared directly in a `.ts` file instead, infers correctly). Surfaces as
  `DialogService.add` rejecting the vendor class against _any_ `Component<P>`
  instantiation, `P = any` included, with the confusing message "is missing the
  following properties from type 'Component<...>': props, env, **owl**, render". Not
  fixable by widening `P` -- the vendor class itself is what fails the structural check.
  Fix: a narrow, hand-typed re-export of the vendor class, cast once
  (`ConfirmationDialogImpl as unknown as new (...args: any[]) => Component<ConfirmationDialogProps>`),
  the same "narrow, hand-traced facade over a vendor boundary" move `odoo.ts` already
  makes for `OrmService`/`NotificationService`/`ActionService` -- every real caller then
  imports the typed re-export from `odoo.ts` instead of the vendor module directly.
- `Domain.toList(context)` (`@web/core/domain.js`) is JSDoc'd with `context` unbracketed
  (`@param {Object} context`, meaning required), and TS enforces that -- but plenty of
  real vendor callers (`field.js`, `utils.js`, several in `search_model.js`) call it
  with zero arguments anyway. The same JSDoc-vs-runtime looseness already tracked for
  `Registry.get`/`queryFirst`/`useDragAndDrop`/`moveTo`, now on a
  required-vs-effectively-optional parameter rather than an arity or shape mismatch. Fix
  at the call site: pass `{}` explicitly, the same "evaluate without context" idiom
  `domain.js`'s own `toJson()` uses internally.
- `querySelector`/`querySelectorAll` infer their default, non-generic return type as the
  DOM lib's own `Element`, which has no `.click()` -- a real gap only surfaces once a
  real caller needs a DOM method `Element` does not have (`identity.ts`'s
  `tabFor`/`findTab`, both genuinely always finding a `<a class="nav-link">`, widened to
  `HTMLElement` with an explicit `querySelector<HTMLElement>(...)` once `canvas.ts`
  needed `.click()` on what they return). A test written against the old, wider return
  type may need a matching `as HTMLElement` at its own comparison site
  (`identity.test.ts`), since `@odoo/hoot-dom`'s own `queryOne` stays the plain,
  non-generic `Element` it has always been (see cluster-3's own `drag.test.ts` finding
  on this).
- `ReturnType<typeof _t>` used to be `any` (the vendor `error` type, see above), which
  is why unioning it with anything tripped `no-redundant-type-constituents`. `_t` is
  imported from `console/l10n.ts` now and returns `Translated` (`string | String`), so
  `ReturnType<typeof _t>` is that union too.
- `usePopover`'s own `open(target, props)` (`@web/core/popover/ popover_hook.js`)
  forwards `props` to the popover service unchanged -- neither it nor `Popover` itself
  injects a `close` into the _rendered_ component's own props (`Popover`'s own `close`
  prop is for its click-away/escape chrome, not forwarded into `componentProps`), unlike
  `DialogService.add`, which does inject one. A component meant to be opened through
  `usePopover` that unconditionally calls `this.props.close()`
  (`field_editor_fallback.ts`'s own `onKeydown`, on Escape) is relying on something no
  real opener in this tree actually supplies -- a real, pre-existing gap, not introduced
  by this migration and not fixed by it (flag, don't fix). The type-level fix at each
  real opener: `Omit<FieldEditorProps, "close">` for the props object, not the full
  shape.
- `field(default_factory=list)`/`field(default_factory=dict)` (dataclasses) infer
  `list[Unknown]`/`dict[Unknown, Unknown]` even when the field's own annotation says
  `list[SomeClass]`/`dict[K, V]` -- pyright does not propagate the field's declared type
  into the zero-arg factory's own return type. Fix:
  `field(default_factory=list[SomeClass])` / `field(default_factory=dict[K, V])` -- the
  parametrized generic itself a real, callable, zero-arg factory at runtime (Python
  3.9+), behaviorally identical to the bare form (confirmed both by pyright, 0 errors,
  and by actually running it: `Term().occurrences == []`). Hit twice independently in
  the same wave (`pogen.py`'s `Term.occurrences`, `canvas_stamp.py`'s
  `StampResult.nodes`/`.elements`), so treated as a general trap rather than a one-off.
- lxml ships no type stubs in this environment (a compiled extension with no
  `.pyi`/`py.typed` marker; `lxml-stubs`/`types-lxml` is not an installed dependency
  here) -- `from lxml import etree` alone reports both `reportMissingTypeStubs` and
  `reportAttributeAccessIssue`. The obvious rewrite, `import lxml.etree as etree`,
  trades this for a worse problem: ruff's own `PLR0402` (`fix = true` project-wide)
  silently auto-fixes it straight back to the broken `from lxml import etree` form on
  every save. Fix: keep `from lxml import (etree,)`, with
  `# pyright: ignore[reportMissingTypeStubs]` on the `from lxml import (` line and
  `# pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]` on the
  `etree,` line -- both required, both on those exact physical lines (confirmed a
  `# pyright: ignore` on a _preceding_ comment line does not suppress the diagnostic
  below it). For the element type itself, `app_builder_base/tools/lxml_types.py`'s
  `LxmlElement` is the one shared, hand-traced `Protocol` every real `tools/` reader
  imports rather than re-declaring -- three independent local copies existed briefly
  before being reconciled into it (see "Implemented so far").
- `BaseModel.sorted(self, key=None, reverse=False)` (`odoo/models.py`) carries no type
  annotation at all on `key` in the merged tree, so a lambda passed as
  `some_recordset.sorted(key=lambda r: ...)` has no context to infer its own parameter's
  type from and reports fully `Unknown` throughout (the lambda's parameter, its return,
  and every attribute read inside its body). Fix: a small, separately-defined,
  explicitly-annotated function in place of the inline lambda -- the function's own
  signature needs no inference, so the same `reveal_type`-confirmed field reads it
  already relied on stay exactly as typed (`pycodegen.py`'s `_selection_sort_key`,
  replacing `record.selection_ids.sorted(key=lambda s: (s.sequence, s.value))`).
  `.sorted` itself still needs a narrow `# pyright: ignore[reportUnknownMemberType]` at
  the call site when the recordset it's called on is itself only reachable via a `cast`
  (see the next trap) -- a separate diagnostic, about the method reference's own
  partially-unknown signature, not about the `key` argument.
- Five attributes of `ir.model.fields` (`IrModelFields`, in the merged tree's
  `odoo/addons/base/models/ir_model.py`) -- `.ttype`, `.relation`, `.relation_table`,
  `.column1`, `.column2` -- read back as `str | bool` under pyright
  (`.column1`/`.column2` additionally carry a genuine `Unknown` component:
  `str | Unknown | bool`) instead of the `str | Literal[False]` every other
  `Char`/`Selection` field on that same real class gets (confirmed clean on ten
  siblings: `.name`, `.field_description`, `.help`, `.related`, `.domain`, `.on_delete`,
  `.currency_field`, `.compute`, `.depends`, `.relation_field`). Confirmed by direct
  `reveal_type` probe, and confirmed it is not about the field _name_: a synthetic
  `models.Model` declared inline with identically-named `Char` fields (`relation`,
  `column1`, `ttype`) infers the expected `str | Literal[False]` every time. Traced as
  far as `Many2many.relation`/`.column1`/`.column2` (`odoo/fields.py`) being unrelated
  class attributes of the _field descriptor_ class itself (e.g.
  `relation = None  # name of table`) that happen to share these exact names with real
  `IrModelFields` columns -- the only coincidental overlap found, not a conclusively
  confirmed root cause, so worth re-checking if it resurfaces elsewhere rather than
  assumed solved. Fix, since a real row only ever holds a `str` (or the empty-string/
  `False` "unset" spelling any `Char` field can have) at these five attributes, never a
  real `bool`: `cast("str", record.<attr>)` at each read, with a
  `# pyright: ignore[reportUnknownMemberType]` alongside the two (`column1`/`column2`)
  whose source expression also carries the genuine `Unknown` component the cast alone
  doesn't silence (`pycodegen.py`'s `_field_spec_from_record`). The same file's own
  `record.selection_ids` (a
  `fields.One2many("ir.model.fields .selection", "field_id", ...)`, a plain string
  comodel with none of OCB's typed-relation syntax) hits the same shape of gap one level
  up -- pyright cannot resolve the element type from the declaration at all and falls
  back to `M@_Relational | list[Unknown] | list[Unknown | bool]`, with `.sorted`
  unresolved on two of the three arms -- fixed the same way,
  `cast("IrModelSelection", record.selection_ids)` plus the matching ignore.
- `Environment._` (`odoo/api.py`) -- the translation callable every real caller knows as
  `env._(...)`/`self.env._(...)` -- has its `source` parameter annotated
  (`str | LazyGettext`) but its `*args`/`**kwargs` are not, in the merged tree;
  confirmed directly with `reveal_type`. Every real call site
  (`env._("...", key=value)`, `env._("...", positional)`) therefore reads as
  `reportUnknownMemberType` under this project's strict `tools/` execution environment.
  Fix: `# pyright: ignore[reportUnknownMemberType]` at each call site (21 in
  `manualfield.py`, the first file in this migration to call `env._` directly rather
  than only pass it as a value). This will very likely recur in most Phase 1c model
  files, which call `self.env._(...)` constantly -- worth deciding then whether the
  house convention stays "ignore at every call site" or a single typed wrapper (e.g.
  `def translate(env: api.Environment, source: str, *args: object, **kwargs: object) -> str: return env._(source, *args, **kwargs)`)
  is worth introducing to avoid dozens of near-duplicate ignores per file. **Confirmed,
  first Phase 1c file (`builder_security.py`): the plain module-level `_`
  (`from odoo import _`, i.e. `odoo.tools.translate .get_text_alias`) has the identical
  gap** -- `reveal_type` shows `(source: str, ...) -> str`, the same
  unannotated-`*args`/`**kwargs` shape, under a file-scoped strict-equivalent
  `executionEnvironment` probe. Given how pervasive plain `_("...")` calls are (every
  translatable string in every model file), fixing this per call site was deliberately
  deferred rather than solved on file 1 -- see the new "two-stage ratchet" note below;
  revisit once several more model files confirm the same scale of recurrence, the same
  "promote only once a real, cross-file pattern is confirmed" discipline `lxml_types.py`
  was built under.
- A method decorated with `@tools.ormcache(...)` (e.g. `IrModel._get_id`) reads as
  `() -> ((...) -> Any)` under pyright, not its real signature -- confirmed with
  `reveal_type` and traced to the installed `decorator` package's own stub
  (`decorator/__init__.pyi`), which types
  `decorator(caller, _func=None, kwsyntax=False)`'s return as unconditionally
  `Callable[[Callable[..., Any]], Callable[..., Any]]` even when `_func` is supplied the
  way `ormcache.__call__` actually calls it (`decorator(self.lookup, method)`,
  `odoo/tools/cache.py`) -- a real stub-vs-runtime gap in a third-party stub, not this
  codebase's to fix. Fix: a narrow `# pyright: ignore[reportCallIssue]` at each call
  site of an `@ormcache(...)`-decorated method called directly (rather than through a
  plain, undecorated wrapper) -- `manualfield.py`'s `IrModel._get_id(relation)`. Likely
  to recur anywhere else in this codebase that calls an
  `@ormcache`/`@tools.ormcache`-decorated ORM method directly.
- A `dict[str, Callable[..., T]]` registry built from inline lambda values reports
  `reportUnknownLambdaType` on every lambda parameter under strict mode, regardless of
  the dict's own declared value type -- a lambda's parameter cannot carry an annotation
  at all (a Python syntax limit), and pyright does not infer one from the surrounding
  dict literal's declared type either. The same underlying gap as
  `.sorted(key =lambda ...)` above, just a second manifestation of it (a dict literal
  rather than a single keyword argument). Fix, identical in shape: small,
  separately-defined, explicitly-annotated named functions in place of the inline
  lambdas (`scaffold.py`'s `SCAFFOLD_BUILDERS`, nine `_build_*` functions replacing nine
  lambdas).
- `Environment.user` (`odoo/api.py`) carries no return annotation of its own; pyright
  infers one from its body (`self(su=True)['res.users'] .browse(self.uid)`), which
  bottoms out at the bare `BaseModel` every `Environment.__getitem__` call returns --
  the same untyped hole `typed.model()` exists for, but `self.env.user` is an
  _already-obtained record_, not a model _name_ to turn into a handle, so
  `typed.model()` doesn't apply here (it would return an empty `res.users` recordset,
  not the current user's own record). Fix: a direct, narrow
  `cast("Users", self.env.user)` at the point of use, `Users` imported
  `TYPE_CHECKING`-only from `odoo.addons.base.models.res_users` (`builder_security.py`'s
  `_assert_builder_group`). Cast inline inside a boolean expression rather than into a
  variable above it, when the original code short-circuited around the property read --
  `self.env.user` is cheap and side-effect-free (`browse` never queries), but preserving
  the exact original evaluation order costs nothing and removes any doubt about a
  behavior change. Likely to recur anywhere else `self.env.user`'s own methods/fields
  (not just `.id`/`.login`, which `BaseModel` doesn't have either) are read directly.
- **Two-stage ratchet for `models/`, discovered on the first Phase 1c file.** The plan's
  own text says "`# pyright: strict` at the top the moment a file passes;
  `reportUnknownMemberType`-class rules on last" -- tested literally on
  `builder_security.py` via a temporary file-scoped `executionEnvironment` probe (same
  individual-rule mechanism `tools/` uses, not a bare `# pyright: strict` comment, per
  the composition trap already documented in "Where it starts from"/1a). Result:
  escalating a file to the full strict-equivalent rule bundle immediately surfaces
  `odoo._`'s own unannotated-varargs gap (see above) -- confirming the plan's own
  instinct that `reportUnknownMemberType`-class rules need to come _after_ something,
  not immediately per-file. Rather than solve that infrastructure question (a shared
  translation wrapper, or blanket per-call-site ignores) off a single file's evidence,
  **Phase 1c's own stage 1 is: full annotations (signatures, `Self`, typed relational
  fields, `typed.model()`/direct casts for the ORM's own untyped holes) verified clean
  under this project's existing top-level `standard` mode plus the `ANN`/`TC`/etc. ruff
  rules -- no per-file strict escalation yet.** Stage 2 (flipping on the
  strict-equivalent bundle, file by file or in bigger groups) is deferred until enough
  files have gone through stage 1 to see the real, cross-file shape of "every `Any` OCB
  leaks" (translation calls being the first confirmed one) rather than guessing at
  shared infrastructure from one data point -- the same "promote only once a real
  pattern is confirmed across readers" discipline `lxml_types.py` was built under.
  **Confirmed on the second Phase 1c file (`builder_serializer.py`): under `models/`'s
  current top-level standard-mode config, `record._fields[fname]`-class reads already
  resolve with _zero_ pyright errors even with no cast/ignore at all**
  (`reportUnknownVariableType`/`reportUnknownMemberType` are strict-only rules, off by
  default in standard mode) -- the narrow `# pyright: ignore[...]` idiom
  `compat.py`/`manualfield.py` established is therefore not load-bearing in `models/`
  _yet_, unlike in `tools/` where its own `executionEnvironment` already enables those
  rules. Kept anyway, everywhere this pattern recurs, so the idiom is already in place,
  byte-identical to `tools/`'s own, the day stage 2 turns those rules on -- confirmed
  the ignore comment itself causes no `reportUnnecessaryTypeIgnoreComment` complaint or
  other diagnostic when the named rule isn't actually firing, so carrying it early is
  free.
- `Environment.get(...)` (inherited, unparameterized `Mapping.get` -- `Environment`
  itself never overrides `get`, only `__getitem__`/ `__contains__`) returns
  `Unknown | None`, confirmed with `reveal_type` -- a _different_ untyped hole from
  `Environment.__getitem__`'s own (which `typed.py`'s `model()` helper exists for):
  `.get()`'s real contract is `BaseModel | None` (`None` on a model-name miss, instead
  of `__getitem__`'s KeyError-on-miss shape). Handled narrowly, by annotating the _call
  site's_ own return type rather than a new shared helper (`builder_serializer.py`'s
  `_for_model`, its only caller so far) -- the same "promote only once a pattern recurs"
  discipline as above; revisit once a second `models/` file calls `env.get(...)` the
  same way.
- `Field.default`'s pyright-inferred type, for any field carrying a callable default, is
  the alarming-looking `((model: Unknown) -> Never) | None` rather than the honest
  `Callable[[BaseModel], object] | None` -- confirmed with `reveal_type` against the
  real merged tree, traced to a self-referential-narrowing artifact inside OCB's own
  `Field.__init__` (`odoo/fields.py`; `self.default` is narrowed against itself earlier
  in the same method, before the `lambda model: value` branch that actually sets it).
  Not a bug in this codebase, not fixable from this side, and confirmed zero practical
  effect: `Never` is a bottom type, so code that calls the callable and uses its result
  (`builder_serializer.py`'s own `_should_skip`) round-trips clean regardless, with no
  cast needed. Recorded so a future reader does not re-derive this from a
  frightening-looking `reveal_type` result.
- A module-level `TypeAlias` built directly from another module's exported type (e.g.
  `Element: TypeAlias = LxmlElement`, re-exporting `lxml_types.py`'s own `LxmlElement`
  under a locally-conventional name) needs its source import at real, top-level scope --
  `TYPE_CHECKING`- guarding it trips ruff's `TC004` ("move import out of type-checking
  block: used for more than typing"), since the assignment itself runs at import time,
  not only inside deferred annotations the way a bare type-only usage would. Only the
  _alias assignment itself_ needs the real import; every place the alias is then _used_
  (a parameter/return annotation) is still deferred as normal by
  `from __future__ import annotations`, exactly like any other name.
