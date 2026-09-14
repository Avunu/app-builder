/** @odoo-module **/
/**
 * View: the settings of the view itself, and what the studio has written.
 *
 * The root's option rows -- a list's inline editing, a form's title, a
 * calendar's date field -- edited the same way as any node's, against the
 * root token. Beside them, what the canvas cannot show: hidden nodes
 * (a switch that re-renders the canvas with them dimmed), the views this
 * model could still gain, the arch the studio has written for this view
 * so far, and the changes that can be undone, with who made them.
 *
 * For a model the package defines in Python, also the model itself: its
 * fields in class order -- the order they are written to Python and the
 * order a scaffolded view shows them in -- each with what the draft holds
 * for it. This is where a field that is on no view of the model, or on a
 * view other than this one, is still reachable: edited, removed, moved, or
 * added without a place to drop it on.
 */

import { Component, onWillDestroy, onWillStart, useEffect, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { optionsFor, visibleRows, writeValue } from "../options";
import { iconForType } from "../pending_widget";
import { useFieldEditor } from "./field_editor_fallback";

export class ViewTab extends Component {
    static template = "app_builder_view.ViewTab";
    static props = { model: Object };

    setup() {
        this.model = useState(this.props.model);
        this.dialog = useService("dialog");
        this.editor = useFieldEditor();
        this.state = useState({ target: null });
        onWillStart(async () => {
            // The model list reads the draft; a Python-owned model with
            // nothing staged has none until asked. A clean draft is nothing
            // to apply, so opening one here costs nothing.
            if (this.model.pythonOwned && !this.model.draft) {
                await this.model._ensureDraft();
            }
        });
        let alive = true;
        onWillDestroy(() => {
            alive = false;
        });
        useEffect(
            (root, version) => {
                this.state.target = null;
                if (!root || !version) {
                    return;
                }
                this.model.describe(root).then((target) => {
                    if (alive && this.model.archVersion === version) {
                        this.state.target = target;
                    }
                });
            },
            () => [this.model.root, this.model.archVersion]
        );
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

    get source() {
        return this.model.canvas ? this.model.canvas.source : null;
    }

    get ownershipNote() {
        if (!this.model.context) {
            return "";
        }
        return this.model.context.owned
            ? _t("This package owns this view, so changes are written into it directly.")
            : _t(
                  "This view belongs to another module. Changes become a separate " +
                      "inheriting view, so the original keeps working and upgrades " +
                      "cleanly."
              );
    }

    get recentChanges() {
        return this.model.history.undo || [];
    }

    // -- the model ------------------------------------------------------------

    get showsModel() {
        return Boolean(this.model.pythonOwned);
    }

    get modelFields() {
        return this.model.modelFields.map((field) => ({
            ...field,
            icon: iconForType(field.ttype, field.ttype),
            typeLabel: field.type_label || field.ttype || "",
        }));
    }

    pendingBadge(field) {
        switch (field.pendingKind) {
            case "added":
                return _t("new");
            case "changed":
                return _t("edited");
            case "removed":
                return _t("removed");
            default:
                return "";
        }
    }

    editorProps(anchorName, field) {
        const names = this.model.modelFields
            .map((f) => f.name)
            .filter((n) => n !== anchorName);
        return {
            field: field ? { ...field } : null,
            mode: "staged",
            fieldTypes: this.model.fieldTypes,
            existingNames: names,
            modelName: this.model.modelName,
            inverseOptions: (comodel) => this.model.inverseOptions(comodel),
            resolveRelated: (path) => this.model.resolveRelated(path),
        };
    }

    async onEditModelField(ev, entry) {
        const staged = this.model.stagedField(entry.name);
        if (!staged) {
            return;
        }
        const name = entry.name;
        this.editor.open(ev.currentTarget, {
            ...this.editorProps(name, staged),
            onSave: async (values) => {
                this.editor.close();
                await this.model.updateStaged(name, values);
            },
            onDelete: () => {
                this.editor.close();
                this.onRemoveModelField(entry);
            },
        });
    }

    onRemoveModelField(entry) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Remove field from the model"),
            body: _t(
                "Remove %s from the model? Nothing changes until Apply; then its " +
                    "column is dropped and its data kept aside by a migration. " +
                    "Discard the pending changes to take it back before that.",
                entry.string || entry.name
            ),
            confirmLabel: _t("Stage the removal"),
            confirm: () => this.model.removePending(entry.name),
            cancel: () => {},
        });
    }

    /** A new field with no place on this canvas: Apply places it. */
    onAddModelField(ev) {
        this.editor.open(ev.currentTarget, {
            ...this.editorProps(null, null),
            initial: { ttype: "char" },
            onSave: async (values) => {
                this.editor.close();
                await this.model.addModelField(values);
            },
            onDelete: null,
        });
    }

    async onMoveUp(entry) {
        const names = this.model.modelFields
            .filter((f) => f.pendingKind !== "removed")
            .map((f) => f.name);
        const index = names.indexOf(entry.name);
        if (index > 0) {
            await this.model.moveField(entry.name, names[index - 1]);
        }
    }

    async onMoveDown(entry) {
        const names = this.model.modelFields
            .filter((f) => f.pendingKind !== "removed")
            .map((f) => f.name);
        const index = names.indexOf(entry.name);
        if (index >= 0 && index < names.length - 1) {
            await this.model.moveField(entry.name, names[index + 2] || null);
        }
    }

    async onRowChange(row, rawValue) {
        if (!this.model.root || !this.state.target) {
            return;
        }
        await this.model.setAttributes(
            this.model.root,
            writeValue(row, rawValue, this.state.target)
        );
    }

    onToggle(row, ev) {
        return this.onRowChange(row, ev.target.checked);
    }

    onInput(row, ev) {
        return this.onRowChange(row, ev.target.value);
    }
}
