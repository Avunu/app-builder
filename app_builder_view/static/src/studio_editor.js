/** @odoo-module **/
/**
 * The studio view editor client action.
 *
 * Two things in core do most of the work for us and are worth knowing about:
 *
 *  - `viewService` busts its own cache on any write to `ir.ui.view`
 *    (web/static/src/views/view_service.js), so re-rendering the preview after
 *    an edit needs no explicit invalidation.
 *  - Every edit is sent to `studio.view.editor.apply_operation`, which produces
 *    an inheriting view rather than mutating the one being previewed. The
 *    preview therefore always shows the *combined* result, exactly as a user
 *    will see it.
 */

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { View } from "@web/views/view";
import { _t } from "@web/core/l10n/translation";

export class StudioEditor extends Component {
    static template = "app_builder_view.StudioEditor";
    static components = { View };
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");

        const params = this.props.action.context || {};
        this.state = useState({
            resModel: params.studio_model || "",
            viewId: params.studio_view_id || null,
            packageId: params.studio_package_id || null,
            views: [],
            packages: [],
            fields: [],
            nodes: [],
            selectedField: null,
            targetXpath: "",
            position: "inside",
            previewKey: 0,
            busy: false,
        });

        onWillStart(async () => {
            await this.loadPackages();
            if (this.state.resModel) {
                await this.loadViews();
                await this.reloadTarget();
            }
        });
    }

    /** Refresh both the addable-field palette and the pickable node list. */
    async reloadTarget() {
        await Promise.all([this.loadFields(), this.loadNodes()]);
    }

    async loadNodes() {
        if (!this.state.viewId) {
            this.state.nodes = [];
            return;
        }
        this.state.nodes = await this.orm.call(
            "studio.view.editor",
            "get_view_nodes",
            [this.state.viewId]
        );
        if (!this.state.nodes.some((n) => n.xpath === this.state.targetXpath)) {
            // Default to the first container, which is where a new field
            // usually belongs.
            const container = this.state.nodes.find((n) => n.container && n.depth > 0);
            this.state.targetXpath = (container || this.state.nodes[0] || {}).xpath || "";
        }
    }

    selectNode(node) {
        this.state.targetXpath = node.xpath;
        // Dropping a field *inside* a container reads naturally; next to a leaf
        // field it does not, so pick the position that matches the target.
        this.state.position = node.container ? "inside" : "after";
    }

    nodeIndent(node) {
        return `padding-left: ${8 + node.depth * 12}px`;
    }

    async loadPackages() {
        this.state.packages = await this.orm.searchRead(
            "studio.package",
            [],
            ["id", "name", "display_name_", "writable"]
        );
        const writable = this.state.packages.find((p) => p.writable);
        if (!this.state.packageId && writable) {
            this.state.packageId = writable.id;
        }
    }

    async loadViews() {
        this.state.views = await this.orm.call(
            "studio.view.editor",
            "get_editable_views",
            [this.state.resModel]
        );
        if (!this.state.viewId && this.state.views.length) {
            const form = this.state.views.find((v) => v.type === "form");
            this.state.viewId = (form || this.state.views[0]).id;
        }
    }

    async loadFields() {
        this.state.fields = await this.orm.call(
            "studio.view.editor",
            "get_addable_fields",
            [this.state.resModel, this.state.viewId]
        );
    }

    get currentView() {
        return this.state.views.find((v) => v.id === this.state.viewId);
    }

    get viewType() {
        return this.currentView ? this.currentView.type : "form";
    }

    async onModelChange(ev) {
        this.state.resModel = ev.target.value.trim();
        this.state.viewId = null;
        this.state.views = [];
        this.state.fields = [];
        if (!this.state.resModel) {
            return;
        }
        try {
            await this.loadViews();
            await this.reloadTarget();
            this.state.previewKey++;
        } catch {
            this.notification.add(
                _t("No such model, or it has no views yet."),
                { type: "warning" }
            );
        }
    }

    async onViewChange(ev) {
        this.state.viewId = parseInt(ev.target.value, 10);
        this.state.targetXpath = "";
        await this.reloadTarget();
        this.state.previewKey++;
    }

    onPackageChange(ev) {
        this.state.packageId = parseInt(ev.target.value, 10);
    }

    selectField(field) {
        this.state.selectedField = field.name === this.state.selectedField
            ? null
            : field.name;
    }

    async addSelectedField() {
        if (!this.state.selectedField) {
            this.notification.add(_t("Pick a field to add first."), {
                type: "warning",
            });
            return;
        }
        await this.applyOperation({
            type: "add_field",
            name: this.state.selectedField,
            xpath: this.state.targetXpath,
            position: this.state.position,
        });
    }

    async removeNode() {
        await this.applyOperation({
            type: "remove_node",
            xpath: this.state.targetXpath,
        });
    }

    /**
     * Send one edit to the server and refresh the preview.
     *
     * Errors are surfaced verbatim: an xpath that matches nothing, or a field
     * that does not exist on the model, is rejected by Odoo's own view
     * validator and the message it produces is the most useful thing we can
     * show.
     */
    async applyOperation(operation) {
        if (!this.state.packageId) {
            this.notification.add(
                _t("Choose a writable studio package to record the change in."),
                { type: "danger" }
            );
            return;
        }
        this.state.busy = true;
        try {
            await this.orm.call("studio.view.editor", "apply_operation", [
                this.state.viewId,
                this.state.packageId,
                operation,
            ]);
            await this.reloadTarget();
            this.state.selectedField = null;
            this.state.previewKey++;
            this.notification.add(_t("Change written to source."), {
                type: "success",
            });
        } finally {
            this.state.busy = false;
        }
    }

    openPackage() {
        if (!this.state.packageId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "studio.package",
            res_id: this.state.packageId,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("app_builder_view_editor", StudioEditor);
