/** @odoo-module **/
/**
 * One catalogue row, rendered as the control its type names.
 *
 * A row is data (`catalogue.Row`): a name, a label, a type and what the
 * type needs -- choices, a comodel, a domain -- and never a function. So
 * one component turns any row into its editor: the console's own inputs
 * for the plain types, and core's own components for the ones that have
 * one (a domain, a field path, code, a record picker). The value in and
 * the value out are the surface's shapes: a many2one is `{id,
 * display_name}` in and an id out, a many2many a list of those in and a
 * list of ids out, everything else as it is.
 *
 * The one version seam is the field selector's `followRelations` flag,
 * which master renamed; it goes through `compat.fieldSelectorFollow`.
 */

import { Component, useState } from "@odoo/owl";
import { CodeEditor } from "@web/core/code_editor/code_editor";
import { Domain } from "@web/core/domain";
import { DomainSelector } from "@web/core/domain_selector/domain_selector";
import { ModelFieldSelector } from "@web/core/model_field_selector/model_field_selector";
import { MultiRecordSelector } from "@web/core/record_selectors/multi_record_selector";
import { RecordSelector } from "@web/core/record_selectors/record_selector";
import * as compat from "../compat";

export class RowEditor extends Component {
    static template = "app_builder_view.RowEditor";
    static components = {
        CodeEditor,
        DomainSelector,
        ModelFieldSelector,
        MultiRecordSelector,
        RecordSelector,
    };
    static props = {
        row: Object,
        value: { optional: true },
        disabled: { type: Boolean, optional: true },
        // `{resModel, groups}`: the subject model, and the groups on offer.
        context: { type: Object, optional: true },
        onChange: Function,
    };

    setup() {
        this.state = useState({ source: false });
    }

    get row() {
        return this.props.row;
    }

    get type() {
        return this.row.type;
    }

    get context() {
        return this.props.context || {};
    }

    get value() {
        return this.props.value;
    }

    get disabled() {
        return Boolean(this.props.disabled);
    }

    get text() {
        const value = this.value;
        return value === null || value === undefined || value === false ? "" : String(value);
    }

    /** The id a record picker shows for a many2one value. */
    get recordId() {
        const value = this.value;
        return value && typeof value === "object" ? value.id : value || false;
    }

    /** The ids a picker shows for a many2many value. */
    get recordIds() {
        return (this.value || []).map((v) => (v && typeof v === "object" ? v.id : v));
    }

    /** A comodel domain the server filled in, as the picker takes it. */
    get comodelDomain() {
        const text = this.row.comodel_domain;
        if (!text) {
            return [];
        }
        try {
            return new Domain(text).toList();
        } catch {
            return [];
        }
    }

    get fieldSelectorProps() {
        return {
            resModel: this.context.resModel,
            path: this.text,
            readonly: Boolean(this.props.disabled),
            update: (path) => this.props.onChange(path),
            ...compat.fieldSelectorFollow(this.row.follow !== false),
        };
    }

    onText(ev) {
        this.props.onChange(ev.target.value);
    }

    onToggle(ev) {
        this.props.onChange(ev.target.checked);
    }

    onSelect(ev) {
        this.props.onChange(ev.target.value);
    }

    onGroups(ev) {
        this.props.onChange([...ev.target.selectedOptions].map((option) => Number(option.value)));
    }
}
