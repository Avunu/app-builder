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

import { Component, markup, onWillStart, useRef, useState, useEffect } from "@odoo/owl";
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
            search: { fields: [], filters: [], group_bys: [] },
            filterField: "",
            filterCondition: "set",
            palette: [],
            paletteFilter: "",
            newButton: { string: "", action_id: "" },
            serverActions: [],
            // A report is previewed as its own rendered output, because a
            // report is a template and the web client has no qweb view type.
            report: { html: "", reason: "", model: "", anchor: null },
            reportField: "",
            reportLabel: "",
            reportList: "",
            reportColumns: [],
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
            await this.loadSearch();
            if (this.isReport) {
                await this.loadReport();
            } else if (!this.isSearch) {
                await this.loadPalette();
                await this.loadServerActions();
            }
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

    get preview() {
        return (
            (this.state.context && this.state.context.preview) || {
                type: this.view.type,
                view_id: this.view.id,
                search_view_id: false,
            }
        );
    }

    get packageId() {
        return this.state.context && this.state.context.suggested_package_id;
    }

    get panels() {
        if (!this.state.target || !this.state.target.found) {
            return [];
        }
        const context = this.state.context || {};
        return optionsFor(context, this.state.target).map((group) => ({
            id: group.id,
            title: group.title,
            rows: visibleRows(group, this.state.target, context),
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

        if (this.isReport) {
            return this.onReportClick(ev);
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

    /**
     * A click in a rendered report, resolved through what qweb branded.
     *
     * Community brands `t-field` and nothing else, with `data-oe-expression`
     * -- node branding of rendered output is a `website` feature. So a value
     * is selectable and the prose around it is not, which is honest: the prose
     * is not in this template as a node the builder put there.
     */
    async onReportClick(ev) {
        const node =
            ev.target && ev.target.closest && ev.target.closest("[data-oe-expression]");
        if (!node) {
            this.state.target = null;
            this.state.message = this.state.report.anchor
                ? ""
                : this.state.report.anchorReason || "";
            return;
        }
        const expression = node.getAttribute("data-oe-expression");
        const found = await this.orm.call("studio.report", "locate_expression", [
            this.viewId,
            expression,
        ]);
        this.state.target = { kind: "report_field", expression, ...found };
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
                    // A whole map, not one value: a row that edits a widget
                    // option is changing one key of the node's options="{...}"
                    // blob and has to hand the blob back.
                    attrs: writeValue(row, rawValue, this.state.target),
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

    onMultiSelect(row, ev) {
        return this.onRowChange(
            row,
            [...ev.target.selectedOptions].map((option) => option.value)
        );
    }

    /** Groups a `groups=""` attribute can name; only ones with an xmlid. */
    get groupChoices() {
        return (this.state.context && this.state.context.groups) || [];
    }

    // -- search views -------------------------------------------------------
    //
    // Edited as the three lists a search view really is, because it has no
    // rendering of its own to click. The preview still shows the menus being
    // edited -- attached to a real list -- so the feedback loop is intact.

    get isSearch() {
        return this.view.type === "search";
    }

    get isReport() {
        return this.view.type === "qweb";
    }

    async loadReport() {
        const preview = await this.orm.call("studio.report", "preview_html", [
            this.viewId,
        ]);
        const anchor = await this.orm.call("studio.report", "body_anchor", [
            this.viewId,
        ]);
        const printable = await this.orm.call("studio.report", "printable_fields", [
            preview.model || false,
        ]);
        Object.assign(this.state.report, {
            html: markup(preview.html || ""),
            reason: preview.reason || "",
            model: preview.model || "",
            anchor: anchor.found ? anchor : null,
            anchorReason: anchor.found ? "" : anchor.reason,
            values: printable.values,
            lists: printable.lists,
        });
    }

    get reportColumnChoices() {
        const chosen = (this.state.report.lists || []).find(
            (entry) => entry.name === this.state.reportList
        );
        return chosen ? chosen.columns : [];
    }

    /**
     * Where an edit lands: beside the field that was clicked, or in the body.
     *
     * The two are different positions, not just different paths. Placing a
     * value while one is selected means "next to this one"; placing with
     * nothing selected means "in the document", and inside the page container
     * is the only answer that does not depend on what the template happens to
     * contain.
     */
    get reportTarget() {
        if (this.state.target && this.state.target.found) {
            return { xpath: this.state.target.xpath, position: "after" };
        }
        const anchor = this.state.report.anchor;
        return anchor ? { xpath: anchor.xpath, position: anchor.position } : null;
    }

    async placeReportField() {
        const target = this.reportTarget;
        if (!this.state.reportField || !target) {
            return;
        }
        await this.structuralEdit(() =>
            this.orm.call("studio.view.editor", "apply_operation", [
                this.viewId,
                this.packageId,
                {
                    type: "add_report_field",
                    xpath: target.xpath,
                    position: target.position,
                    model: this.state.report.model,
                    name: this.state.reportField,
                    label: this.state.reportLabel || false,
                },
            ])
        );
        this.state.reportLabel = "";
    }

    async placeReportTable() {
        const target = this.reportTarget;
        if (!this.state.reportList || !this.state.reportColumns.length || !target) {
            return;
        }
        await this.structuralEdit(() =>
            this.orm.call("studio.view.editor", "apply_operation", [
                this.viewId,
                this.packageId,
                {
                    type: "add_report_table",
                    xpath: target.xpath,
                    position: target.position,
                    model: this.state.report.model,
                    name: this.state.reportList,
                    columns: [...this.state.reportColumns],
                },
            ])
        );
        this.state.reportColumns = [];
    }

    toggleReportColumn(name) {
        const chosen = this.state.reportColumns;
        const at = chosen.indexOf(name);
        if (at === -1) {
            chosen.push(name);
        } else {
            chosen.splice(at, 1);
        }
    }

    get searchFieldChoices() {
        // Straight from the server: "not already in this view" has to ignore
        // embedded subviews, whose fields belong to another model, and that
        // rule is not one to reimplement here.
        return this.state.search.addable || [];
    }

    get groupByChoices() {
        const present = new Set(
            (this.state.search.group_bys || []).map((g) => g.name.replace("group_by_", ""))
        );
        return (this.state.context.fields || []).filter(
            (f) =>
                ["many2one", "selection", "boolean", "date", "datetime"].includes(f.type) &&
                !present.has(f.name)
        );
    }

    async loadSearch() {
        if (!this.isSearch) {
            return;
        }
        this.state.search = await this.orm.call(
            "studio.view.editor",
            "search_elements",
            [this.viewId]
        );
    }

    async addSearchElement(kind, values) {
        if (!values.field || !this.packageId) {
            return;
        }
        this.state.busy = true;
        try {
            await this.orm.call("studio.view.editor", "add_search_element", [
                this.viewId,
                this.packageId,
                kind,
                values,
            ]);
            await this.afterSearchChange();
        } finally {
            this.state.busy = false;
        }
    }

    async removeSearchElement(kind, name) {
        this.state.busy = true;
        try {
            await this.orm.call("studio.view.editor", "remove_search_element", [
                this.viewId,
                this.packageId,
                kind,
                name,
            ]);
            await this.afterSearchChange();
        } finally {
            this.state.busy = false;
        }
    }

    async afterSearchChange() {
        await this.loadSearch();
        await this.loadHistory();
        this.env.bus.trigger("CLEAR-CACHES");
        this.state.previewKey += 1;
    }

    onAddSearchField(ev) {
        const field = ev.target.value;
        ev.target.value = "";
        return this.addSearchElement("field", { field });
    }

    onAddGroupBy(ev) {
        const field = ev.target.value;
        ev.target.value = "";
        return this.addSearchElement("group_by", { field });
    }

    onAddFilter() {
        const field = this.state.filterField;
        const condition = this.state.filterCondition || "set";
        if (!field) {
            return;
        }
        this.state.filterField = "";
        return this.addSearchElement("filter", { field, condition });
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
        if (this.isReport) {
            // A report selection is an expression, not a descriptor, and its
            // xpath can move when something is inserted above it.
            if (this.state.target && this.state.target.expression) {
                const expression = this.state.target.expression;
                const found = await this.orm.call(
                    "studio.report",
                    "locate_expression",
                    [this.viewId, expression]
                );
                this.state.target = { kind: "report_field", expression, ...found };
            }
            return;
        }
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

    // -- adding to the view ------------------------------------------------
    //
    // Click-to-add rather than drag-and-drop, and anchored on the selection.
    // Where a dropped element lands is genuinely ambiguous in a rendered form --
    // between two groups, inside the notebook, after the chatter -- and the
    // server has to answer it anyway because the browser must not mint a
    // locator. Saying "into the group you have selected" out loud is a smaller
    // promise than a drop shadow, and it is one the editor can keep.

    get anchor() {
        return (this.state.target && this.state.target.descriptor) || { kind: "root" };
    }

    /** Only a leaf can be removed: taking out a container takes its contents. */
    get canRemoveSelection() {
        const target = this.state.target;
        return Boolean(
            target && target.found && ["field", "column", "button", "page"].includes(target.kind)
        );
    }

    /** What the current selection means for something added now. */
    get anchorNote() {
        const kind = this.anchor.kind;
        const inside = ["group", "notebook", "sheet", "header", "root"].includes(kind);
        const what = this.state.target && this.state.target.name;
        if (inside) {
            return kind === "root"
                ? _t("Added at the end of the view.")
                : _t("Added inside the selected %s.", kind);
        }
        return what
            ? _t("Added just after %s.", what)
            : _t("Added just after the selection.");
    }

    async loadPalette() {
        this.state.palette = await this.orm.call(
            "studio.view.editor",
            "get_addable_fields",
            [this.view.model, this.viewId]
        );
    }

    get paletteChoices() {
        const needle = (this.state.paletteFilter || "").toLowerCase();
        if (!needle) {
            return this.state.palette;
        }
        return this.state.palette.filter(
            (f) =>
                f.string.toLowerCase().includes(needle) ||
                f.name.toLowerCase().includes(needle)
        );
    }

    async addField(name) {
        await this.structuralEdit(() =>
            this.orm.call("studio.view.editor", "add_field_at", [
                this.viewId,
                this.packageId,
                this.anchor,
                name,
            ])
        );
    }

    async removeSelected() {
        if (!this.state.target || !this.state.target.found) {
            return;
        }
        await this.structuralEdit(() =>
            this.orm.call("studio.view.editor", "remove_at", [
                this.viewId,
                this.packageId,
                this.anchor,
            ])
        );
        this.state.target = null;
    }

    async addContainer(kind) {
        await this.structuralEdit(() =>
            this.orm.call("studio.view.editor", "add_container_at", [
                this.viewId,
                this.packageId,
                this.anchor,
                kind,
            ])
        );
    }

    async addButton() {
        const values = { ...this.state.newButton };
        if (!values.action_id) {
            this.notification.add(_t("Choose the action this button should run."), {
                type: "warning",
            });
            return;
        }
        values.action_id = Number(values.action_id);
        await this.structuralEdit(() =>
            this.orm.call("studio.view.editor", "add_button_at", [
                this.viewId,
                this.packageId,
                this.anchor,
                values,
            ])
        );
        this.state.newButton = { string: "", action_id: "" };
    }

    async loadServerActions() {
        this.state.serverActions = await this.orm.searchRead(
            "ir.actions.server",
            [["model_id.model", "=", this.view.model]],
            ["id", "name"],
            { limit: 200, order: "name" }
        );
    }

    /**
     * One wrapper for every edit that changes the view's *shape*.
     *
     * All of them invalidate the same three things, and forgetting one leaves
     * the user looking at an unchanged view after a successful edit -- which
     * reads as the editor being broken rather than as a stale cache.
     */
    async structuralEdit(run) {
        if (!this.packageId) {
            this.notification.add(
                _t("Choose a studio package to record this change in first."),
                { type: "warning" }
            );
            return;
        }
        this.state.busy = true;
        try {
            await run();
            if (this.isReport) {
                // The preview is rendered output, not a <View>, so bumping
                // previewKey does nothing for it -- it has to be re-rendered.
                await this.loadReport();
            } else {
                await this.loadPalette();
            }
            await this.loadHistory();
            await this.refreshSelection();
            this.env.bus.trigger("CLEAR-CACHES");
            this.state.previewKey += 1;
        } finally {
            this.state.busy = false;
        }
    }

    // -- adding a view -----------------------------------------------------

    async loadAddable() {
        // A report template has no model -- it must not, or every
        // `<template inherit_id=...>` written against it is dropped -- and
        // "add a view" means nothing for one. Asking anyway raised
        // "Unknown model 'False'" out of onWillStart, so the editor never
        // mounted at all.
        if (this.isReport || !this.view.model) {
            this.state.addable = [];
            return;
        }
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
        // A timeline needs that *and* something to make its rows from, which
        // web_timeline requires where Gantt leaves it optional.
        const dateField = (entry.date_fields || []).length
            ? entry.date_fields[0].name
            : null;
        const groupField = (entry.group_fields || []).length
            ? entry.group_fields[0].name
            : null;
        if (entry.type === "calendar" && !dateField) {
            return;
        }
        if (entry.type === "timeline" && (!dateField || !groupField)) {
            return;
        }
        this.state.busy = true;
        try {
            await this.orm.call("studio.view.editor", "add_view", [
                this.view.model,
                entry.type,
                this.packageId,
                dateField,
                groupField,
            ]);
            this.notification.add(
                _t(
                    "%s view created. It is now offered by this app's menu.",
                    entry.label || entry.type
                ),
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
