/** @odoo-module **/
/**
 * Add: the palette -- components, new fields, existing fields -- as tiles.
 *
 * Every tile is a thing that can be put into the view, two ways. Dragged,
 * it lands where it is dropped: the tile carries what it stands for in
 * its dataset -- `data-kind` and `data-key` -- and `drag.js` reads that
 * when it is picked up; nothing else about a drag lives here. Clicked (or
 * Enter, on a focused tile), it goes to the selection: inside a selected
 * container, after a selected leaf, at the end of the view when nothing
 * is selected -- the keyboard's way, and the one that needs no aim. A
 * disabled tile keeps its tooltip and is neither.
 *
 * The one tile a drop does not finish by itself is Button: it needs an
 * action before anything is written, so the drop hands the palette the
 * spot and the same inline form asks for the rest, then sends it there.
 *
 * Three sections, three sources. Components are a fixed list. New fields
 * come from the server's field-type catalogue for this model, which says
 * which are available and why not otherwise, and for each whether it can
 * be made live here and whether it needs its definition first. A tile of
 * a type a label suffices for -- Text, Decimal, Date -- creates at once,
 * as "New Text", and hands the cursor to the Label row; one that needs
 * more -- a relation, a selection -- opens the field editor before
 * anything is sent, so Cancel is no request. On a Python-owned model the
 * same tiles stage the field on a draft instead, and the canvas shows a
 * ghost where it will land. Existing fields are what the model has and
 * the view does not, searchable.
 *
 * A kanban has a fourth source, small and its own. A field declared at
 * the kanban's root -- `<field name="x"/>` above the templates -- loads
 * a value for the card and shows nothing, so the server counts it as
 * placed and keeps it out of the existing fields; yet dropping it into
 * the card is exactly what someone who wants to see it does, and the
 * server takes that drop. Those fields are listed here from the node
 * table, as tiles like any other existing field, under their own title.
 */

import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { focusLabelRow } from "../drag";
import { iconForType } from "../pending_widget";
import { useFieldEditor } from "./field_editor_fallback";

export const COMPONENTS = [
    { component: "page", label: _t("Tabs"), icon: "fa fa-folder-o", tags: ["form"] },
    { component: "columns", label: _t("Columns"), icon: "fa fa-columns", tags: ["form"] },
    { component: "group", label: _t("Group"), icon: "fa fa-object-group", tags: ["form"] },
    { component: "separator", label: _t("Separator"), icon: "fa fa-minus", tags: ["form"] },
    { component: "button", label: _t("Button"), icon: "fa fa-hand-pointer-o", tags: ["form"] },
];

export class AddTab extends Component {
    static template = "app_builder_view.AddTab";
    static props = { model: Object };

    setup() {
        this.model = useState(this.props.model);
        this.notification = useService("notification");
        this.rootRef = useRef("root");
        this.editor = useFieldEditor();
        this.state = useState({
            search: "",
            newButton: null,
        });
        // A field tile dropped on the canvas whose type needs the editor
        // first: open it beside the tile, on the spot the model holds.
        // When the model lets that spot go -- the view changed under it
        // -- the editor is closed rather than left asking for a field
        // with nowhere to go.
        useEffect(
            (serial) => {
                const target = this.model.fieldTarget;
                if (serial && target) {
                    this.openEditor(this.tileFor(target.ttype), target.ttype, target.label);
                } else if (!target && this.editor.isOpen && this.editorForDrop) {
                    this.editor.close();
                }
            },
            () => [this.model.fieldTarget && this.model.fieldTarget.serial]
        );
        // A Button tile dropped on the canvas: open the form for it. And
        // when the model lets the drop go -- the view changed under it --
        // a form that would still say "where it was dropped" is closed,
        // unless it is this tab sending that drop, which takes the target
        // out of the model itself and keeps the form for a refused retry.
        useEffect(
            (serial) => {
                const form = this.state.newButton;
                if (serial) {
                    this.state.newButton = { string: "", action_id: "", dropped: true };
                } else if (form && form.dropped && !form.sending) {
                    this.state.newButton = null;
                }
            },
            () => [this.model.buttonTarget && this.model.buttonTarget.serial]
        );
    }

