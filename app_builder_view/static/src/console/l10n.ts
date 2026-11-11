/** @odoo-module **/
/**
 * `_t`, the same function `@web/core/l10n/translation` exports, with a type
 * that is true instead of the `any` it otherwise brings in.
 *
 * `translation.js` is untyped vendor JS (`allowJs`, `checkJs: false`) whose
 * own JSDoc promises `@returns {string|Markup|LazyTranslatedString}` -- but
 * neither `Markup` nor `LazyTranslatedString` is a name that file declares
 * as a type, so TypeScript collapses the whole return type to its `error`
 * intrinsic, and `checkJs: false` suppresses the diagnostic that would have
 * said so. Every `_t(...)` in this tree was therefore an `any` flowing
 * silently into typed code: `tsc` reported nothing, and typescript-eslint's
 * `no-unsafe-*` rules reported it at every one of well over a hundred call
 * sites -- the real reason `eslint` could not be enforced, not the
 * program-construction bug `eslint.config.mjs` used to blame.
 *
 * Nothing changes at runtime: this re-exports the identical function, so a
 * call before translations load still returns a *lazy* value, which is why
 * this is deliberately not a stringifying wrapper (`odoo.ts`'s own header
 * explains why that would be the wrong default). The honest type follows
 * from that: a plain `string` once translations are loaded, otherwise a
 * `LazyTranslatedString` -- and, when a value passed in is a `markup()`, a
 * `Markup`. Both are `String` subclasses, so the whole range is `string |
 * String`. Write `String(_t(...))` where a primitive string is what is
 * actually needed, as the tree already does.
 *
 * Its own module, not a member of `odoo.ts`: that file imports Owl hooks and
 * a real dialog component, and the Owl-free modules (`console_model.ts`,
 * `drag.ts`, the pure `zones`/`options`/`outline_tree` family) must not
 * pull those in just to translate a label. This file's only runtime
 * dependency is the one every caller already had.
 *
 * `app_builder_ui` and `app_builder_approval` do not depend on
 * `app_builder_view`, so they must not import this module at runtime (it
 * would be missing from their bundles when installed without it). They
 * import `_t` from `@web/core/l10n/translation` as before and take only
 * the type, `TranslateFn`, through an `import type` -- erased from the
 * emitted `.js`.
 */

import {_t as _tUntyped} from "@web/core/l10n/translation";

/** What `_t` returns: see this module's own header. */
export type Translated = string | String; // eslint-disable-line @typescript-eslint/no-wrapper-object-types

/** `_t`'s real signature. */
export type TranslateFn = (term: string, ...values: unknown[]) => Translated;

export const _t: TranslateFn = _tUntyped as TranslateFn;
