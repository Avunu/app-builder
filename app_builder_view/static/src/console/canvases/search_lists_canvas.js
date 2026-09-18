import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { View } from "@web/views/view";
import { canvasJsClass } from "../canvas_views";
const HOST_PASSTHROUGH = ".o_control_panel, .o_group_header";
class SearchListsCanvas extends Component {
  // `static template`/`static props` both need `override`: Owl's own
  // `Component` base class (`@odoo/owl/dist/types/runtime/component.d.ts`)
  // declares both by name (`static template: string`, `static props?:
  // Schema`) directly on the class body. `static components` does not
  // get one -- it is only part of the separate `StaticComponentProperties`
  // type used for a *constructor's* shape, never a member of `Component`
  // itself, so a subclass declaring it is not overriding anything the
  // base class visibly has.
  static template = "app_builder_view.SearchListsCanvas";
  static components = { View };
  static props = { model: Object };
  /** Owl's own `Component` constructor never runs this class's own field
   * initializers before `setup()` does -- `model`/`state`/`hostRef` are
   * all first assigned there, not in a constructor, so
   * `strictPropertyInitialization` needs the definite-assignment `!`
   * on each rather than a real initial value. */
  model;
  state;
  /** `useRef`'s own return shape (`@odoo/owl`'s `hooks.d.ts`), written
   * out rather than referenced by name -- nothing in this tree exports
   * it on its own (`compat.ts`'s `DragRef` is the same shape, but named
   * and documented for a drag hook's `ref` specifically, not a plain
   * DOM ref, so reusing it here would borrow a name that means
   * something else). */
  hostRef;
  /** Memoized alongside `hostPropsCache`; see `hostProps`'s own
   * docstring for why a plain getter is not enough on its own. */
  hostPropsKey;
  /** `undefined` only until the first `hostProps` read computes it --
   * true on every mount before the getter has run once, which is a real
   * state this field can be in, not a guarantee to type around. */
  hostPropsCache;
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
    if (target instanceof Element && target.closest(HOST_PASSTHROUGH)) {
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
      showButtons: false
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
  /**
   * `_preview_for`'s own answer (`studio_view_editor.py`), narrowed out
   * of `EditingContext.preview`'s `unknown` -- this is the real reader
   * TYPING.md's own note on that field says to narrow for
   * (`console_model.ts`: "nothing converted so far reads them"). See
   * `newSharedTypes`/`wire.ts`'s `PreviewInfo`.
   */
  get preview() {
    return this.model.context && this.model.context.preview || {
      type: "",
      view_id: false,
      search_view_id: false
    };
  }
  get fieldChoices() {
    return this.search.addable || [];
  }
  get groupByChoices() {
    const present = new Set(
      (this.search.group_bys || []).map((g) => g.name.replace("group_by_", ""))
    );
    return (this.model.context && this.model.context.fields || []).filter(
      (f) => ["many2one", "selection", "boolean", "date", "datetime"].includes(f.type) && !present.has(f.name)
    );
  }
  get previewKey() {
    return `${this.preview.view_id}:${this.model.searchSerial}`;
  }
  onAddSearchField(ev) {
    const target = ev.target;
    const field = target.value;
    target.value = "";
    return this.model.addSearchElement("field", { field });
  }
  onAddGroupBy(ev) {
    const target = ev.target;
    const field = target.value;
    target.value = "";
    return this.model.addSearchElement("group_by", { field });
  }
  /**
   * Not `async`: the two branches genuinely answer different things
   * (nothing to send yet, or the mutation's own promise), and nothing
   * here awaits or chains the result -- a click handler, forwarding
   * what `addSearchElement` gives back. Unlike `moveChild`
   * (`record_pane_model.ts`, TYPING.md's own trap), this union is
   * declared with `undefined` already in it, so nothing forces the two
   * branches to unify into one `Promise` type; adding `async` here
   * would be a real behavior change (deferring the early return, and
   * everything after it, by a microtask) that nothing asks for.
   */
  onAddFilter() {
    const field = this.state.filterField;
    const condition = this.state.filterCondition || "set";
    if (!field) {
      return void 0;
    }
    this.state.filterField = "";
    return this.model.addSearchElement("filter", { field, condition });
  }
}
export {
  SearchListsCanvas
};
