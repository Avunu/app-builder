/** @odoo-module **/
/**
 * The model composer.
 *
 * A sidebar of what the model *is*, beside a live preview of what it looks
 * like. Two things about the shape are deliberate:
 *
 *  - **Edits stage, they do not save.** A new column needs the class
 *    re-imported, so the studio cannot make each keystroke live. Rather than
 *    hide that, the tray shows exactly what is pending and one Apply writes and
 *    reloads once for the whole changeset. All the staging happens in
 *    `studio.model.draft`, which touches no `ir.model.fields` and therefore no
 *    registry.
 *  - **The preview shows the applied state, not the pending one.** You cannot
 *    render a form containing a field the registry does not have. Pretending
 *    otherwise would be a lie that breaks the moment anything real happens, so
 *    the preview is honest and the tray carries the difference.
 *
 * The `previewKey` bump on Apply is load-bearing: `viewService` caches by view
 * id, so without re-keying the `<View/>` the preview would keep showing the
 * arch from before the reload. A stale preview would cost trust faster than a
 * missing feature.
 */

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ResizablePanel } from "@web/core/resizable_panel/resizable_panel";
import { View } from "@web/views/view";
import { _t } from "@web/core/l10n/translation";
import { FieldPopover } from "./field_popover";
import { usePopover } from "@web/core/popover/popover_hook";

export class StudioComposer extends Component {
    static template = "app_builder_model.StudioComposer";
    static components = { ResizablePanel, View };
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");

        this.popover = usePopover(FieldPopover, {
            popoverClass: "o_studio_field_popover",
            position: "right",
            closeOnClickAway: (target) => this.canClosePopover(target),
        });

        this.draftId = this.resolveDraftId();

        this.state = useState({
            loading: true,
            data: null,
            tab: "fields",
            previewKey: 1,
            diff: "",
            applying: false,
        });

        onWillStart(() => this.reload());
    }

    /**
     * Where the draft comes from, in order of directness. The URL fallback is
     * what makes the composer resumable: Apply rebuilds the registry, so the
     * page has to survive being reopened from its own address.
     */
    resolveDraftId() {
        const action = this.props.action || {};
        const fromAction =
            action.params?.draft_id ||
            action.context?.studio_draft_id ||
            action.context?.draft_id;
        if (fromAction) {
            return fromAction;
        }
        const fromUrl = new URLSearchParams(window.location.search).get("draft_id");
        return fromUrl ? parseInt(fromUrl, 10) : null;
    }

    /**
     * Sibling overlays are not DOM children of the popover, so a click in a
     * date picker or a model-field selector reads as "outside" and would close
     * the editor mid-edit. Core's properties field carries the same guard, and
     * without it the popover feels broken the first time anyone opens the
     * domain builder.
     */
    canClosePopover(target) {
        const escapes = [
            ".o_datetime_picker",
            ".o_model_field_selector_popover",
            ".o_domain_selector_dialog",
            ".o_select_menu_menu",
            ".modal",
            ".o_tag_popover",
        ];
        return !escapes.some((selector) => target.closest?.(selector));
    }

    // -- data -------------------------------------------------------------

    async reload() {
        this.state.data = await this.orm.call(
            "studio.model.draft",
            "load",
            [[this.draftId]]
        );
        this.state.loading = false;
    }

    async call(method, args = []) {
        try {
            await this.orm.call("studio.model.draft", method, [[this.draftId], ...args]);
        } finally {
            await this.reload();
        }
    }

    get data() {
        return this.state.data || {};
    }

    get fields() {
        return this.data.fields || [];
    }

    get pending() {
        return this.data.pending || [];
    }

    get changeCount() {
        return this.data.change_count || 0;
    }

    get errors() {
        return this.data.errors || [];
    }

    get canApply() {
        return (
            this.changeCount > 0 &&
            !this.errors.length &&
            !this.state.applying &&
            this.data.package?.writable
        );
    }

    get reloadNotice() {
        const mode = this.data.package?.reload_mode;
        if (mode === "manual") {
            return _t("This server runs several workers, so it cannot reload in place. Restart it to pick these changes up.");
        }
        if (mode === "restart") {
            return _t("Applying restarts the server, which takes a few seconds.");
        }
        return _t("Applying reloads this package. It takes a moment.");
    }

    // -- fields -----------------------------------------------------------

    openField(ev, fieldName) {
        const target = ev.currentTarget;
        const existing = this.fields.find((f) => f.name === fieldName);
        this.popover.open(target, {
            field: existing ? { ...existing } : null,
            fieldTypes: this.data.field_types || [],
            existingNames: this.fields.map((f) => f.name),
            modelName: this.data.model,
            inverseOptions: (comodel) => this.inverseOptions(comodel),
            resolveRelated: (path) => this.resolveRelated(path),
            onSave: (values) => this.saveField(existing, values),
            onDelete: existing ? () => this.removeField(existing.name) : null,
        });
    }

    /**
     * Asked of the server rather than derived here: whether a model can be
     * linked back depends on what the package owns in Python, which is a fact
     * only the server has.
     */
    inverseOptions(comodel) {
        return this.orm.call("studio.model.draft", "inverse_options", [
            [this.draftId],
            comodel,
        ]);
    }

    /**
     * Also the server's answer, and for a stronger reason: a related field's
     * type is whatever the chain ends at, and getting it wrong is a registry
     * error when the class loads rather than a message anybody can act on.
     */
    resolveRelated(path) {
        return this.orm.call("studio.model.draft", "resolve_related", [
            [this.draftId],
            path,
        ]);
    }

    async saveField(existing, values) {
        this.popover.close();
        if (existing) {
            await this.call("update_field", [existing.name, values]);
        } else {
            await this.call("add_field", [values]);
        }
    }

    async removeField(name) {
        this.popover.close();
        await this.call("remove_field", [name]);
    }

    async moveField(name, before) {
        await this.call("move_field", [name, before]);
    }

    async onMoveUp(name) {
        const names = this.fields.map((f) => f.name);
        const index = names.indexOf(name);
        if (index > 0) {
            await this.moveField(name, names[index - 1]);
        }
    }

    async onMoveDown(name) {
        const names = this.fields.map((f) => f.name);
        const index = names.indexOf(name);
        if (index >= 0 && index < names.length - 1) {
            await this.moveField(name, names[index + 2] || null);
        }
    }

    // -- commit -----------------------------------------------------------

    async showDiff() {
        this.state.diff = await this.orm.call(
            "studio.model.draft",
            "preview_diff",
            [[this.draftId]]
        );
        this.state.tab = "source";
    }

    async onApply(allowDestructive = false) {
        this.state.applying = true;
        try {
            await this.orm.call("studio.model.draft", "action_apply", [
                [this.draftId],
                allowDestructive,
            ]);
            this.notification.add(_t("Applied."), { type: "success" });
            // The registry has just been rebuilt; re-key so the preview stops
            // showing the arch it cached before the reload.
            this.state.previewKey += 1;
            await this.reload();
        } catch (error) {
            // A destructive change is refused once on purpose, so the user is
            // told what would be lost before deciding.
            const message = error?.data?.message || error?.message || "";
            if (!allowDestructive && /remove|drop|destructive/i.test(message)) {
                this.state.destructiveWarning = message;
            }
            throw error;
        } finally {
            this.state.applying = false;
        }
    }

    async onDiscard() {
        await this.call("action_discard");
        this.state.diff = "";
    }

    openPackage() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "studio.package",
            res_id: this.data.package.id,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("app_builder_composer", StudioComposer);
