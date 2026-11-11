import {registry} from "@web/core/registry";

/**
 * Build an app and Adopt a model, walked up to their Review step from
 * Home. The building itself reloads the server twice, which a tour
 * cannot sit through -- `test_app_builder_rpc.py` and the e2e probe
 * pin what it writes; this pins what the person is asked, what each
 * answer costs, and what Review says will land on disk.
 */
registry.category("web_tour.tours").add("app_builder_build_app_tour", {
  steps: () => [
    {
      content: "Home, on the package",
      trigger: ".o_builder_console .o_builder_home",
    },
    {
      content: "the Build an app tile",
      trigger: ".o_builder_home_tile[data-tile='build_app']:not(:disabled)",
      run: "click",
    },
    {
      content: "the flow, on its first step",
      trigger:
        ".o_builder_flow[data-flow='build_app'] .o_builder_flow_steps li.active[data-step='name']",
    },
    {
      content: "Next without a name says so",
      trigger: ".o_builder_flow_next",
      run: "click",
    },
    {
      content: "the complaint",
      trigger: ".o_builder_flow_error:contains('needs a name')",
    },
    {
      content: "name it",
      trigger: "#o_builder_app_label",
      run: "edit Tour Workshop Job",
    },
    {
      content: "the technical name follows, package-prefixed and without x_",
      trigger: "#o_builder_app_model:value('tour_build_pkg.tour_workshop_job')",
    },
    {
      content: "Next",
      trigger: ".o_builder_flow_next",
      run: "click",
    },
    {
      content: "the feature tiles, the defaults on",
      trigger: ".o_builder_flow_steps li.active[data-step='features']",
    },
    {
      content: "Tags carries its consequence",
      trigger: ".o_builder_feature_tile[data-feature='tags']:contains('second model')",
      run: "click",
    },
    {
      content: "it is on",
      trigger: ".o_builder_feature_tile[data-feature='tags'].selected",
    },
    {
      content: "Next",
      trigger: ".o_builder_flow_next",
      run: "click",
    },
    {
      content: "who can use it: Internal User is preset",
      trigger: ".o_builder_flow_steps li.active[data-step='who']",
    },
    {
      content: "the group is there",
      trigger: ".o_builder_app_groups .o_tag:contains('Internal User')",
    },
    {
      content: "Next",
      trigger: ".o_builder_flow_next",
      run: "click",
    },
    {
      content: "the menu step, an app of its own by default",
      trigger: "#o_builder_menu_new:checked",
    },
    {
      content: "under an existing app needs a parent",
      trigger: "#o_builder_menu_under",
      run: "click",
    },
    {
      content: "Next without one says so",
      trigger: ".o_builder_flow_next",
      run: "click",
    },
    {
      content: "the complaint",
      trigger: ".o_builder_flow_error:contains('which app')",
    },
    {
      content: "back to an app of its own",
      trigger: "#o_builder_menu_new",
      run: "click",
    },
    {
      content: "Next",
      trigger: ".o_builder_flow_next",
      run: "click",
    },
    {
      content: "Review lists the class, the tag model and the views",
      trigger:
        ".o_builder_flow_review .o_builder_review_files:contains('models/tour_build_pkg_tour_workshop_job.py')",
    },
    {
      content: "with the tag model",
      trigger: ".o_builder_review_files:contains('_tag.py')",
    },
    {
      content: "and the two reloads said out loud",
      trigger: ".o_builder_flow_review:contains('Two reloads')",
    },
    {
      content: "nothing is written before the button: cancel",
      trigger: ".o_builder_flow_cancel",
      run: "click",
    },
    {
      content: "back on Home",
      trigger: ".o_builder_console .o_builder_home",
    },
    // -- Adopt a model -------------------------------------------------------
    {
      content: "the Adopt tile",
      trigger: ".o_builder_home_tile[data-tile='adopt_model']:not(:disabled)",
      run: "click",
    },
    {
      content: "the hand-made model is offered, with its origin",
      trigger: ".o_builder_adopt_card[data-model='x_tour_loose']:contains('by hand')",
      run: "click",
    },
    {
      content: "Next",
      trigger: ".o_builder_flow_next",
      run: "click",
    },
    {
      content: "the preview shows the class the builder will write",
      trigger: ".o_builder_code_preview:contains('class ')",
    },
    {
      content: "with the model's field",
      trigger: ".o_builder_code_preview:contains('x_score')",
    },
    {
      content: "Next",
      trigger: ".o_builder_flow_next",
      run: "click",
    },
    {
      content: "Review names the file",
      trigger: ".o_builder_review_files:contains('models/x_tour_loose.py')",
    },
    {
      content: "cancel: nothing written",
      trigger: ".o_builder_flow_cancel",
      run: "click",
    },
    {
      content: "Home again",
      trigger: ".o_builder_console .o_builder_home",
    },
  ],
});
