/** @odoo-module **/
/**
 * What this addon adds to the studio console: the field editor, and a
 * "New Model" tab.
 *
 * The tab is the smaller of the two. The console's top bar takes its tabs
 * from `app_builder.console_tabs`, and a new model is the one thing a
 * builder wants that no view of the current model can offer; the tab
 * opens the New Model wizard -- the same one the Studio menu opens, as a
 * dialog over the console -- with the console's package filled in, and
 * the console is still there when the dialog closes. It needs no model
 * on the canvas, so it is the one tab a report console keeps.
 *
 * The console asks `app_builder.field_editor` for what edits a new field's
 * definition before it is created -- a relation's model, a selection's
 * values -- and ships a label-and-type fallback of its own for when
 * nothing is registered. This addon has the real thing already: the
 * composer's `FieldPopover`, with the type-conditional rows, the inverse
 * picker and the related-chain resolver. It is registered here as it is,
 * behind a thin subclass that takes the two props the console adds to
 * the contract and that the composer never needed:
 *
 *  - `initial`, the `{ttype, string}` a new field starts from -- the tile
 *    that was dropped -- where the composer always starts from Text;
 *  - `mode`, `live` or `staged`, since on a core model the field is an
 *    `ir.model.fields` row created the moment Done is pressed, and the
 *    rows that only mean something for a class attribute -- placement in
 *    the scaffolded views, a computed value -- are not shown for it.
 *
 * Everything else the console hands over -- `fieldTypes`, `existingNames`,
 * `modelName`, `inverseOptions`, `resolveRelated`, `onSave`, `close` --
 * is the popover's own contract.
 */

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { FieldPopover } from "./composer/field_popover";

export class ConsoleFieldEditor extends FieldPopover {
    static template = "app_builder_model.ConsoleFieldEditor";
    static props = {
        ...FieldPopover.props,
        initial: { type: Object, optional: true },
        mode: { type: String, optional: true },
    };

    setup() {
        super.setup();
        const initial = this.props.initial;
        if (this.isNew && initial) {
            const entry = this.props.fieldTypes.find((t) => t.value === initial.ttype);
            if (entry && entry.enabled) {
                this.onTypeChange(initial.ttype);
            }
            if (initial.string) {
                this.state.string = initial.string;
                this.state.name = this.suggestName(initial.string);
            }
        }
    }

    /** Whether the field is a class attribute waiting for an Apply. */
    get staged() {
        return this.props.mode !== "live";
    }

    /**
     * The types the console can make here: on a live model only what
     * the server said can be created as a row, so the picker does not
     * offer a computed field it would then refuse.
     */
    get typeGroups() {
        if (this.staged) {
            return super.typeGroups;
        }
        const groups = {};
        for (const entry of this.props.fieldTypes) {
            if (entry.live === false) {
                continue;
            }
            (groups[entry.group] ||= []).push(entry);
        }
        return Object.entries(groups).map(([name, choices]) => ({ name, choices }));
    }
}

registry.category("app_builder.field_editor").add("field_popover", ConsoleFieldEditor);

registry.category("app_builder.console_tabs").add(
    "new_model",
    {
        label: _t("New Model"),
        isAvailable: () => true,
        async open(env, ctx) {
            // The wizard's own action, so its form and `target="new"` come
            // from the XML; the package is the console's when it has one,
            // else the wizard's own default.
            const context = {};
            if (ctx.packageId) {
                context.default_package_id = ctx.packageId;
            }
            await env.services.action.doAction("app_builder_model.studio_model_wizard_action", {
                additionalContext: context,
            });
        },
    },
    { sequence: 90 }
);
