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
import { StudioCanvas } from "../canvas";
import type { Props as StudioCanvasProps } from "../canvas";
import { SearchListsCanvas } from "../canvases/search_lists_canvas";
import { ConsoleModel } from "../console_model";
import { useService } from "../odoo";
import type { DialogService } from "../odoo";
import { paneRegistry } from "../shell/pane_registry";
import type { StudioShell } from "../shell/shell_model";
import { AddTab } from "../sidebar/add_tab";
import { Outline } from "../sidebar/outline";
import { PropertiesTab } from "../sidebar/properties_tab";
import { removeWithConfirm } from "../sidebar/remove_flow";
import { ViewTab } from "../sidebar/view_tab";
import type { Token } from "../types";

// `app_builder.canvas`'s item shape and its `declare module "registries"`
// augmentation both live in `odoo.ts` now -- "the framework boundary,
// fenced in one place" (TYPING.md, Phase 2c) -- alongside
// `app_builder.panes`/`console_tabs`/`field_editor`/`cogMenu`/`systray`/
// `view_widgets`.

const canvasRegistry = registry.category("app_builder.canvas");
canvasRegistry.add("canvas", StudioCanvas);
canvasRegistry.add("search_lists", SearchListsCanvas);

// Empty until the staged-field step: what edits a new field's definition
// before it is created, keyed by what the field editor is for.
registry.category("app_builder.field_editor");

/** One tab of the sidebar's own switcher (`ViewsSidebar.tabs`), read by
 * this file's own template (`tab.key`, `tab.label`). `label` is `_t(...)`'s
 * own lazy return type, not stringified here -- `t-esc` renders it as-is,
 * the same bare-`ReturnType<typeof _t>` idiom `console_model.ts`'s own
 * `KIND_LABELS` already uses for an identical per-key label table. */
interface SidebarTab {
    key: string;
    label: ReturnType<typeof _t>;
}

export const SIDEBAR_TABS: SidebarTab[] = [
    { key: "add", label: _t("Add") },
    { key: "view", label: _t("View") },
    { key: "properties", label: _t("Properties") },
];

/** `{shell, model}`, as `static props` below validates it -- `model` is
 * marked `optional: true` there only for Owl's own runtime schema
 * looseness (the real state before the shell's first `openPane` has
 * resolved a model); every real mount this pane's own template reaches
 * (`shell.xml`'s `t-elif="this.content"`) already has one in hand, the
 * same "every real caller passes both" reasoning `record_pane.ts`'s own
 * identical `{shell, model}` `Props` already documents. */
interface Props {
    shell: StudioShell;
    model: ConsoleModel;
}

export class ViewsPane extends Component<Props> {
    static override template = "app_builder_view.ViewsPane";
    static override props = { shell: Object, model: { type: Object, optional: true } };

    // Assigned in `setup()`, which Owl calls synchronously right after
    // construction and before the first render -- always set by the time
    // any getter or template read runs (TYPING.md's own "Known traps").
    shell!: StudioShell;
    model!: ConsoleModel;
    dialog!: DialogService;

    override setup(): void {
        this.shell = useState(this.props.shell);
        this.model = useState(this.props.model);
        this.dialog = useService("dialog");
    }

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    get canvasComponent(): typeof Component<any, any> {
        const key = this.model.editableAs;
        if (!canvasRegistry.contains(key)) {
            return StudioCanvas;
        }
        // `Registry.get`'s JSDoc leaves `defaultValue` undocumented (so TS
        // infers it as required) -- the same trap `canvas_views.ts`'s own
        // `Registry.get` call hit first (TYPING.md's "Known traps"), and
        // the same fix: `key` is already known to exist (`contains`, just
        // above), so this keeps the call at one argument instead of
        // passing an explicit `undefined` that would suppress the real
        // "missing key" throw, and `.call(canvasRegistry, ...)` rather
        // than a bare reference, since `get` reads `this.content`
        // internally and an unbound reference would call it with no
        // `this` at all.
        return (
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            (canvasRegistry.get as (key: string) => typeof Component<any, any>).call(
                canvasRegistry,
                key,
            )
        );
    }

    get canvasProps(): StudioCanvasProps {
        const props: StudioCanvasProps = { model: this.model };
        if (this.canvasComponent === StudioCanvas) {
            // `onRemove` is typed `(token: Token) => void` (`canvas.ts`'s
            // own `Props`); `removeFromCanvas` is `async`, so assigning it
            // directly would hand `Overlay`'s own fire-and-forget caller a
            // `Promise` it never awaits -- exactly what eslint's
            // `no-misused-promises` (`checksVoidReturn`) exists to catch,
            // the same finding already fixed this way at every other
            // fire-and-forget call site in this migration (TYPING.md,
            // cluster 4 wave 1). `void` makes the discard explicit instead
            // of implicit, with no change to what actually runs.
            props.onRemove = (token) => {
                void this.removeFromCanvas(token);
            };
        }
        return props;
    }

    async removeFromCanvas(token: Token): Promise<void> {
        this.model.select(token);
        // A click on the frame's cross is the same request as the panel's
        // Remove button, and the outline's, and asks the same question.
        await removeWithConfirm({ model: this.model, dialog: this.dialog, token });
    }
}

interface SidebarState {
    tab: string;
}

export class ViewsSidebar extends Component<Props> {
    static override template = "app_builder_view.ViewsSidebar";
    static components = { Outline, AddTab, ViewTab, PropertiesTab };
    static override props = { shell: Object, model: { type: Object, optional: true } };

    shell!: StudioShell;
    model!: ConsoleModel;
    state!: SidebarState;

    override setup(): void {
        this.shell = useState(this.props.shell);
        this.model = useState(this.props.model);
        this.state = useState<SidebarState>({ tab: "add" });
        // Properties opens on selection; a remount that carries the same
        // selection across is not a selection and leaves the tab alone.
        useEffect(
            (serial: number | undefined) => {
                if (serial) {
                    this.state.tab = "properties";
                }
            },
            () => [this.model.selectionSerial],
        );
    }

    get tabs(): SidebarTab[] {
        return SIDEBAR_TABS;
    }

    get packageMissing(): boolean {
        return Boolean(this.model.context) && !this.shell.packageId;
    }

    /** The outline lists a node table: what a rendered canvas has and a search view or a report has not. */
    get showOutline(): boolean {
        return Boolean(this.model.root) && this.model.editableAs === "canvas";
    }
}

paneRegistry.add(
    "views",
    {
        label: String(_t("Views")),
        icon: "fa fa-th-large",
        scope: "model",
        // A view id names its model: the cog and the systray send one
        // without the model, and the server tells the shell which it is.
        isAvailable: (ctx) => Boolean(ctx.modelName || (ctx.view && ctx.view.view_id)),
        Component: ViewsPane,
        sidebar: ViewsSidebar,
        // `PaneRegistration.makeModel` is a *property* typed as an arrow
        // function (`((shell: unknown) => PaneModel) | null`), checked
        // contravariantly under `strictFunctionTypes` -- the same shape
        // `changes_pane.ts`'s own `makeModel` already hit, and the same
        // fix: the callback's own `shell` parameter is left unannotated
        // so TS infers it from context (`unknown`), then cast once inside.
        // `StudioShell.env` (`ShellEnv`, `shell_model.ts`) structurally
        // satisfies `ConsoleModel`'s own constructor env parameter, widened
        // to carry `services.field`/`bus` once this file needed it to
        // construct a `ConsoleModel` here.
        makeModel: (shell) => new ConsoleModel((shell as StudioShell).env, shell as StudioShell),
    },
    { sequence: 10 },
);