    // -- what the palette offers ---------------------------------------------

    get components() {
        const type = this.model.viewType;
        return COMPONENTS.filter((entry) => entry.tags.includes(type));
    }

    /**
     * The New Fields tiles. On a Python-owned model every available type
     * is offered, to be staged; elsewhere only what can be made live,
     * and a type that cannot keeps the server's reason as its tooltip.
     */
    get fieldTypes() {
        const staged = this.model.pythonOwned;
        const plan = this.fieldPlan;
        return this.model.fieldTypes.map((entry) => {
            let enabled = Boolean(entry.enabled && (staged || entry.live));
            let tooltip = entry.tooltip || "";
            if (enabled) {
                tooltip = entry.needs_dialog
                    ? _t("Opens the field editor first")
                    : staged
                      ? _t("Staged until Apply")
                      : "";
            } else if (entry.enabled && !staged && plan && !plan.can_create) {
                tooltip = plan.reason || tooltip;
            } else if (entry.enabled && !enabled) {
                tooltip = tooltip || _t("Cannot be created live on this model");
            }
            return {
                ...entry,
                enabled,
                tooltip,
                icon: iconForType(entry.value, entry.ttype),
            };
        });
    }

    get existingFields() {
        const needle = (this.state.search || "").toLowerCase();
        const fields = this.model.palette || [];
        if (!needle) {
            return fields;
        }
        return fields.filter(
            (f) => f.string.toLowerCase().includes(needle) || f.name.toLowerCase().includes(needle)
        );
    }

    /**
     * The fields a kanban declares at its root and shows in no card:
     * loaded for the template, invisible on the board, and not in the
     * existing fields since the arch already names them. Searchable
     * like those, and dropped the same way.
     */
    get declaredFields() {
        if (this.model.viewType !== "kanban") {
            return [];
        }
        const nodes = this.model.nodes;
        const root = this.model.root;
        const shown = new Set();
        for (const node of Object.values(nodes)) {
            if (node.kind === "field" && node.dom && node.name) {
                shown.add(node.name);
            }
        }
        const needle = (this.state.search || "").toLowerCase();
        const fields = [];
        for (const node of Object.values(nodes)) {
            if (
                node.kind !== "field" ||
                node.dom ||
                node.parent !== root ||
                !node.name ||
                shown.has(node.name) ||
                fields.some((f) => f.name === node.name)
            ) {
                continue;
            }
            const info = node.field || {};
            const field = {
                name: node.name,
                string: info.string || node.string || node.name,
                type: info.type || "char",
            };
            if (
                !needle ||
                field.string.toLowerCase().includes(needle) ||
                field.name.toLowerCase().includes(needle)
            ) {
                fields.push(field);
            }
        }
        return fields;
    }

    iconFor(field) {
        return iconForType(field.type, field.type);
    }

    /** What the current selection means for something added now. */
    get anchorNote() {
        const token = this.model.anchorToken;
        const node = this.model.nodes[token];
        if (!node || node.kind === "root") {
            if (this.model.viewType === "kanban") {
                // The board's root takes no field a person can see: a
                // click lands in the selected part of a card, or nowhere.
                return _t("Select a place in a card first.");
            }
            return _t("Added at the end of the view.");
        }
        const what = this.model.tagFor(token);
        return node.container
            ? _t("Added inside %s.", what)
            : _t("Added just after %s.", what);
    }

