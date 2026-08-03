/** @odoo-module **/
/**
 * The view editor: the real view on the right, what you selected on the left.
 *
 * Three things about the shape are deliberate.
 *
 * **Edits are live.** Unlike a field, a view needs no reload — views are data,
 * and `apply_operation` writes the arch and the source file in one call. So
 * there is no pending tray here and no Apply button: pretending a cost that
 * does not exist would only make the editor slower and less honest. The price
 * is that an edit is visible to everyone immediately, which the header says out
 * loud.
 *
 * **The preview is the real view, not a drawing of one.** That is the whole
 * point of WYSIWYG, and it is why clicks have to be intercepted in the capture
 * phase: a click in a list would otherwise open a record and navigate away from
 * the editor mid-edit.
 *
 * **The browser never mints an xpath.** It says what was clicked and the server
 * says where that is. The arch a client receives is a per-user projection, so a
 * locator derived from it can be wrong for somebody else — see
 * `studio.view.editor.locate_target`.
 */

import { Component, onWillStart, useRef, useState, useEffect } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { ResizablePanel } from "@web/core/resizable_panel/resizable_panel";
import { useService } from "@web/core/utils/hooks";
import { View } from "@web/views/view";
import { describeTarget, sameTarget, shouldPassThrough } from "./selection";
import { optionsFor, visibleRows, writeValue } from "./options";

export class StudioViewEditor extends Component {
    static template = "app_builder_view.StudioViewEditor";
    static components = { ResizablePanel, View };
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        this.previewRef = useRef("preview");

        this.state = useState({
            loading: true,
            context: null,
            target: null,
            previewKey: 1,
            busy: false,
            message: "",
        });

        onWillStart(async () => {
            this.state.context = await this.orm.call(
                "studio.view.editor",
                "editing_context",
                [this.params.view_id || false],
                {
                    model: this.params.res_model,
                    view_type: this.params.view_type,
                }
            );
            this.state.loading = false;
        });

        // Capture phase, on the container rather than per element: the view
        // re-renders after every edit, so anything bound to individual nodes
        // would go stale the first time somebody changed something.
        useEffect(
            (el) => {
                if (!el) {
                    return;
                }
                const onClick = (ev) => this.onPreviewClick(ev);
                el.addEventListener("click", onClick, true);
                return () => el.removeEventListener("click", onClick, true);
            },
            () => [this.previewRef.el]
        );
    }

    // -- what we are editing ----------------------------------------------

    get params() {
        const action = this.props.action || {};
        return { ...(action.context || {}), ...(action.params || {}) };
    }

    get viewId() {
        // The resolved id, once we have it: the caller may have had none.
        return this.view.id || this.params.view_id;
    }

    get view() {
        return (this.state.context && this.state.context.view) || {};
    }

    get packageId() {
        return this.state.context && this.state.context.suggested_package_id;
    }

    get panels() {
        if (!this.state.target || !this.state.target.found) {
            return [];
        }
        return optionsFor(this.view.type, this.state.target).map((option) => ({
            id: option.id || option.title(this.state.target),
            title: option.title(this.state.target),
            rows: visibleRows(option, this.state.target),
        }));
    }

    get ownershipNote() {
        if (!this.state.context) {
            return "";
        }
        return this.state.context.owned
            ? _t("This package owns this view, so changes are written into it directly.")
            : _t(
                  "This view belongs to another module. Changes become a separate " +
                      "inheriting view, so the original keeps working and upgrades " +
                      "cleanly."
              );
    }

    // -- selecting ---------------------------------------------------------

    async onPreviewClick(ev) {
        // The preview is a working view: without this a click opens a record,
        // sorts a column, or ticks a checkbox instead of selecting. Notebook
        // tabs are the exception -- selecting a page you cannot switch to
        // would mean editing a tab whose contents you cannot see.
        if (!shouldPassThrough(ev.target)) {
            ev.preventDefault();
            ev.stopPropagation();
        }

        const descriptor = describeTarget(ev.target, this.view.type);
        if (this.state.target && sameTarget(this.state.target.descriptor, descriptor)) {
            return;
        }
        const found = await this.orm.call("studio.view.editor", "locate_target", [
            this.viewId,
            descriptor,
        ]);
        // Both halves: the descriptor carries what was clicked (`kind`, `name`),
        // which is what the option registry matches on, and the server's answer
        // carries where it is and what it currently says.
        this.state.target = { ...descriptor, ...found, descriptor };
        this.state.message = found.found ? "" : found.reason;
    }

    selectRoot() {
        return this.onPreviewClick({
            target: null,
            preventDefault: () => {},
            stopPropagation: () => {},
        });
    }

    // -- changing ----------------------------------------------------------

    async onRowChange(row, rawValue) {
        if (!this.packageId) {
            this.notification.add(
                _t("Choose a studio package to record this change in first."),
                { type: "warning" }
            );
            return;
        }
        this.state.busy = true;
        try {
            await this.orm.call("studio.view.editor", "apply_operation", [
                this.viewId,
                this.packageId,
                {
                    type: "set_attributes",
                    xpath: this.state.target.xpath,
                    position: "attributes",
                    attrs: { [row.name]: writeValue(row, rawValue) },
                },
            ]);
            // Re-read the node so the panel shows what the arch now says rather
            // than what we hoped it would say.
            const found = await this.orm.call("studio.view.editor", "locate_target", [
                this.viewId,
                this.state.target.descriptor,
            ]);
            const descriptor = this.state.target.descriptor;
            this.state.target = { ...descriptor, ...found, descriptor };
            // Two separate staleness problems, and fixing only one leaves the
            // user looking at their unchanged view after a successful edit.
            // viewService caches loaded arches by (model, view id, type), so
            // the cache has to be dropped...
            this.env.bus.trigger("CLEAR-CACHES");
            // ...and the component re-keyed, or Owl reuses the mounted view.
            this.state.previewKey += 1;
        } finally {
            this.state.busy = false;
        }
    }

    onToggle(row, ev) {
        return this.onRowChange(row, ev.target.checked);
    }

    onInput(row, ev) {
        return this.onRowChange(row, ev.target.value);
    }

    openPackage() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "studio.package",
            res_id: this.packageId,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("app_builder_view_wysiwyg", StudioViewEditor);
