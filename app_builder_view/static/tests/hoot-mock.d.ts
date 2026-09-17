/**
 * Odoo's own `web/static/src/@types/hoot.d.ts` declares `"@odoo/hoot"` and
 * `"@odoo/hoot-dom"` (each `export * from "@web/../lib/hoot/..."`) but not
 * `"@odoo/hoot-mock"`, even though it is a real sibling module
 * (`web/static/lib/hoot/hoot-mock.js`) several hoot tests import from --
 * `animationFrame`, `mockSendBeacon`, `mockDate`, and the rest. A vendored
 * gap, not ours to fix at the source; this file is the same one-line
 * pattern `hoot.d.ts` uses for its two siblings, kept in our own tree
 * since we cannot edit the vendored `@types` directory. Picked up by
 * tsconfig.json's own include entry for every addon's static tests tree
 * -- no new include line needed, and ambient module declarations are
 * global to the program once loaded anywhere in it, so this covers every
 * addon's tests, not just this one's.
 */
declare module "@odoo/hoot-mock" {
    export * from "@web/../lib/hoot/hoot-mock";
}
