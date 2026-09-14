/** @odoo-module **/
/**
 * A record pane: the model's records of one kind, as cards, with what
 * each does in a sentence; a properties sidebar for the one selected.
 *
 * The content slot lists the rows a server surface hands back (see
 * `record_pane_model.js`), owned by this package first, dimmed when
 * archived, badged when another module owns them or nothing does. New
 * is inline: the two or three questions a record cannot exist without,
 * from a template's `needs`, then the sidebar carries on. Odoo's own
 * form is one button in the sidebar, `Advanced…`, and never the first
 * thing on screen.
 *
 * A data-only registration (`{surface, surfaceArgs, rowActions}`) from
 * another addon resolves to these components, so a pane costs its owner
 * a few lines and no import.
 */

import { Component, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";
import * as compat from "../compat";
import { setPaneResolver } from "../shell/pane_registry";
import { RecordPaneModel } from "./record_pane_model";
import { RowEditor } from "./row_editor";

export class RecordPane extends Component {
    static template = "app_builder_view.RecordPane";
    static components = { RowEditor };
    static props = { shell: Object, model: { type: Object, optional: true } };

    setup() {
        this.shell = useState(this.props.shell);
        this.model = useState(this.props.model);
        this.dialog = useService("dialog");
        // The gate form, when the surface reports one (approvals): which
        // state field, from which states, into which, and the cancel one.
        this.state = useState({ gate: { field: "", from: [], to: [], cancel: "" } });
    }

    get label() {
        return this.model.entry.label || _t("Records");
    }

    get modelLabel() {
        return this.shell.modelLabel || this.shell.modelName;
    }

    get rows() {
        return this.model.visibleRows;
    }

    get empty() {
        return !this.model.loading && !this.model.rows.length;
    }

    get templates() {
        return this.model.templates;
    }

    get canCreate() {
        const scoped = this.model.entry.scope === "package" || Boolean(this.shell.modelName);
        return this.shell.packageWritable && scoped && !this.gateClosed;
    }

    // -- the gate: a surface whose records need the model prepared first -----------

    /** `{on, title, help, consequence, state_fields, call}` or null. */
    get gate() {
        return (this.model.extra && this.model.extra.gate) || null;
    }

    get gateClosed() {
        return Boolean(this.gate && !this.gate.on);
    }

    get gateField() {
        const gate = this.gate;
        if (!gate) {
            return null;
        }
        const fields = gate.state_fields || [];
        return fields.find((f) => f.name === this.state.gate.field) || fields[0] || null;
    }

    /** The values the chosen state field has, for the from/to pickers. */
    get gateValues() {
        const field = this.gateField;
        return field ? field.values : [];
    }

    onGateField(ev) {
        this.state.gate.field = ev.target.value;
        this.state.gate.from = [];
        this.state.gate.to = [];
        this.state.gate.cancel = "";
    }

    onGateStates(key, ev) {
        this.state.gate[key] = [...ev.target.selectedOptions].map((o) => o.value);
    }

    /** What the gate will say, before it is written. */
    get gateSentence() {
        const field = this.gateField;
        const { from, to } = this.state.gate;
        if (!field || !to.length) {
            return _t("Say which state needs approving into.");
        }
        const label = (value) => {
            const found = field.values.find((v) => v.value === value);
            return found ? found.label : value;
        };
        return _t(
            "Approval is asked for when %s goes from %s to %s.",
            field.string,
            from.length ? from.map(label).join(", ") : _t("any state"),
            to.map(label).join(", ")
        );
    }

    get gateReady() {
        return Boolean(this.gateField && this.state.gate.to.length && this.shell.packageWritable);
    }

    async onEnableGate() {
        const gate = this.gate;
        const field = this.gateField;
        if (!gate || !field || !this.gateReady) {
            return;
        }
        const { from, to, cancel } = this.state.gate;
        const result = await this.model.call(gate.call, [
            this.shell.packageId,
            this.shell.modelName,
            field.name,
            from.length ? from : false,
            to,
            cancel || false,
        ]);
        if (result !== undefined) {
            // The model's class changed under the web client: its views
            // carry buttons now.
            compat.clearViewCaches(this.env);
            this.shell.refreshChanges();
        }
    }

    /** The empty state's words: the pane's own, else the plain ones. */
    get emptyState() {
        const empty = this.model.entry.empty || {};
        return {
            title: empty.title || _t("%s of %s", this.label, this.modelLabel),
            help: empty.help || _t("Nothing here yet."),
        };
    }

    /** Indentation for a row that came back with a depth (a tree). */
    rowStyle(row) {
        return row.depth ? `padding-left: ${8 + row.depth * 18}px` : "";
    }

    /** What a card offers on hover: the pane's own actions, then the surface's. */
    actionsFor(row) {
        const actions = [];
        for (const action of this.model.entry.rowActions || []) {
            if (!action.when || action.when(row)) {
                actions.push({ ...action, run: () => action.run(this.shell, row, this.model) });
            }
        }
        if (row.editable) {
            actions.push({
                key: "remove",
                label: _t("Remove"),
                icon: "fa fa-trash-o",
                danger: true,
                run: () => this.onRemove(row),
            });
        } else if (row.in_source && this.shell.packageWritable) {
            actions.push({
                key: "duplicate",
                label: _t("Duplicate into %s", this.shell.package ? this.shell.package.name : ""),
                icon: "fa fa-clone",
                run: () => this.model.duplicate(row.id),
            });
        }
        return actions;
    }

    onSelect(row) {
        if (this.model.selectedId !== row.id) {
            this.model.select(row.id);
        }
    }

    onRemove(row) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Remove"),
            body: _t("Remove %s? It is taken out of the package's files as well.", row.title),
            confirmLabel: _t("Remove"),
            confirm: () => this.model.remove(row.id, true),
            cancel: () => {},
        });
    }

    // -- the inline New form ------------------------------------------------------

    get creating() {
        return this.model.creating;
    }

    /** The rows the inline form asks for, in catalogue order. */
    get createRows() {
        const creating = this.creating;
        if (!creating) {
            return [];
        }
        const byName = this.model.rowsByName;
        const names = [...(creating.needs || [])];
        for (const name of this.model.requiredRowNames()) {
            if (!names.includes(name)) {
                names.push(name);
            }
        }
        return names.map((name) => byName[name]).filter(Boolean);
    }

    onCreateValue(row, value) {
        this.model.creating.values[row.name] = value;
    }

    async onCreate() {
        await this.model.create();
    }

    get rowContext() {
        return {
            resModel: this.shell.modelName,
            groups: (this.model.extra && this.model.extra.groups) || [],
        };
    }
}

