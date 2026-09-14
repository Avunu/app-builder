/** @odoo-module **/
/**
 * A search view, edited as the three lists it really is.
 *
 * The one view type with nothing to click: a search view has no rendering
 * of its own, it furnishes another view's control panel. So its canvas is
 * the three lists -- searchable fields, filters, group-bys -- beside a real
 * list of the model *with this search view attached*, so the menus being
 * edited are the menus on screen. The host list is a `View` that loads its
 * search view the ordinary way, which is why the console clears the view
 * cache and remounts it after every edit here, and nowhere else.
 *
 * A preview, not a list to use: it renders under the same never-saving
 * class as the canvas, with no row selectors, no buttons and no opening of
 * records, and every click below its control panel is swallowed before
 * the list sees it -- an editable list would otherwise take a cell click
 * as the start of an edit, and Close would save it. The control panel is
 * let through: the search bar and the Filters and Group By menus are the
 * very thing being edited, and looking at them is the point.
 */

import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { View } from "@web/views/view";
import { canvasJsClass } from "../canvas_views";

/** What a click in the host pane may reach: the search panel, a fold. */
const HOST_PASSTHROUGH = ".o_control_panel, .o_group_header";

export class SearchListsCanvas extends Component {
    static template = "app_builder_view.SearchListsCanvas";
    static components = { View };
    static props = { model: Object };

    setup() {
        this.model = useState(this.props.model);
        this.state = useState({ filterField: "", filterCondition: "set" });
        this.hostRef = useRef("host");
        useEffect(
            (el) => {
                if (!el) {
                    return;
                }
                const onClick = (ev) => this.onHostClick(ev);
                el.addEventListener("click", onClick, true);
                return () => el.removeEventListener("click", onClick, true);
            },
            () => [this.hostRef.el]
        );
    }

    /** Stop the list acting on a click, unless it is in the search panel. */
    onHostClick(ev) {
        const target = ev.target;
        if (target.closest && target.closest(HOST_PASSTHROUGH)) {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
    }

    /**
     * The props of the host list: the real search view, an inert list. One
     * object per mount, so a re-render of the lists beside it does not
     * hand the View a new props object for nothing.
     */
    get hostProps() {
        if (this.hostPropsKey === this.previewKey) {
            return this.hostPropsCache;
        }
        this.hostPropsKey = this.previewKey;
        this.hostPropsCache = this.computeHostProps();
        return this.hostPropsCache;
    }

    computeHostProps() {
        const props = {
            resModel: this.model.modelName,
            type: "list",
            viewId: this.preview.view_id,
            searchViewId: this.preview.search_view_id,
            allowSelectors: false,
            // The control panel is let through for the search bar and its
            // menus, so the breadcrumb it would draw must not be there: its
            // previous entry is a live link out of the console.
            noBreadcrumbs: true,
            allowOpenAction: false,
            showButtons: false,
        };
        const jsClass = canvasJsClass("list");
        if (jsClass) {
            props.jsClass = jsClass;
        }
        return props;
    }

    get search() {
        return this.model.search || { fields: [], filters: [], group_bys: [], addable: [] };
    }

    get preview() {
        return (this.model.context && this.model.context.preview) || {};
    }

    get fieldChoices() {
        // Straight from the server: "not already in this view" has to ignore
        // embedded subviews, whose fields belong to another model, and that
        // rule is not one to reimplement here.
        return this.search.addable || [];
    }

    get groupByChoices() {
        const present = new Set(
            (this.search.group_bys || []).map((g) => g.name.replace("group_by_", ""))
        );
        return ((this.model.context && this.model.context.fields) || []).filter(
            (f) =>
                ["many2one", "selection", "boolean", "date", "datetime"].includes(f.type) &&
                !present.has(f.name)
        );
    }

    get previewKey() {
        return `${this.preview.view_id}:${this.model.searchSerial}`;
    }

    onAddSearchField(ev) {
        const field = ev.target.value;
        ev.target.value = "";
        return this.model.addSearchElement("field", { field });
    }

    onAddGroupBy(ev) {
        const field = ev.target.value;
        ev.target.value = "";
        return this.model.addSearchElement("group_by", { field });
    }

    onAddFilter() {
        const field = this.state.filterField;
        const condition = this.state.filterCondition || "set";
        if (!field) {
            return undefined;
        }
        this.state.filterField = "";
        return this.model.addSearchElement("filter", { field, condition });
    }
}
