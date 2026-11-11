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
// Named apart from odoo-nix's managed `eslint.config.cjs`, which lints the JS.
// Enforced: the `eslint-ts` hook, on the manual stage, which typecheck.yml
// runs in the dev shell. Its findings
// were once blamed on typescript-eslint's program construction and set aside
// as spurious; a program built exactly the way `tsc -p` builds it, passed in
// through `parserOptions.programs`, reported the same findings. The cause
// was untyped vendor JS (`allowJs`, `checkJs: false`) carrying TypeScript's
// `error` type into our code without a diagnostic -- `_t` was most of it, and
// is typed at the boundary now (`console/l10n.ts`, likewise `user` and the
// bus in `console/odoo.ts`/`compat.ts`). TYPING.md, Known traps, has the
// account.
import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
    {
        ignores: [
            "node_modules/**",
            "**/static/lib/**",
            "**/static/description/**",
            "**/*.js",
            "**/*.cjs",
            "**/*.mjs",
            ".odoo-nix/**",
            ".devenv/**",
        ],
    },
    js.configs.recommended,
    ...tseslint.configs.recommendedTypeChecked,
    {
        languageOptions: {
            parserOptions: {
                project: ["tsconfig.json"],
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
            // `const { a, b, ...rest } = obj` is how a key is stripped from
            // an object; the stripped names are unused on purpose.
            "@typescript-eslint/no-unused-vars": ["error", { ignoreRestSiblings: true }],
        },
    },
    {
        // Test doubles implement the async service interfaces
        // (`orm.call`, `learnContext`, ...) with synchronous bodies; the
        // signature is dictated by the interface, so `async` without
        // `await` is the correct shape there, not a mistake.
        files: ["**/static/tests/**/*.ts"],
        rules: { "@typescript-eslint/require-await": "off" },
    }
);
