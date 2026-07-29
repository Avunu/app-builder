/** @odoo-module **/
/**
 * The field editor, modelled on core's `properties` field popover.
 *
 * Two behaviours are lifted deliberately, because they are what make that
 * editor feel finished:
 *
 *  - **Never a blank required-field wall.** A new field arrives already named
 *    and typed, and the label is focused *and selected*, so typing replaces it.
 *  - **Type-conditional rows.** The server's field-type catalogue names the
 *    parameters each type actually needs, so the form shows exactly those and
 *    nothing else. Unusable types are listed disabled with the reason rather
 *    than hidden -- somebody who cannot find "Amount" learns nothing, whereas
 *    "needs a Currency field on this model" tells them what to do next.
 */

import { Component, useState, useRef, onMounted } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { CheckBox } from "@web/core/checkbox/checkbox";
import { ModelSelector } from "@web/core/model_selector/model_selector";
import { SelectMenu } from "@web/core/select_menu/select_menu";

const ONDELETE_CHOICES = [
    { value: "set null", label: _t("Leave empty") },
    { value: "restrict", label: _t("Prevent deletion") },
    { value: "cascade", label: _t("Delete this record too") },
];

export class FieldPopover extends Component {
    static template = "app_builder_model.FieldPopover";
    static components = { CheckBox, ModelSelector, SelectMenu };
    static props = {
        field: { type: [Object, { value: null }], optional: true },
        fieldTypes: Array,
        existingNames: Array,
        modelName: String,
        onSave: Function,
        onDelete: { type: [Function, { value: null }], optional: true },
        close: Function,
    };

    setup() {
        const field = this.props.field;
        this.isNew = !field;
        this.labelRef = useRef("label");

        this.state = useState(
            field
                ? { ...field }
                : {
                      // Created already valid, so the popover opens on something
                      // editable rather than on a wall of required inputs.
                      name: this.suggestName(_t("New field")),
                      ttype: "char",
                      string: _t("New field"),
                  }
        );
        this.state.error = "";

        onMounted(() => {
            const input = this.labelRef.el;
            if (input) {
                input.focus();
                if (this.isNew) {
                    // Selected, not just focused: the placeholder name is a
                    // starting point, and typing should replace it outright.
                    input.select();
                }
            }
        });
    }

    // -- naming -----------------------------------------------------------

    /**
     * The technical name is derived once, from the first label, and then left
     * alone. Renaming a column is a migration, not a typing gesture.
     */
    suggestName(label) {
        const slug = (label || "")
            .toLowerCase()
            .normalize("NFKD")
            .replace(/[^a-z0-9]+/g, "_")
            .replace(/^_+|_+$/g, "");
        let candidate = slug || "field";
        if (/^[0-9]/.test(candidate)) {
            candidate = `f_${candidate}`;
        }
        let unique = candidate;
        let counter = 2;
        while (this.props.existingNames.includes(unique)) {
            unique = `${candidate}_${counter++}`;
        }
        return unique;
    }

    onLabelInput(ev) {
        this.state.string = ev.target.value;
        if (this.isNew) {
            this.state.name = this.suggestName(this.state.string);
        }
    }

    // -- types ------------------------------------------------------------

    get typeGroups() {
        const groups = {};
        for (const entry of this.props.fieldTypes) {
            (groups[entry.group] ||= []).push(entry);
        }
        return Object.entries(groups).map(([name, choices]) => ({ name, choices }));
    }

    get currentType() {
        return this.props.fieldTypes.find((t) => t.value === this.state.ttype) || {};
    }

    get params() {
        return this.currentType.params || [];
    }

    shows(param) {
        return this.params.includes(param);
    }

    get ondeleteChoices() {
        return ONDELETE_CHOICES;
    }

    onTypeChange(value) {
        const entry = this.props.fieldTypes.find((t) => t.value === value);
        if (!entry || !entry.enabled) {
            return;
        }
        this.state.ttype = value;
        // Parameters that no longer apply would otherwise be written out on a
        // field whose type cannot carry them.
        for (const param of ["comodel", "inverse_name", "selection", "currency_field"]) {
            if (!entry.params.includes(param)) {
                delete this.state[param];
            }
        }
    }

    // -- selection values -------------------------------------------------

    get selectionRows() {
        return this.state.selection || [];
    }

    addSelectionRow() {
        this.state.selection = [
            ...this.selectionRows,
            { value: "", label: "", sequence: (this.selectionRows.length + 1) * 10 },
        ];
    }

    updateSelectionRow(index, key, value) {
        const rows = [...this.selectionRows];
        rows[index] = { ...rows[index], [key]: value };
        if (key === "label" && !rows[index].value) {
            rows[index].value = (value || "")
                .toLowerCase()
                .replace(/[^a-z0-9]+/g, "_")
                .replace(/^_+|_+$/g, "");
        }
        this.state.selection = rows;
    }

    removeSelectionRow(index) {
        this.state.selection = this.selectionRows.filter((_row, i) => i !== index);
    }

    // -- commit -----------------------------------------------------------

    validate() {
        if (!this.state.string?.trim()) {
            return _t("Give the field a label.");
        }
        if (this.shows("comodel") && !this.state.comodel) {
            return _t("Choose the model this points at.");
        }
        if (this.state.ttype === "one2many" && !this.state.inverse_name) {
            return _t("Name the field on the other model that points back.");
        }
        if (
            ["selection", "reference"].includes(this.state.ttype) &&
            !this.selectionRows.filter((r) => r.value).length
        ) {
            return _t("A selection needs at least one value.");
        }
        return "";
    }

    onSave() {
        const problem = this.validate();
        if (problem) {
            this.state.error = problem;
            return;
        }
        const values = { ...this.state };
        delete values.error;
        delete values.type_label;
        if (values.selection) {
            values.selection = this.selectionRows.filter((r) => r.value);
        }
        this.props.onSave(values);
    }

    onDelete() {
        this.props.onDelete?.();
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.onSave();
        }
    }
}
