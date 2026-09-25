/** @odoo-module **/
/**
 * The panes this addon adds to the console, as data.
 *
 * Automations, webhooks, access control, record rules and the menu: each
 * a record pane the console renders itself from the surface named here.
 * Nothing is imported from the console's addon at runtime -- this one
 * does not depend on it, and a real import would only resolve while it
 * is installed -- so an entry is a surface name and a few strings, and
 * the console's record pane does the rest. The empty states carry the
 * one sentence that says what a record of that kind is and where it is
 * written.
 *
 * The three `import type`s below (`PaneRegistration`, `RowActionSpec`,
 * `RecordPaneModel`/`RecordRowJSON`) are the one exception, and a
 * deliberate one: they exist only for `tsc`, to check this file's own
 * registrations against the console addon's real, already-converted
 * contract (per TYPING.md's own instructions for a pane registration)
 * instead of this file inventing its shape a second time. `verbatimModuleSyntax`
 * erases a type-only import completely -- nothing named here appears in
 * the emitted `.js`'s own import list, so the paragraph above stays true
 * of what Odoo's module loader actually sees at runtime, unchanged from
 * before this conversion.
 */

import { _t as _tUntyped } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import type { TranslateFn } from "@app_builder_view/console/l10n";
import type {
    RecordPaneModel,
    RowActionSpec,
} from "@app_builder_view/console/record_pane/record_pane_model";
import type { PaneRegistration } from "@app_builder_view/console/types";
import type { RecordRowJSON } from "@app_builder_view/console/wire";

// `app_builder_ui` does not depend on `app_builder_view` (its manifest), so
// nothing from that addon may be imported here at runtime -- it would be
// missing from this addon's bundle whenever it is installed without it.
// The typed facades are taken as *types* only (`import type`, erased from
// the emitted `.js`) and applied to Odoo's own functions, which is all
// `console/l10n.ts` and `console/odoo.ts` do at runtime anyway.
const _t = _tUntyped as TranslateFn;

const panes = registry.category("app_builder.panes");

/**
 * The fields a record-pane registration may carry beyond the four named
 * parameters below -- read by `record_pane_model.ts`/`record_pane.ts` in
 * the console addon, never by `pane_registry.ts` itself (`PaneRegistration`'s
 * own comment says exactly that, which is why they live under its index
 * signature rather than as named members there). Named here as the
 * subset `RecordPaneEntry` (`record_pane_model.ts`) documents, so this
 * file's own calls are checked against a real reader's shape rather than
 * a guess.
 */
interface PaneExtra {
    scope?: "package" | "model" | "view";
    surfaceArgs?: Record<string, unknown>;
    empty?: { title?: unknown; help?: unknown };
    rowActions?: RowActionSpec[];
}

function pane(
    key: string,
    label: ReturnType<typeof _t>,
    icon: string,
    sequence: number,
    surface: string,
    extra: PaneExtra = {},
): void {
    // Called at module load, so `label` stays the lazy `_t` value it was
    // given: `String()` on it here would throw before translations load
    // (`PaneRegistration.label`'s own comment).
    const value: PaneRegistration = {
        label,
        icon,
        scope: "model",
        surface,
        ...extra,
    };
    panes.add(key, value, { sequence });
}

pane("automations", _t("Automations"), "fa fa-bolt", 30, "studio.automation", {
    empty: {
        title: _t("Make something happen on its own"),
        help: _t(
            "Pick what to watch for and what to do about it. Rules you add are written to data/<model>_automation.xml and ship with the package.",
        ),
    },
});
pane("webhooks", _t("Webhooks"), "fa fa-plug", 40, "studio.automation", {
    surfaceArgs: { webhooks: true },
    empty: {
        title: _t("Let another system drive this database"),
        help: _t(
            "A webhook gives you a URL. Anything that can send it a POST can create or update records of this model.",
        ),
    },
});
pane("access", _t("Access Control"), "fa fa-lock", 50, "studio.access.surface", {
    empty: {
        title: _t("Nobody but the administrator can see this model"),
        help: _t("One line per group. Lines you add are written to security/ir.model.access.csv."),
    },
});
pane("rules", _t("Filter Rules"), "fa fa-filter", 60, "studio.rule.surface", {
    empty: {
        title: _t("Decide which records each group sees"),
        help: _t(
            "A rule is a condition on the records, per group. Rules you add are written to security/<model>_security.xml.",
        ),
    },
});

/** The row before or after `row` among the rows with the same parent. */
function sibling(
    model: RecordPaneModel,
    row: RecordRowJSON,
    direction: 1 | -1,
): RecordRowJSON | null {
    const siblings = model.rows.filter((r) => r.parent_id === row.parent_id);
    const index = siblings.findIndex((r) => r.id === row.id);
    return siblings[index + direction] || null;
}

pane("menu", _t("Menu"), "fa fa-bars", 80, "studio.menu", {
    scope: "package",
    empty: {
        title: _t("Nothing in the apps menu yet"),
        help: _t(
            "An app is a root menu with an icon; a submenu opens a model's views. Both are written to views/menus.xml.",
        ),
    },
    // Up and down among the menus beside it: the surface renumbers the
    // package's own siblings 10/20/30 and leaves the others' numbers alone.
    rowActions: [
        {
            key: "up",
            label: _t("Move up"),
            icon: "fa fa-arrow-up",
            when: (row) => row.editable,
            run: (shell, row, model) => {
                const before = sibling(model, row, -1);
                if (before) {
                    // Fire-and-forget, matching the original: the surface
                    // reloads the pane's own rows on success, and nothing
                    // here has anything to add to a rejection. `void`
                    // only silences `no-floating-promises`; it changes
                    // nothing about when or how the call runs.
                    void model.call("move", [
                        row.id,
                        row.parent_id || false,
                        before.id,
                        shell.packageId,
                    ]);
                }
            },
        },
        {
            key: "down",
            label: _t("Move down"),
            icon: "fa fa-arrow-down",
            when: (row) => row.editable,
            run: (shell, row, model) => {
                const after = sibling(model, row, 1);
                if (after) {
                    const target = sibling(model, after, 1);
                    void model.call("move", [
                        row.id,
                        row.parent_id || false,
                        target ? target.id : false,
                        shell.packageId,
                    ]);
                }
            },
        },
    ],
});
