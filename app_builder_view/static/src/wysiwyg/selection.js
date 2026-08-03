/** @odoo-module **/
/**
 * What did the user just click?
 *
 * This answers with a *descriptor* -- "the column for user_id" -- and never
 * with an xpath. That division is deliberate and load-bearing: the arch a
 * browser receives is a per-user projection, with nodes dropped by group rights
 * and whole subviews grafted in, so a locator derived from the DOM can be wrong
 * for the next person to open the same view. `studio.view.editor.locate_target`
 * turns the descriptor into an xpath against the real definition.
 *
 * Odoo hands us the hooks for free, which is what makes this ~40 lines instead
 * of a rendering fork:
 *
 *  - Every `Field` renders its name and an `o_field_widget` class
 *    (`web/static/src/views/fields/field.js:339`, `field.xml:5`), so one
 *    selector covers form fields, list cells *and* kanban card fields.
 *  - List headers carry `data-name` (`list_renderer.xml:22`), which is what
 *    makes a column selectable by its heading rather than only by a cell.
 */

const HEADER = "th[data-name]";
const FIELD = ".o_field_widget[name]";
const BUTTON = "button[name]";
const TAB = ".o_notebook .nav-link";

/**
 * Whether a click should still reach the view after being used to select.
 *
 * Almost nothing should: a click in a list would open a record and navigate
 * away mid-edit. A notebook tab is the exception, because selecting a page you
 * cannot switch to is useless -- you would be editing a tab whose contents are
 * hidden behind the one you are looking at.
 */
export function shouldPassThrough(el) {
    return Boolean(el && el.closest && el.closest(TAB));
}

/**
 * @param {HTMLElement} el the clicked element
 * @param {string} viewType the view being edited
 * @returns {{kind: string, name?: string}} always something; the root is the
 *   honest answer for a click on empty space, and it selects the view itself.
 */
export function describeTarget(el, viewType) {
    if (!el || !el.closest) {
        return { kind: "root" };
    }

    // Heading first: it is the most deliberate way to aim at a column, and a
    // heading is not inside a field so nothing else would match it.
    const header = el.closest(HEADER);
    if (header && header.dataset.name) {
        return { kind: "column", name: header.dataset.name };
    }

    // A notebook tab, so a page can be renamed by clicking the tab that names
    // it. Core pages often carry no name attribute, and there is nothing to put
    // in a locator then -- so fall back to the tab's position, which is exactly
    // how `getpath` would index it anyway.
    const tab = el.closest(TAB);
    if (tab) {
        const name = tab.getAttribute("name");
        if (name) {
            return { kind: "page", name };
        }
        const strip = tab.closest(".nav");
        const tabs = strip ? [...strip.querySelectorAll(".nav-link")] : [tab];
        return { kind: "page", index: tabs.indexOf(tab) };
    }

    // Before fields: a button rendered inside a cell should select the button.
    const button = el.closest(BUTTON);
    if (button && button.getAttribute("name")) {
        return { kind: "button", name: button.getAttribute("name") };
    }

    const field = el.closest(FIELD);
    if (field && field.getAttribute("name")) {
        // The same node means different things in different views, and the
        // server resolves each against a different arch shape.
        return {
            kind: viewType === "list" ? "column" : "field",
            name: field.getAttribute("name"),
        };
    }

    return { kind: "root" };
}

/**
 * Whether two descriptors point at the same thing, so re-clicking the selected
 * element does not churn the sidebar.
 */
export function sameTarget(a, b) {
    return Boolean(a) && Boolean(b) && a.kind === b.kind && a.name === b.name;
}
