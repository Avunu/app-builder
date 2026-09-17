#!/usr/bin/env node
/**
 * `tsc --noEmit` over this repo, but failing only on diagnostics anchored
 * in this repo's own sources.
 *
 * `allowJs` pulls in Odoo core's real .js sources through the `@web/*`
 * etc. path aliases -- needed for `checkJs: false` to still infer types
 * from them (a facade calling `useService("orm")` has to see what `orm`
 * actually returns). tsc reports diagnostics for those files too whenever
 * a vendored file opts into per-file checking with a `//@ts-check`
 * pragma, which overrides our project-level `checkJs: false` (two files
 * do this today: `model/relational_model/{relational_model,
 * dynamic_group_list}.js`; see TYPING.md, "Known traps"). Those errors are
 * real, but they are not ours to fix, and failing the build on vendored
 * code we do not own would make every future OCB bump a typecheck outage
 * we cannot resolve from this repo.
 *
 * "Ours" is anything tsc resolves to a path inside this repo's own
 * directory, checked by actually resolving each reported path against
 * this file's directory -- not by pattern-matching a leading "../", which
 * only holds for tsconfig.json's *relative* `@web/*` aliases. In CI
 * (`TSC_PROJECT=tsconfig.ci.json`, TYPING.md) those aliases point at the
 * container's absolute `/opt/odoo/addons/*` instead, which tsc reports
 * as-is, with no leading ".." to match.
 */

import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repoRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
// TYPING.md: local dev uses tsconfig.json (the default tsc picks up on its
// own); the OCA CI container's typecheck job sets this to point at
// tsconfig.ci.json instead, whose `@web/*` etc. resolve to the
// container's absolute /opt/odoo/addons rather than a relative ../../odoo.
const project = process.env.TSC_PROJECT ?? "tsconfig.json";

const result = spawnSync(
  process.platform === "win32" ? "npx.cmd" : "npx",
  ["tsc", "-p", project, "--noEmit", "--pretty", "false"],
  { cwd: repoRoot, encoding: "utf8" }
);

const output = `${result.stdout ?? ""}${result.stderr ?? ""}`;
const lines = output.split("\n");

// A new diagnostic starts at column 0 with "<path>(<line>,<col>): error ...";
// everything else (blank lines, indented "Type '...' is not assignable..."
// detail) belongs to the block above it.
const DIAGNOSTIC_START = /^(\S.*)\(\d+,\d+\): error /;

const blocks = [];
for (const line of lines) {
  const match = DIAGNOSTIC_START.exec(line);
  if (match) {
    blocks.push({ file: match[1], lines: [line] });
  } else if (blocks.length > 0) {
    blocks.at(-1).lines.push(line);
  } else if (line.trim()) {
    // Output before any recognized diagnostic (e.g. a fatal config error).
    console.error(line);
  }
}

// path.relative(repoRoot, X) starts with ".." exactly when X lies outside
// repoRoot -- true whether tsc reported X as a relative "../../odoo/..."
// (local dev) or an absolute "/opt/odoo/..." (CI): both resolve() to the
// same real path either way, so one check covers both configs.
const isOurs = (file) => !path.relative(repoRoot, path.resolve(repoRoot, file)).startsWith("..");
const vendored = blocks.filter((b) => !isOurs(b.file));
const ours = blocks.filter((b) => isOurs(b.file));

if (vendored.length > 0) {
  console.error(
    `tsc: ignoring ${vendored.length} diagnostic(s) in vendored Odoo source ` +
      `outside this repo (reached via a path alias, not something we can fix here)`
  );
}

if (ours.length > 0) {
  for (const block of ours) {
    console.error(block.lines.join("\n").trimEnd());
  }
  console.error(`\ntsc: ${ours.length} error(s) in this repo's own sources.`);
  process.exit(1);
}

if (result.status !== 0 && blocks.length === 0) {
  // tsc failed but produced nothing matching our diagnostic pattern --
  // e.g. a config error. Surface it and fail rather than reporting clean.
  process.exit(result.status ?? 1);
}

console.log("tsc: no errors in this repo's own sources.");
process.exit(0);