export class RecordSidebar extends Component {
    static template = "app_builder_view.RecordSidebar";
    static components = { RowEditor };
    static props = { shell: Object, model: { type: Object, optional: true } };

    setup() {
        this.shell = useState(this.props.shell);
        this.model = useState(this.props.model);
        this.dialog = useService("dialog");
        // Which child is unfolded; the last one added opens itself.
        this.state = useState({ openChild: false });
    }

    get record() {
        return this.model.record;
    }

    get row() {
        return this.record ? this.record.row : null;
    }

    get editable() {
        return Boolean(this.row && this.row.editable);
    }

    /** The sections that apply to the record's values, with their rows. */
    get sections() {
        const record = this.record;
        if (!record) {
            return [];
        }
        return (record.sections || [])
            .filter((section) => this.model.visible(section.visible_when, record.values))
            .map((section) => ({
                ...section,
                rows: section.rows.filter((row) =>
                    this.model.visible(row.visible_when, record.values)
                ),
            }))
            .filter((section) => section.rows.length);
    }

    get actions() {
        return (this.record && this.record.actions) || [];
    }

    get notes() {
        return (this.record && this.record.notes) || [];
    }

    /** `{valid, count, total}` or `{valid: false, reason}` when the surface counts a condition. */
    get matches() {
        return (this.record && this.record.matches) || null;
    }

