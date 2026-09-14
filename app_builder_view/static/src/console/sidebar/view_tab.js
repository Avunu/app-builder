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
 */

import { Component, onWillDestroy, useEffect, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { optionsFor, visibleRows, writeValue } from "../options";

export class ViewTab extends Component {
    static template = "app_builder_view.ViewTab";
    static props = { model: Object };

    setup() {
        this.model = useState(this.props.model);
        this.state = useState({ target: null });
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
