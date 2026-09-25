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
// Not yet enforced (no pre-commit hook, no CI step) -- but its findings
// are real. They were once blamed on typescript-eslint's program
// construction; a program built exactly the way `tsc -p` builds it,
// passed in through `parserOptions.programs`, reports the same findings.
// The cause is untyped vendor JS (`allowJs`, `checkJs: false`) carrying
// TypeScript's `error` type into our code without a diagnostic -- `_t`
// was most of it, and is typed at the boundary now (`console/l10n.ts`).
// TYPING.md, Known traps, has the account and what remains.
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
