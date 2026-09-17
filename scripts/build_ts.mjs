#!/usr/bin/env node
/**
 * Emit every `.ts` source under an addon's `static/src` or `static/tests`
 * tree as a sibling `.js`, committed alongside it (TYPING.md, decision 3).
 *
 * esbuild does one thing tsc's own `--outDir` cannot: transform in place,
 * next to JS sources that are still part of the same directory tree,
 * without tsc refusing to emit because JS inputs are in the program (tsc
 * is still what type-checks -- `npm run typecheck` / `scripts/typecheck.mjs`
 * -- this script only strips types). Each file is transformed
 * independently, matching `tsconfig.json`'s `isolatedModules: true`: no
 * step here needs to see more than one file at a time, which is what lets
 * a single `git mv foo.js foo.ts` be the whole diff for converting one
 * module.
 *
 * The emitted `.js` is exactly the `.ts` with types erased -- no bundling,
 * no import rewriting -- so it goes through
 * `odoo.tools.js_transpiler.transpile_javascript` unchanged, the same as
 * before conversion (verified in TYPING.md's spike). `erasableSyntaxOnly`
 * in tsconfig.json keeps that true: no enum, namespace or parameter
 * property could ever need real emitted code, only deletion.
 */

import { context, build } from "esbuild";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const watch = process.argv.includes("--watch");

// `fs.globSync` needs Node 22; the OCA CI container (test.yml's
// `typecheck` job) ships Node 20 (jammy's nodesource package, per the
// Dockerfile this was checked against). Plain `readdirSync(...,
// { recursive: true })` (relative path strings, no Dirent) needs only
// Node 20.1+, comfortably inside that. Walked per addon's own
// `static/src`/`static/tests` -- never from the repo root, which would
// also recurse through node_modules for no reason.
const entryPoints = readdirSync(repoRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name.startsWith("app_builder"))
    .flatMap((addon) =>
        ["static/src", "static/tests"].flatMap((sub) => {
            const dir = path.join(repoRoot, addon.name, sub);
            if (!existsSync(dir)) {
                return [];
            }
            return readdirSync(dir, { recursive: true })
                // `.d.ts` matches `.endsWith(".ts")` too, but a pure
                // ambient declaration has no runtime code to emit --
                // esbuild would still happily turn one into an empty
                // `.d.js`, a nonsense extension pairing that shipped once
                // (`hoot-mock.d.ts`) before this exclusion existed.
                .filter((relative) => relative.endsWith(".ts") && !relative.endsWith(".d.ts"))
                .map((relative) => path.join(dir, relative));
        })
    );

if (entryPoints.length === 0) {
    console.log("build_ts: no .ts sources yet.");
    process.exit(0);
}

const options = {
    entryPoints,
    outbase: repoRoot,
    outdir: repoRoot,
    // One output file per input, next to it -- never bundled: every
    // console module already resolves its own siblings by Odoo's own
    // module system (odoo.define/@web path aliases) at runtime, and
    // bundling would duplicate what the asset pipeline already does.
    bundle: false,
    format: "esm",
    target: "es2022",
    // The runtime is Odoo's JS module loader, not Node or a browser
    // <script type=module> -- charset/legalComments only affect readability
    // of the committed .js, which a human reviews like any other diff.
    charset: "utf8",
    legalComments: "inline",
};

if (watch) {
    const ctx = await context(options);
    await ctx.watch();
    console.log("build_ts: watching for changes...");
} else {
    // `write: false` so a pre-commit run can tell "nothing to do" from
    // "the committed .js was stale" -- the same shape as `ruff --fix`:
    // write the correction, but fail so the commit picks up the new
    // file instead of silently shipping the .ts/.js pair out of sync.
    const result = await build({ ...options, write: false });
    for (const warning of result.warnings) {
        console.warn(warning);
    }
    let changed = 0;
    for (const file of result.outputFiles) {
        const previous = (() => {
            try {
                return readFileSync(file.path, "utf8");
            } catch {
                return null;
            }
        })();
        if (previous !== file.text) {
            writeFileSync(file.path, file.text);
            changed += 1;
        }
    }
    if (changed > 0) {
        console.error(
            `build_ts: ${changed} file(s) were stale and have been regenerated -- ` +
                `stage them and commit again.`
        );
        process.exit(1);
    }
    console.log(`build_ts: ${entryPoints.length} file(s) already up to date.`);
}
