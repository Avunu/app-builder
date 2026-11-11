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

import {Component, useEffect, useRef, useState} from "@odoo/owl";
import {View} from "@web/views/view";
import {canvasJsClass} from "../canvas_views";
import type {ConsoleModel} from "../console_model";
import type {
  AddableFieldEntry,
  EditingContextFieldEntry,
  OperationResult,
  PreviewInfo,
  SearchElements,
} from "../wire";

/** What a click in the host pane may reach: the search panel, a fold. */
const HOST_PASSTHROUGH = ".o_control_panel, .o_group_header";

interface Props {
  model: ConsoleModel;
}

/**
 * The props of the host list, `View`'s own (`@web/views/view.js`'s
 * `ViewProps` typedef for the shape every view takes, plus three booleans
 * `list_controller.js`'s own `static props` adds on top of it -- this
 * canvas always previews a list, so only that view type's own extra props
 * are named here rather than every view type's). `resModel` is `string`
 * in `View`'s own typedef, but `ConsoleModel.modelName` can answer
 * `false`/`undefined` while the context is still loading -- widened to
 * match what this file actually hands the component, the same call this
 * migration has made everywhere a vendor typedef is narrower than a real
 * caller (TYPING.md, "Known traps").
 */
interface HostListProps {
  resModel: string | false | undefined;
  type: "list";
  viewId: number | false;
  searchViewId: number | false;
  allowSelectors: boolean;
  noBreadcrumbs: boolean;
  allowOpenAction: boolean;
  showButtons: boolean;
  jsClass?: string;
}

export class SearchListsCanvas extends Component<Props> {
  // `static template`/`static props` both need `override`: Owl's own
  // `Component` base class (`@odoo/owl/dist/types/runtime/component.d.ts`)
  // declares both by name (`static template: string`, `static props?:
  // Schema`) directly on the class body. `static components` does not
  // get one -- it is only part of the separate `StaticComponentProperties`
  // type used for a *constructor's* shape, never a member of `Component`
  // itself, so a subclass declaring it is not overriding anything the
  // base class visibly has.
  static override template = "app_builder_view.SearchListsCanvas";
  static components = {View};
  static override props = {model: Object};

  /** Owl's own `Component` constructor never runs this class's own field
   * initializers before `setup()` does -- `model`/`state`/`hostRef` are
   * all first assigned there, not in a constructor, so
   * `strictPropertyInitialization` needs the definite-assignment `!`
   * on each rather than a real initial value. */
  model!: ConsoleModel;
  state!: {filterField: string; filterCondition: string};
  /** `useRef`'s own return shape (`@odoo/owl`'s `hooks.d.ts`), written
   * out rather than referenced by name -- nothing in this tree exports
   * it on its own (`compat.ts`'s `DragRef` is the same shape, but named
   * and documented for a drag hook's `ref` specifically, not a plain
   * DOM ref, so reusing it here would borrow a name that means
   * something else). */
  hostRef!: {el: HTMLElement | null};

  /** Memoized alongside `hostPropsCache`; see `hostProps`'s own
   * docstring for why a plain getter is not enough on its own. */
  hostPropsKey?: string;
  /** `undefined` only until the first `hostProps` read computes it --
   * true on every mount before the getter has run once, which is a real
   * state this field can be in, not a guarantee to type around. */
  hostPropsCache?: HostListProps;

  override setup(): void {
    this.model = useState(this.props.model);
    this.state = useState({filterField: "", filterCondition: "set"});
    this.hostRef = useRef("host");
    useEffect(
      (el: HTMLElement | null) => {
        if (!el) {
          return;
        }
        const onClick = (ev: MouseEvent) => this.onHostClick(ev);
        el.addEventListener("click", onClick, true);
        return () => el.removeEventListener("click", onClick, true);
      },
      () => [this.hostRef.el]
    );
  }

  /** Stop the list acting on a click, unless it is in the search panel. */
  onHostClick(ev: MouseEvent): void {
    const target = ev.target;
    // `EventTarget` has no `.closest()` -- the original's own duck
    // check (`target.closest && ...`) is written as "does this target
    // support `.closest`", which `instanceof Element` says precisely
    // (same fix as `drag.ts`'s own `layerSelector` check, TYPING.md).
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
  get hostProps(): HostListProps | undefined {
    if (this.hostPropsKey === this.previewKey) {
      return this.hostPropsCache;
    }
    this.hostPropsKey = this.previewKey;
    this.hostPropsCache = this.computeHostProps();
    return this.hostPropsCache;
  }

  computeHostProps(): HostListProps {
    const props: HostListProps = {
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

  get search(): SearchElements {
    return this.model.search || {fields: [], filters: [], group_bys: [], addable: []};
  }

  /**
   * `_preview_for`'s own answer (`builder_view_editor.py`), narrowed out
   * of `EditingContext.preview`'s `unknown` -- this is the real reader
   * TYPING.md's own note on that field says to narrow for
   * (`console_model.ts`: "nothing converted so far reads them"). See
   * `newSharedTypes`/`wire.ts`'s `PreviewInfo`.
   */
  get preview(): PreviewInfo {
    return (
      (this.model.context && this.model.context.preview) || {
        type: "",
        view_id: false,
        search_view_id: false,
      }
    );
  }

  get fieldChoices(): AddableFieldEntry[] {
    // Straight from the server: "not already in this view" has to ignore
    // embedded subviews, whose fields belong to another model, and that
    // rule is not one to reimplement here.
    return this.search.addable || [];
  }

  get groupByChoices(): EditingContextFieldEntry[] {
    const present = new Set(
      (this.search.group_bys || []).map((g) => g.name.replace("group_by_", ""))
    );
    return ((this.model.context && this.model.context.fields) || []).filter(
      (f) =>
        ["many2one", "selection", "boolean", "date", "datetime"].includes(f.type) &&
        !present.has(f.name)
    );
  }

  get previewKey(): string {
    return `${this.preview.view_id}:${this.model.searchSerial}`;
  }

  onAddSearchField(ev: Event): Promise<OperationResult | undefined> {
    const target = ev.target as HTMLSelectElement;
    const field = target.value;
    target.value = "";
    return this.model.addSearchElement("field", {field});
  }

  onAddGroupBy(ev: Event): Promise<OperationResult | undefined> {
    const target = ev.target as HTMLSelectElement;
    const field = target.value;
    target.value = "";
    return this.model.addSearchElement("group_by", {field});
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
  onAddFilter(): Promise<OperationResult | undefined> | undefined {
    const field = this.state.filterField;
    const condition = this.state.filterCondition || "set";
    if (!field) {
      return undefined;
    }
    this.state.filterField = "";
    return this.model.addSearchElement("filter", {field, condition});
  }
}
