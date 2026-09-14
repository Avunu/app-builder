/** @odoo-module **/
/**
 * Properties: what the selected node is, and what can be changed about it.
 *
 * The rows come from the server's option catalogue, resolved against what
 * this browser has (`options.js`); the node's current attributes and its
 * field come from `describe_node`, asked for on selection and cached until
 * the arch changes. A row that is edited writes a whole attribute map
 * through `set_attributes` -- a row targeting a widget option is changing
 * one key of the node's `options="{...}"` blob and has to hand the blob
 * back -- against the token the node was selected by, never against a
 * locator the browser worked out.
 *
 * Below the view's rows, the field's *definition*: what it is at the
 * model level, which the view can only dress. Three origins, three
 * treatments. A core field's definition is Python and is shown as facts.
 * A manual `x_` field's is a row of `ir.model.fields`, and its label,
 * help, flags and selection values are edited here through
 * `update_manual_field` -- including from the Label row above, which for
 * such a field writes the model's label rather than a view override, and
 * says so. A pending field's is staged on a draft and does not exist yet:
 * its ghost has no attributes to describe, so the panel shows what was
 * staged and opens the field editor on it, and can take it off the draft.
 *
 * Above the rows, the node's ancestors as a breadcrumb, so a field's group
 * and the group's tab are one click away; below them, Remove, which asks
 * first when the node has something in it.
 */

