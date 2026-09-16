/** @odoo-module **/
/**
 * The Views pane: the real view, rendered, with everything the console can
 * do to it.
 *
 * The content is whichever component the `app_builder.canvas` registry
 * maps the view's `editable_as` to: the rendered view for anything with
 * a rendering, the three lists for a search view, and -- registered by
 * `app_builder_report`, which owns the RPCs it calls -- the printed
 * document for a report. The sidebar is the outline -- the view as a
 * tree, above -- and Add | View | Properties below it; Properties opens
 * by itself when something is selected, and the outline stays.
 *
 * The pane's model is `ConsoleModel`: the canvas, the selection, the
 * history and the palette of one view; the shell owns the package, the
 * model and the draft it reads through.
 */

import { Component, useEffect, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { StudioCanvas } from "../canvas";
import { SearchListsCanvas } from "../canvases/search_lists_canvas";
import { ConsoleModel } from "../console_model";
import { AddTab } from "../sidebar/add_tab";
import { Outline } from "../sidebar/outline";
import { PropertiesTab } from "../sidebar/properties_tab";
import { removeWithConfirm } from "../sidebar/remove_flow";
import { ViewTab } from "../sidebar/view_tab";
import { paneRegistry } from "../shell/pane_registry";

const canvasRegistry = registry.category("app_builder.canvas");
canvasRegistry.add("canvas", StudioCanvas);
canvasRegistry.add("search_lists", SearchListsCanvas);

// Empty until the staged-field step: what edits a new field's definition
// before it is created, keyed by what the field editor is for.
registry.category("app_builder.field_editor");

export const SIDEBAR_TABS = [
    { key: "add", label: _t("Add") },
    { key: "view", label: _t("View") },
    { key: "properties", label: _t("Properties") },
];

export class ViewsPane extends Component {
    static template = "app_builder_view.ViewsPane";
    static props = { shell: Object, model: { type: Object, optional: true } };

    setup() {
        this.shell = useState(this.props.shell);
        this.model = useState(this.props.model);
        this.dialog = useService("dialog");
    }

    get canvasComponent() {
        const key = this.model.editableAs;
        return canvasRegistry.contains(key) ? canvasRegistry.get(key) : StudioCanvas;
    }

    get canvasProps() {
        const props = { model: this.model };
        if (this.canvasComponent === StudioCanvas) {
            props.onRemove = (token) => this.removeFromCanvas(token);
        }
        return props;
    }

    async removeFromCanvas(token) {
        this.model.select(token);
        // A click on the frame's cross is the same request as the panel's
        // Remove button, and the outline's, and asks the same question.
        await removeWithConfirm({ model: this.model, dialog: this.dialog, token });
    }
}

export class ViewsSidebar extends Component {
    static template = "app_builder_view.ViewsSidebar";
    static components = { Outline, AddTab, ViewTab, PropertiesTab };
    static props = { shell: Object, model: { type: Object, optional: true } };

    setup() {
        this.shell = useState(this.props.shell);
        this.model = useState(this.props.model);
        this.state = useState({ tab: "add" });
        // Properties opens on selection; a remount that carries the same
        // selection across is not a selection and leaves the tab alone.
        useEffect(
            (serial) => {
                if (serial) {
                    this.state.tab = "properties";
                }
            },
            () => [this.model.selectionSerial]
        );
    }

    get tabs() {
        return SIDEBAR_TABS;
    }

    get packageMissing() {
        return Boolean(this.model.context) && !this.shell.packageId;
    }

    /** The outline lists a node table: what a rendered canvas has and a search view or a report has not. */
    get showOutline() {
        return Boolean(this.model.root) && this.model.editableAs === "canvas";
    }
}

paneRegistry.add(
    "views",
    {
        label: _t("Views"),
        icon: "fa fa-th-large",
        scope: "model",
        // A view id names its model: the cog and the systray send one
        // without the model, and the server tells the shell which it is.
        isAvailable: (ctx) => Boolean(ctx.modelName || (ctx.view && ctx.view.view_id)),
        Component: ViewsPane,
        sidebar: ViewsSidebar,
        makeModel: (shell) => new ConsoleModel(shell.env, shell),
    },
    { sequence: 10 }
);
