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
import { useSortable } from "@web/core/utils/sortable_owl";
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
            addable: [],
            history: [],
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
            await this.loadAddable();
            await this.loadHistory();
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

        // Reordering rides on core's own sortable hook rather than native
        // HTML5 drag-and-drop. Two reasons, and the second is decisive: core's
        // is pointer-based, so it works on touch, and it is what Odoo's own
        // tour helper drives -- native dragstart events are never dispatched by
        // `hoot.drag`, so a native implementation is untestable by tour.
        useSortable({
            enable: () => this.view.type === "list" && Boolean(this.packageId),
            ref: this.previewRef,
            elements: "th[data-name]",
            cursor: "grabbing",
            onDrop: (params) => this.onColumnDropped(params),
        });
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
            rows: visibleRows(option, this.state.target, this.state.context || {}),
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
        if (
            this.view.type === "kanban" &&
            descriptor.kind === "root" &&
            ev.target &&
            ev.target.closest &&
            ev.target.closest(".o_kanban_record")
        ) {
            // A card whose values are `t-esc="record.x.value"` renders no field
            // name into the DOM, so there is nothing to aim at. Silence would
            // read as a broken editor; this says what is going on instead.
            this.state.target = null;
            this.state.message = _t(
                "This card is built from a custom template, so its parts cannot " +
                    "be selected individually. The kanban's own settings are " +
                    "still editable — click outside a card."
            );
            return;
        }
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
            // Re-read the node so the panel shows what the arch now says
            // rather than what we hoped it would say.
            await this.refreshSelection();
            await this.loadHistory();
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

    // -- reordering ---------------------------------------------------------
    //
    // Native drag-and-drop rather than core's sortable hook: the preview is
    // re-rendered wholesale after every edit, and a hook bound to the old nodes
    // would silently stop working the first time somebody changed something.

    /**
     * Where a dragged column landed.
     *
     * The hook reports the element's new neighbours, which is exactly what the
     * move needs: "before that one" is what the user expressed by dropping
     * there, and it survives optional columns being hidden -- an index would
     * not, because the DOM only contains the visible ones.
     */
    async onColumnDropped({ element, previous, next }) {
        const name = element && element.dataset.name;
        const anchor = next || previous;
        if (!name || !anchor || !anchor.dataset.name || !this.packageId) {
            return;
        }
        this.state.busy = true;
        try {
            await this.orm.call("studio.view.editor", "move_node", [
                this.viewId,
                this.packageId,
                { kind: "column", name },
                { kind: "column", name: anchor.dataset.name },
                next ? "before" : "after",
            ]);
            await this.loadHistory();
            await this.refreshSelection();
            this.env.bus.trigger("CLEAR-CACHES");
            this.state.previewKey += 1;
        } finally {
            this.state.busy = false;
        }
    }

    // -- undo ---------------------------------------------------------------

    async loadHistory() {
        this.state.history = await this.orm.call(
            "studio.view.edit",
            "history_for",
            [this.viewId]
        );
    }

    get lastEdit() {
        return this.state.history.length ? this.state.history[0] : null;
    }

    /**
     * Live edits are the honest design -- a view needs no reload -- but on a
     * shared database a mistake is immediately everybody's mistake. Undo is
     * what makes that bargain fair rather than merely fast.
     */
    async onUndo() {
        if (!this.lastEdit) {
            return;
        }
        this.state.busy = true;
        try {
            await this.orm.call("studio.view.edit", "action_undo", [
                [this.lastEdit.id],
            ]);
            await this.loadHistory();
            await this.refreshSelection();
            this.env.bus.trigger("CLEAR-CACHES");
            this.state.previewKey += 1;
        } finally {
            this.state.busy = false;
        }
    }

    /** Re-read the selected node, so the panel shows what the arch now says. */
    async refreshSelection() {
        if (!this.state.target || !this.state.target.descriptor) {
            return;
        }
        const descriptor = this.state.target.descriptor;
        const found = await this.orm.call("studio.view.editor", "locate_target", [
            this.viewId,
            descriptor,
        ]);
        this.state.target = { ...descriptor, ...found, descriptor };
    }

    // -- adding a view -----------------------------------------------------

    async loadAddable() {
        this.state.addable = await this.orm.call(
            "studio.view.editor",
            "addable_view_types",
            [this.view.model]
        );
    }

    async onAddView(entry) {
        if (!entry.enabled || !this.packageId) {
            return;
        }
        // A calendar cannot be built without being told which date to place
        // records on -- date_start is mandatory and the view throws without it.
        let dateField = null;
        if (entry.type === "calendar") {
            dateField = entry.date_fields.length && entry.date_fields[0].name;
            if (!dateField) {
                return;
            }
        }
        this.state.busy = true;
        try {
            await this.orm.call("studio.view.editor", "add_view", [
                this.view.model,
                entry.type,
                this.packageId,
                dateField,
            ]);
            this.notification.add(
                _t("%s view created. It is now offered by this app's menu.", entry.type),
                { type: "success" }
            );
            await this.loadAddable();
        } finally {
            this.state.busy = false;
        }
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
