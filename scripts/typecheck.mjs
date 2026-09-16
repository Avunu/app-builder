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
 * tsc reports every path relative to this file's directory (tsconfig.json
 * lives at the repo root next to this script's parent). Anything this
 * repo owns resolves without a leading "../"; anything reached through an
 * alias into ../../odoo always has one. That is the split this script
 * enforces -- not a path allowlist, a "did tsc have to leave this repo to
 * find it" test.
 */

import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repoRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

const result = spawnSync(
  process.platform === "win32" ? "npx.cmd" : "npx",
  ["tsc", "--noEmit", "--pretty", "false"],
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

const vendored = blocks.filter((b) => b.file.startsWith(".."));
const ours = blocks.filter((b) => !b.file.startsWith(".."));

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