    /**
     * What to say above the tiles: that fields are staged here, or why
     * none can be made. The plan's handoff to the composer is not it any
     * more -- a Python-owned model stages in place -- so its reason is
     * shown only when there is no draft road either.
     */
    get fieldPlanNote() {
        if (this.model.pythonOwned) {
            return _t(
                "%s is defined in Python, so a new field is staged here and appears after Apply.",
                this.model.modelName
            );
        }
        const plan = this.fieldPlan;
        return plan && !plan.can_create ? plan.reason || "" : "";
    }

    get fieldPlan() {
        return this.model.fieldPlan;
    }

    get canAdd() {
        return this.model.canWrite;
    }

    // -- adding ---------------------------------------------------------------

    async onComponent(entry) {
        if (!this.canAdd) {
            return;
        }
        if (entry.component === "button") {
            // Closing the form forgets a dropped spot too; the next click
            // adds at the selection, as it says.
            const open = Boolean(this.state.newButton);
            this.state.newButton = open ? null : { string: "", action_id: "" };
            if (open) {
                this.model.buttonTarget = null;
            }
            return;
        }
        await this.model.addComponent(entry.component);
    }

    async addButton() {
        const form = this.state.newButton;
        const values = { string: form.string, action_id: form.action_id };
        if (!values.action_id) {
            this.notification.add(_t("Choose the action this button should run."), {
                type: "warning",
            });
            return;
        }
        values.action_id = Number(values.action_id);
        form.sending = true;
        const result = await this.model.addButton(values);
        if (result !== undefined) {
            this.state.newButton = null;
        } else {
            form.sending = false;
        }
    }

    /**
     * A field tile clicked: the field goes to the selection. A type a
     * label suffices for is created at once as "New <Type>"; one that
     * needs more opens the editor beside the tile first.
     */
    async onFieldType(entry, ev) {
        if (!entry.enabled || !this.canAdd) {
            return;
        }
        const label = String(_t("New %s", entry.label));
        if (this.model.needsDialog(entry.value)) {
            // A click is not a drop: whatever spot a drop was holding is
            // let go of, so the editor's Done goes to the selection.
            this.model.fieldTarget = null;
            this.openEditor(ev && ev.currentTarget, entry.value, label);
            return;
        }
        await this.finishField({ ttype: entry.value, field_description: label });
    }

    /** The tile for a picker key, to anchor the editor on. */
    tileFor(ttype) {
        const root = this.rootRef.el;
        return (root && root.querySelector(`.o_studio_tile_new[data-type="${ttype}"]`)) || root;
    }

    /**
     * Open the field editor for a new field of `ttype`, beside `anchor`.
     * Its Done sends the field where the model says: the held drop
     * target when there is one, the selection otherwise.
     */
    openEditor(anchor, ttype, label) {
        if (this.editor.isOpen) {
            this.editor.close();
        }
        this.editorForDrop = Boolean(this.model.fieldTarget);
        this.editor.open(anchor || this.rootRef.el, {
            field: null,
            initial: { ttype, string: label },
            mode: this.model.pythonOwned ? "staged" : "live",
            fieldTypes: this.model.fieldTypes,
            existingNames: this.existingNames,
            modelName: this.model.modelName,
            inverseOptions: (comodel) => this.model.inverseOptions(comodel),
            resolveRelated: (path) => this.model.resolveRelated(path),
            onSave: (values) => this.onEditorSave(values),
            onDelete: null,
        });
    }

    /** Every name the model already has, so the editor picks another. */
    get existingNames() {
        const context = this.model.context || {};
        return (context.fields || []).map((field) => field.name);
    }

    async onEditorSave(values) {
        this.editor.close();
        await this.finishField(values);
    }

    /** Send the field, then put the cursor where the next edit is. */
    async finishField(values) {
        const result = await this.model.addNewField(values);
        if (result && result.created_field) {
            const root = this.rootRef.el && this.rootRef.el.closest(".o_studio_console");
            focusLabelRow(root || document.body);
        }
        return result;
    }

    async onExistingField(field) {
        if (!this.canAdd) {
            return;
        }
        await this.model.addExistingField(field.name);
    }
}