    get rowContext() {
        return {
            resModel: this.shell.modelName,
            groups: (this.model.extra && this.model.extra.groups) || [],
        };
    }

    onChange(row, value) {
        this.model.write({ [row.name]: value });
    }

    // -- children -----------------------------------------------------------------

    get children() {
        return this.model.children;
    }

    /** A child's sections that apply to its values, with their rows. */
    childSections(child) {
        return (child.sections || [])
            .filter((section) => this.model.visible(section.visible_when, child.values))
            .map((section) => ({
                ...section,
                rows: section.rows.filter((row) =>
                    this.model.visible(row.visible_when, child.values)
                ),
            }))
            .filter((section) => section.rows.length);
    }

    /** The kinds a child can be added as, as objects: a pair is no key for a loop. */
    get childKinds() {
        return ((this.children && this.children.kinds) || []).map(([value, label]) => ({
            value,
            label,
        }));
    }

    childKindLabel(child) {
        const children = this.children;
        const value = child.values[children.kind_field];
        const kind = (children.kinds || []).find((k) => k[0] === value);
        return kind ? kind[1] : value;
    }

    isOpen(child) {
        return this.state.openChild === child.row.id;
    }

    toggleChild(child) {
        this.state.openChild = this.isOpen(child) ? false : child.row.id;
    }

    onChildChange(child, row, value) {
        this.model.writeChild(child.row.id, { [row.name]: value });
    }

    async onAddChild(ev) {
        const kind = ev.target.value;
        ev.target.value = "";
        if (!kind) {
            return;
        }
        const added = await this.model.addChild(kind);
        if (added && added.row) {
            this.state.openChild = added.row.id;
        }
    }

    /** Up: before the previous one. Down: before the one after the next, or last. */
    onMoveChild(child, direction) {
        const items = this.children.items;
        const index = items.findIndex((item) => item.row.id === child.row.id);
        const target = direction < 0 ? items[index - 1] : items[index + 2];
        if (direction < 0 && index === 0) {
            return;
        }
        if (direction > 0 && index >= items.length - 1) {
            return;
        }
        this.model.moveChild(child.row.id, target ? target.row.id : false);
    }

    onRemoveChild(child) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Remove"),
            body: _t("Remove this %s? The rest stay as they are.", this.children.one),
            confirmLabel: _t("Remove"),
            confirm: () => this.model.removeChild(child.row.id),
            cancel: () => {},
        });
    }

    onChildAction(child, action) {
        if (!action.enabled) {
            return;
        }
        this.model.runChild(child.row.id, action.key);
    }

    onAction(action) {
        if (!action.enabled) {
            return;
        }
        this.model.runAction(action.key);
    }

    /** Odoo's own form on the record, inside the console, capturing on save. */
    onAdvanced() {
        const advanced = this.record.advanced;
        this.dialog.add(FormViewDialog, {
            resModel: advanced.res_model,
            resId: advanced.res_id,
            context: advanced.context || {},
            title: this.row.title,
            onRecordSaved: async () => {
                await this.model.loadRows();
                await this.model.describe();
                this.shell.refreshChanges();
            },
        });
    }

    onRemove() {
        const row = this.row;
        this.dialog.add(ConfirmationDialog, {
            title: _t("Remove"),
            body: _t("Remove %s? It is taken out of the package's files as well.", row.title),
            confirmLabel: _t("Remove"),
            confirm: () => this.model.remove(row.id, true),
            cancel: () => {},
        });
    }

    onDuplicate() {
        this.model.duplicate(this.row.id);
    }
}

setPaneResolver("record", (entry) => ({
    Component: RecordPane,
    sidebar: RecordSidebar,
    makeModel: (shell) => new RecordPaneModel(shell, entry),
}));
