/**
 * The composer, driven in a real browser.
 *
 * Templates are compiled by OWL in the client, not on the server, so nothing
 * short of a browser proves the composer renders at all. This tour is
 * deliberately about the shape rather than the styling: open it, stage a
 * field, see it in the tray, discard it, and confirm the count goes back.
 */

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("app_builder_composer_tour", {
    // The tour navigates here itself; start_tour's url does not override it.
    url: "/odoo/action-app_builder_model.studio_package_model_action",
    steps: () => [
        {
            content: "open the composer the way a user does",
            trigger: ".o_data_row button[name='action_compose']",
            run: "click",
        },
        {
            content: "the composer rendered",
            trigger: ".o_studio_composer .o_studio_composer_bar",
            run: () => {},
        },
        {
            content: "the field list is populated from the block",
            trigger: ".o_studio_composer .o_studio_field",
            run: () => {},
        },
        {
            content: "nothing is pending on a fresh draft",
            trigger: ".o_studio_composer_bar:not(:has(.text-bg-warning))",
            run: () => {},
        },
        {
            content: "open the new-field popover",
            trigger: ".o_studio_composer button:contains('Add a field')",
            run: "click",
        },
        {
            content: "the popover opened, already named and typed",
            trigger: ".o_studio_field_popover input[placeholder='Customer reference']",
            run: "edit Colour",
        },
        {
            content: "stage it",
            trigger: ".o_studio_field_popover button:contains('Done')",
            run: "click",
        },
        {
            content: "the tray now shows one pending change",
            trigger: ".o_studio_composer_bar .text-bg-warning:contains('1')",
            run: () => {},
        },
        {
            content: "and the field is in the list",
            trigger: ".o_studio_field:contains('Colour')",
            run: () => {},
        },
        {
            content: "review shows a diff of what would be written",
            trigger: ".o_studio_composer_bar button:contains('Review')",
            run: "click",
        },
        {
            content: "the diff mentions the staged field",
            trigger: ".o_studio_diff:contains('colour')",
            run: () => {},
        },
        {
            content: "discard it again",
            trigger: ".o_studio_composer_bar button:contains('Discard')",
            run: "click",
        },
        {
            content: "back to nothing pending",
            trigger: ".o_studio_composer_bar:not(:has(.text-bg-warning))",
            run: () => {},
        },
    ],
});
