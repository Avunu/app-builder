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
  `esbuild`, `@odoo/owl@2.8.4` (types only -- must match the vendored Owl),
  `prettier`, `typescript-eslint`. `npm ci` in the shell hook.
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
  stale `.js` or `wire.d.ts` cannot be committed. In the pre-commit CI job
  (no Odoo checkout) skip the checker hooks via `SKIP=`; run them in a
  `typecheck` job inside the OCB container in `test.yml`, where
  `import odoo` resolves and node is present.
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
- `@odoo/owl` npm version must track the vendored `owl.js` (`2.8.4` now);
  pin exactly and note it in `FORWARD_COMPAT.md`.
- Typed relational fields + circular imports: annotation syntax +
  `from __future__ import annotations`, never `fields.Many2one[Cls]` (that
  evaluates at import).
- `Field[T]` gives `str | Literal[False]` for `Char` -- under strict, every
  `record.name` needs narrowing. That is the ORM's real contract; the
  `tools/` boundary should take `str`, not `str | False`, and models
  narrow before calling.
- pyright over the merged 906-addon tree: keep `include` to the addon
  repo; the tree is `extraPaths` only, loaded on import.
- OCA CI is py3.10 while the workspace is 3.11: run pyright with
  `pythonVersion = "3.10"` so 3.11-only syntax fails locally, not in CI.

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
