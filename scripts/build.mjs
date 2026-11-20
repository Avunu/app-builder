#!/usr/bin/env node
/**
 * `npm run build`: compile every addon's TypeScript, with nothing but Node.
 *
 * The compiled `.js` is not committed (.gitignore), and the manifests name
 * it, so a checkout serves an empty console until it is built. The Nix dev
 * shell and `nix build .#default` build it themselves; this is the same
 * build for an install without Nix:
 *
 *     npm run build          # from the repository's root, Node 20 or newer
 *
 * For each addon with a package.json it runs that addon's locked install
 * (`npm ci`: esbuild alone, from the addon's own package-lock.json) and its
 * `build` script, which writes each `.js` beside its `.ts`. It uses no
 * dependency of the root package.json (those are the lint tools), so the
 * root needs no `npm ci` first.
 *
 * It also removes a compiled `.js` whose `.ts` is gone: the manifests load
 * `static/src/console/**` by glob, so a stale file left by a rename would
 * still be served as a module. Every `.js` under an addon's `static/src` and
 * `static/tests` is build output, never a source: git ignores them all.
 *
 *     --no-install   skip `npm ci` (the addons' node_modules are in place)
 *     --clean        remove the stale `.js` and build nothing
 */

import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import fs from "node:fs";
import path from "node:path";

const repoRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const args = new Set(process.argv.slice(2));
const unknown = [...args].filter((a) => !["--no-install", "--clean"].includes(a));
if (unknown.length > 0) {
  console.error(`build: unknown argument ${unknown.join(" ")}`);
  process.exit(2);
}

const npm = process.platform === "win32" ? "npm.cmd" : "npm";

/** The addons that compile something: a directory with a `build` script. */
function addons() {
  return fs
    .readdirSync(repoRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name.startsWith("app_builder"))
    .map((entry) => entry.name)
    .filter((name) => {
      const manifest = path.join(repoRoot, name, "package.json");
      if (!fs.existsSync(manifest)) {
        return false;
      }
      return Boolean(JSON.parse(fs.readFileSync(manifest, "utf8")).scripts?.build);
    })
    .sort();
}

/** Every file under `dir`, node_modules aside. */
function* walk(dir) {
  if (!fs.existsSync(dir)) {
    return;
  }
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== "node_modules") {
        yield* walk(full);
      }
    } else {
      yield full;
    }
  }
}

/** Remove each compiled `.js` that no `.ts` beside it accounts for. */
function removeStale(addon) {
  let removed = 0;
  for (const sub of ["static/src", "static/tests"]) {
    for (const file of walk(path.join(repoRoot, addon, sub))) {
      if (file.endsWith(".js") && !fs.existsSync(`${file.slice(0, -3)}.ts`)) {
        fs.rmSync(file);
        console.log(`build: removed stale ${path.relative(repoRoot, file)}`);
        removed += 1;
      }
    }
  }
  return removed;
}

function run(addon, ...argv) {
  console.log(`build: ${addon}: npm ${argv.join(" ")}`);
  const result = spawnSync(npm, argv, {
    cwd: path.join(repoRoot, addon),
    stdio: "inherit",
    // Node refuses to spawn a .cmd without a shell since CVE-2024-27980;
    // argv is only fixed script names, so the shell adds no quoting hazard.
    shell: process.platform === "win32",
  });
  if (result.error) {
    console.error(`build: cannot run npm: ${result.error.message}`);
    process.exit(1);
  }
  if (result.status !== 0) {
    console.error(`build: ${addon}: npm ${argv.join(" ")} failed`);
    process.exit(result.status ?? 1);
  }
}

const names = addons();
if (names.length === 0) {
  console.error("build: no addon with a build script here");
  process.exit(1);
}

for (const addon of names) {
  removeStale(addon);
  if (args.has("--clean")) {
    continue;
  }
  if (!args.has("--no-install")) {
    run(addon, "ci", "--no-audit", "--no-fund");
  }
  run(addon, "run", "build");
}

if (!args.has("--clean")) {
  console.log(`build: compiled ${names.length} addons: ${names.join(", ")}`);
}