import { Component, onWillDestroy, useEffect, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { optionsFor, visibleRows, writeValue } from "../options";
import { iconForType } from "../pending_widget";
import { useFieldEditor } from "./field_editor_fallback";

/**
 * The rows a manual field's definition can offer, in this order; which
 * of them appear is the server's word (`definition.editable`).
 */
const DEFINITION_ROWS = [
    { name: "field_description", label: _t("Label"), type: "text" },
    { name: "help", label: _t("Help"), type: "text" },
    { name: "required", label: _t("Required"), type: "toggle" },
    { name: "readonly", label: _t("Read-only"), type: "toggle" },
    { name: "index", label: _t("Indexed"), type: "toggle" },
    { name: "translate", label: _t("Translatable"), type: "toggle" },
    { name: "selection", label: _t("Values"), type: "selection" },
];

export class PropertiesTab extends Component {
    static template = "app_builder_view.PropertiesTab";
    static props = { model: Object };

    setup() {
        this.model = useState(this.props.model);
        this.dialog = useService("dialog");
        this.editor = useFieldEditor();
        this.state = useState({ target: null, loading: false, selectionDraft: null });
        let alive = true;
        onWillDestroy(() => {
            alive = false;
        });
        useEffect(
            (token, version) => {
                this.state.target = null;
                this.state.selectionDraft = null;
                if (!token || !version || this.isPending) {
                    // A ghost is not in the arch: there is nothing to
                    // describe, and its definition is on the draft.
                    return;
                }
                this.state.loading = true;
                this.model.describe(token).then((target) => {
                    if (!alive || !this.model.selection || this.model.selection.token !== token) {
                        return;
                    }
                    this.state.target = target;
                    this.state.loading = false;
                });
            },
            () => [this.model.selection && this.model.selection.token, this.model.archVersion]
        );
    }

    get node() {
        return this.model.selectedNode;
    }

    get token() {
        return this.model.selection ? this.model.selection.token : null;
    }

    /** The selected node's ancestors, outermost first, as clickable crumbs. */
    get crumbs() {
        const nodes = this.model.nodes;
        const out = [];
        let token = this.node ? this.node.parent : null;
        while (token && nodes[token]) {
            out.unshift({ token, label: this.model.tagFor(token) });
            token = nodes[token].parent;
        }
        return out;
    }

    get panels() {
        const target = this.state.target;
        if (!target || !target.found) {
            return [];
        }
        const context = this.model.context || {};
        return optionsFor(context, target).map((group) => ({
            id: group.id,
            title: group.title,
            rows: visibleRows(group, target, context),
        }));
    }

    get groupChoices() {
        return (this.model.context && this.model.context.groups) || [];
    }

    get canRemove() {
        return Boolean(this.node && this.node.removable && this.model.packageId);
    }

    // -- the definition -----------------------------------------------------

    get definition() {
        return (this.state.target && this.state.target.definition) || null;
    }

    get isManual() {
        return Boolean(this.definition && this.definition.origin === "manual");
    }

    /**
     * Whether the Label row above writes the model's label, not the
     * view's: for a manual field, unless this view already overrides the
     * label -- then the override is what is on screen, and the row edits
     * that, as it says.
     */
    labelWritesDefinition(row) {
        if (row.name !== "string" || row.target === "option" || !this.isManual) {
            return false;
        }
        const attrs = (this.state.target && this.state.target.attrs) || {};
        return !attrs.string;
    }

    /** The editable rows of a manual field's definition, with their values. */
    get definitionRows() {
        const definition = this.definition;
        if (!definition || !this.isManual) {
            return [];
        }
        const editable = definition.editable || [];
        const values = definition.values || {};
        // The Label row of the view section already writes the model's
        // label when this view does not override it; one row for it.
        const attrs = (this.state.target && this.state.target.attrs) || {};
        const rows = DEFINITION_ROWS.filter(
            (row) =>
                editable.includes(row.name) &&
                (row.name !== "field_description" || attrs.string)
        );
        return rows.map((row) => ({
            ...row,
            key: `def:${row.name}`,
            value: row.type === "toggle" ? Boolean(values[row.name]) : values[row.name] || "",
        }));
    }

    /** The read-only facts of any field's definition. */
    get facts() {
        const definition = this.definition;
        if (!definition) {
            return [];
        }
        const values = definition.values || {};
        const out = [
            { label: _t("Technical name"), value: this.node && this.node.name },
            { label: _t("Type"), value: values.ttype },
        ];
        if (values.relation) {
            out.push({ label: _t("Relation"), value: values.relation });
        }
        if (!this.isManual) {
            out.push(
                { label: _t("Label"), value: values.field_description },
                { label: _t("Required"), value: values.required ? _t("Yes") : _t("No") },
                { label: _t("Read-only"), value: values.readonly ? _t("Yes") : _t("No") }
            );
            if (values.help) {
                out.push({ label: _t("Help"), value: values.help });
            }
        }
        out.push({
            label: _t("Defined"),
            value: definition.origin === "manual" ? _t("in this database") : _t("in Python"),
        });
        return out;
    }

    /** The selection values being edited, a copy until they are sent. */
    get selectionRows() {
        if (this.state.selectionDraft) {
            return this.state.selectionDraft;
        }
        const values = (this.definition && this.definition.values) || {};
        return (values.selection || []).map((row) => ({ ...row }));
    }

    editSelectionRow(index, key, value) {
        const rows = this.selectionRows.map((row) => ({ ...row }));
        rows[index] = { ...rows[index], [key]: value };
        if (key === "label" && !rows[index].value) {
            rows[index].value = (value || "")
                .toLowerCase()
                .replace(/[^a-z0-9]+/g, "_")
                .replace(/^_+|_+$/g, "");
        }
        this.state.selectionDraft = rows;
    }

    addSelectionRow() {
        const rows = this.selectionRows.map((row) => ({ ...row }));
        rows.push({ value: "", label: "", sequence: (rows.length + 1) * 10 });
        this.state.selectionDraft = rows;
    }

    removeSelectionRow(index) {
        this.state.selectionDraft = this.selectionRows.filter((_row, i) => i !== index);
    }

    get selectionDirty() {
        return Boolean(this.state.selectionDraft);
    }

    async saveSelection() {
        const rows = this.selectionRows
            .filter((row) => row.value)
            .map((row, index) => ({
                value: row.value,
                label: row.label || row.value,
                sequence: row.sequence || (index + 1) * 10,
            }));
        if (!rows.length) {
            this.model.notification.add(_t("A selection needs at least one value."), {
                type: "warning",
            });
            return;
        }
        await this.writeDefinition({ selection: rows });
    }

    /** One write to `ir.model.fields`, and the panel shows what it now says. */
    async writeDefinition(values) {
        if (!this.token || !this.state.target) {
            return;
        }
        const token = this.token;
        const definition = await this.model.updateManualField(token, values);
        if (definition === undefined || !this.state.target || this.token !== token) {
            return;
        }
        this.state.selectionDraft = null;
        this.state.target = {
            ...this.state.target,
            definition,
            field: this.state.target.field
                ? {
                      ...this.state.target.field,
                      string: (definition.values || {}).field_description,
                  }
                : this.state.target.field,
        };
    }

    onDefinitionToggle(row, ev) {
        return this.writeDefinition({ [row.name]: ev.target.checked });
    }

    onDefinitionInput(row, ev) {
        return this.writeDefinition({ [row.name]: ev.target.value });
    }

    // -- fields the package defines in Python ---------------------------------
    //
    // Their definition is a class attribute: editing it is staged on the
    // model's draft, exactly like a pending field's, and lands on Apply.
    // Three things the panel says about one: what the draft already holds
    // for it, how to edit it, and that a removal drops a column.

    /** A field node of a model this package defines in Python. */
    get isOwnedPython() {
        return Boolean(
            this.model.pythonOwned &&
                this.node &&
                this.node.kind === "field" &&
                this.definition &&
                this.definition.origin !== "manual"
        );
    }

    /** The change the draft holds for this field, or `null`. */
    get ownedPendingKind() {
        if (!this.isOwnedPython || !this.node) {
            return null;
        }
        const entry = this.model.modelFields.find((f) => f.name === this.node.name);
        return (entry && entry.pendingKind) || null;
    }

    get ownedPendingNote() {
        switch (this.ownedPendingKind) {
            case "changed":
                return _t("Its definition has a staged edit; Apply writes it.");
            case "removed":
                return _t("Staged for removal; Apply drops the column and keeps its data aside.");
            case "added":
                return _t("Staged as a new field; Apply creates it.");
            default:
                return "";
        }
    }

    /** Open the field editor on the class attribute, staged on the draft. */
    async onEditOwned(ev) {
        if (!this.node) {
            return;
        }
        const name = this.node.name;
        const anchor = ev.currentTarget;
        const draft = await this.model._ensureDraft();
        const staged = draft && this.model.stagedField(name);
        if (!staged) {
            this.model.notification.add(
                _t("The class this field belongs to could not be read into a draft."),
                { type: "warning" }
            );
            return;
        }
        this.editor.open(anchor, {
            field: { ...staged },
            mode: "staged",
            fieldTypes: this.model.fieldTypes,
            existingNames: ((this.model.draft && this.model.draft.fields) || [])
                .map((f) => f.name)
                .filter((n) => n !== name),
            modelName: this.model.modelName,
            inverseOptions: (comodel) => this.model.inverseOptions(comodel),
            resolveRelated: (path) => this.model.resolveRelated(path),
            onSave: async (values) => {
                this.editor.close();
                await this.model.updateStaged(name, values);
            },
            onDelete: () => {
                this.editor.close();
                this.onRemoveOwned();
            },
        });
    }

    /** Stage the removal of a class attribute: a dropped column on Apply. */
    onRemoveOwned() {
        if (!this.node) {
            return;
        }
        const name = this.node.name;
        const label = (this.definition && this.definition.values.field_description) || name;
        this.dialog.add(ConfirmationDialog, {
            title: _t("Remove field from the model"),
            body: _t(
                "Remove %s from the model? Nothing changes until Apply; then its " +
                    "column is dropped and its data kept aside by a migration. " +
                    "Discard the pending changes to take it back before that.",
                label
            ),
            confirmLabel: _t("Stage the removal"),
            confirm: async () => {
                const result = await this.model.removePending(name);
                if (result !== undefined) {
                    this.model.clearSelection();
                }
            },
            cancel: () => {},
        });
    }

    // -- pending fields -----------------------------------------------------

    get isPending() {
        return Boolean(this.node && this.node.kind === "pending");
    }

    /** What the ghost stands for: the node's word, then the draft's. */
    get pendingField() {
        const node = this.node;
        if (!node || !this.isPending) {
            return null;
        }
        const info = node.pending || {};
        const name = info.name || node.name;
        const staged = this.model.stagedField(name);
        return {
            name,
            string: (staged && staged.string) || info.string || name,
            ttype: (staged && staged.ttype) || info.ttype || "",
            typeLabel: (staged && staged.type_label) || info.ttype || "",
            resolved: info.resolved !== false,
            staged,
        };
    }

    get pendingIcon() {
        const field = this.pendingField;
        return field ? iconForType(field.ttype, field.ttype) : "";
    }

    /** Open the field editor on the staged definition, beside the button. */
    async onEditPending(ev) {
        const field = this.pendingField;
        if (!field) {
            return;
        }
        let staged = field.staged;
        if (!staged) {
            await this.model.loadDraft();
            staged = this.model.stagedField(field.name);
        }
        if (!staged) {
            this.model.notification.add(
                _t("The draft this field is staged on could not be read."),
                { type: "warning" }
            );
            return;
        }
        const name = field.name;
        this.editor.open(ev.currentTarget, {
            field: { ...staged },
            mode: "staged",
            fieldTypes: this.model.fieldTypes,
            existingNames: ((this.model.draft && this.model.draft.fields) || [])
                .map((f) => f.name)
                .filter((n) => n !== name),
            modelName: this.model.modelName,
            inverseOptions: (comodel) => this.model.inverseOptions(comodel),
            resolveRelated: (path) => this.model.resolveRelated(path),
            onSave: async (values) => {
                this.editor.close();
                await this.model.updateStaged(name, values);
            },
            onDelete: () => {
                this.editor.close();
                this.onRemovePending();
            },
        });
    }

    onRemovePending() {
        const field = this.pendingField;
        if (!field) {
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: _t("Remove pending field"),
            body: _t(
                "Remove %s from the draft? It has not been applied, so nothing is lost but its definition.",
                field.string
            ),
            confirmLabel: _t("Remove"),
            confirm: async () => {
                const result = await this.model.removePending(field.name);
                if (result !== undefined) {
                    this.model.clearSelection();
                }
            },
            cancel: () => {},
        });
    }

    // -- writing ------------------------------------------------------------

    async onRowChange(row, rawValue) {
        if (!this.token || !this.state.target) {
            return;
        }
        if (this.labelWritesDefinition(row)) {
            // The label of a manual field is the model's, and renaming it
            // here renames it everywhere rather than on this view alone.
            await this.writeDefinition({ field_description: rawValue });
            return;
        }
        await this.model.setAttributes(this.token, writeValue(row, rawValue, this.state.target));
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

    /** The Label row of a manual field shows the model's label, not the view's. */
    rowValue(row) {
        if (this.labelWritesDefinition(row) && !row.value) {
            return ((this.definition && this.definition.values) || {}).field_description || "";
        }
        return row.value;
    }

    async onRemove() {
        if (!this.token) {
            return;
        }
        const token = this.token;
        const result = await this.model.remove(token, false);
        if (result && result.confirm) {
            this.dialog.add(ConfirmationDialog, {
                title: _t("Remove from view"),
                body: result.confirm,
                confirmLabel: _t("Remove"),
                confirm: () => this.model.remove(token, true),
                cancel: () => {},
            });
        }
    }
}
