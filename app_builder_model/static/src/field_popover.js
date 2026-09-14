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
import { ModelFieldSelector } from "@web/core/model_field_selector/model_field_selector";
import { SelectMenu } from "@web/core/select_menu/select_menu";

const ONDELETE_CHOICES = [
    { value: "set null", label: _t("Leave empty") },
    { value: "restrict", label: _t("Prevent deletion") },
    { value: "cascade", label: _t("Delete this record too") },
];

export class FieldPopover extends Component {
    static template = "app_builder_model.FieldPopover";
    static components = { CheckBox, ModelSelector, ModelFieldSelector, SelectMenu };
    static props = {
        field: { type: [Object, { value: null }], optional: true },
        fieldTypes: Array,
        existingNames: Array,
        modelName: String,
        onSave: Function,
        onDelete: { type: [Function, { value: null }], optional: true },
        inverseOptions: Function,
        resolveRelated: Function,
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
            if (this.state.ttype === "one2many" && this.state.comodel) {
                this.loadInverseOptions(this.state.comodel);
            }
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

    // -- relationships ----------------------------------------------------

    /**
     * Odoo needs a many2one on the other side before a related list can exist.
     * Making the user go and build it there first is the gesture every studio
     * gets wrong, so the choice is offered inline: reuse a link that already
     * points back, or have one made in the same Apply.
     */
    async loadInverseOptions(comodel) {
        this.state.inverse = await this.props.inverseOptions(comodel);
        const { candidates, can_create: canCreate, suggested } = this.state.inverse;
        if (candidates.length) {
            this.state.create_inverse = false;
            this.state.inverse_name = candidates[0].name;
        } else if (canCreate) {
            this.state.create_inverse = true;
            this.state.inverse_name = suggested;
        }
    }

    get inverse() {
        return this.state.inverse || { candidates: [], can_create: false, reason: "" };
    }

    onInverseChange(value) {
        if (value === "__new__") {
            this.state.create_inverse = true;
            this.state.inverse_name = this.inverse.suggested;
        } else {
            this.state.create_inverse = false;
            this.state.inverse_name = value;
        }
    }

    async onComodelSelected(model) {
        this.state.comodel = model.technical;
        if (this.state.ttype === "one2many") {
            await this.loadInverseOptions(model.technical);
        }
    }

    // -- related ----------------------------------------------------------

    /**
     * A related field has no type of its own: `partner_id.email` is a char
     * because `email` is. So the chain is what the user picks, and the type
     * comes back from the server -- asking them to state it as well would be
     * asking them to be right about something the model already knows, where
     * being wrong is a registry error at load time rather than a message.
     */
    async onRelatedChange(path) {
        this.state.related = path;
        this.state.relatedInfo = await this.props.resolveRelated(path);
        if (this.state.relatedInfo.ok) {
            this.state.error = "";
            if (!this.state.string || this.state.string === _t("New field")) {
                this.state.string = this.state.relatedInfo.string;
                this.state.name = this.suggestName(this.state.string);
            }
        }
    }

    get relatedInfo() {
        return this.state.relatedInfo || null;
    }

    // -- computed ---------------------------------------------------------

    get computeOpen() {
        return Boolean(this.state.showCompute || this.state.compute_body);
    }

    toggleCompute() {
        this.state.showCompute = !this.computeOpen;
        if (!this.state.showCompute) {
            // Clearing the body is what clears the compute: a spec that keeps
            // the method name would declare one the generator has nothing to
            // write.
            this.state.compute_body = "";
            this.state.depends = "";
        }
    }

    // -- placement --------------------------------------------------------

    /**
     * Placement is view intent, not part of the field definition, so it lives
     * beside the spec rather than in it. It is edited here anyway because
     * "where does this show up" is the question people ask *while* adding a
     * field, not on a separate screen afterwards.
     */
    get placement() {
        return this.state.placement || this.currentType.placement || {};
    }

    setPlacement(slot, value) {
        this.state.placement = { ...this.placement, [slot]: value };
    }

    get canGroupBy() {
        return ["many2one", "selection", "date", "datetime", "boolean"].includes(
            this.state.ttype
        );
    }

    get wantsPage() {
        return ["one2many", "many2many", "html", "text"].includes(this.state.ttype);
    }

    onTypeChange(value) {
        const entry = this.props.fieldTypes.find((t) => t.value === value);
        if (!entry || !entry.enabled) {
            return;
        }
        this.state.ttype = value;
        // Placement follows the type: a long note does not belong in a list
        // column just because the char field it started as did.
        this.state.placement = { ...entry.placement };
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
            return _t(
                "Choose how %s links back to this model.",
                this.state.comodel || _t("the other model")
            );
        }
        if (
            ["selection", "reference"].includes(this.state.ttype) &&
            !this.selectionRows.filter((r) => r.value).length
        ) {
            return _t("A selection needs at least one value.");
        }
        if (this.shows("related")) {
            if (!this.state.related) {
                return _t("Choose the field this one follows.");
            }
            if (this.relatedInfo && !this.relatedInfo.ok) {
                return this.relatedInfo.reason;
            }
        }
        if (this.state.compute_body && !this.state.depends) {
            // Odoo will not recompute without it, and a stored computed field
            // that never recomputes is the worst thing this can produce:
            // correct on creation and quietly wrong from then on.
            return _t("A computed field needs the fields it reads, so Odoo knows when to recompute.");
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
        // Picker state, not field definition: the server re-derives what it
        // needs from create_inverse and would reject the rest.
        delete values.inverse;
        delete values.showCompute;
        // The resolved chain, not the panel's copy of it: `ttype` is whatever
        // the related field turned out to be.
        if (this.relatedInfo && this.relatedInfo.ok) {
            values.ttype = this.relatedInfo.ttype;
            values.comodel = this.relatedInfo.comodel || undefined;
        }
        delete values.relatedInfo;
        values.placement = { ...this.placement };
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
