// TYPING.md, Phase 2c: lint with typescript-eslint's `no-unsafe-*` rules so
// an `any` leaking in from Odoo's own untyped JS (via allowJs) shows up at
// the boundary that let it in, rather than spreading silently through
// everything downstream -- the TS-side equivalent of pyright's
// `reportUnknown*` family on the Python side.
//
// Scoped to this repo's own `.ts` sources only (`tsconfig.json`'s own
// `include`, not a glob over the whole tree): the point is catching an
// unsafe boundary *we* wrote, not re-litigating vendored JS we don't own
// and that `scripts/typecheck.mjs` already treats as out of scope.
// KNOWN BROKEN for now -- read this before trusting a "no-unsafe-*"
// finding from this config. typescript-eslint's own program construction
// (tried: `project` as a relative string, `project` as an absolute path,
// `projectService: true` -- all three, same result) fails to resolve
// tsconfig.json's ambient `registries`/`@odoo/owl` module declarations,
// which are literal (non-glob) `include` entries reaching outside this
// directory via `../../odoo/...`. Every file that touches a type from
// one of those (`ViewsRegistryItemShape`, `Component`, ...) then reports
// spurious `no-unsafe-*` findings on code that `npm run typecheck` (the
// real, enforced checker -- `tsc -p tsconfig.json`) and the TypeScript
// compiler API's own `getParsedCommandLineOfConfigFile` (what `tsc -p`
// itself calls) both pass cleanly. Confirmed narrowly: calling
// `ts.parseJsonConfigFileContent` directly with a *relative* base path
// (`.`) silently drops those same `include` entries; an absolute one, or
// the higher-level `getParsedCommandLineOfConfigFile`, does not.
// typescript-eslint's parser evidently still hits the relative-basePath
// path somewhere internal to it, which none of the public parserOptions
// change. Not yet filed upstream. Until this is fixed (or narrowed down
// further), eslint is NOT wired into the pre-commit hooks or CI
// typecheck job -- see TYPING.md, Known traps.
import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
    {
        ignores: [
            "node_modules/**",
            "**/static/lib/**",
            "**/static/description/**",
            "**/*.js",
        ],
    },
    js.configs.recommended,
    ...tseslint.configs.recommendedTypeChecked,
    {
        languageOptions: {
            parserOptions: {
                projectService: true,
                tsconfigRootDir: import.meta.dirname,
            },
        },
        rules: {
            // The five rules TYPING.md names explicitly.
            "@typescript-eslint/no-unsafe-argument": "error",
            "@typescript-eslint/no-unsafe-assignment": "error",
            "@typescript-eslint/no-unsafe-call": "error",
            "@typescript-eslint/no-unsafe-member-access": "error",
            "@typescript-eslint/no-unsafe-return": "error",
            // verbatimModuleSyntax (tsconfig.json) already forces `import
            // type` where tsc can prove it -- this rule is the reverse
            // direction (catching a value import that could have been
            // type-only) and would just duplicate that enforcement.
            "@typescript-eslint/consistent-type-imports": "off",
        },
    }
);
