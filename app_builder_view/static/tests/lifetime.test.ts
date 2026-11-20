/** @odoo-module **/
/**
 * What outlives its moment, and must not.
 *
 * Two things in the console are started now and finish later: the timer
 * that asks for the package's counters a moment after the last change,
 * and the wait for the Label row a new field is renamed in. Each is
 * pinned here at the edge where it used to go wrong: the timer when the
 * console has closed, the wait when the user has moved on.
 */

import {expect, getFixture, test} from "@odoo/hoot";
import {advanceTime} from "@odoo/hoot-mock";

import {focusLabelRow} from "@app_builder_view/console/drag";
import {BuilderShell} from "@app_builder_view/console/shell/shell_model";
import type {
  FieldService,
  NotificationService,
  OrmService,
  PaneModel,
} from "@app_builder_view/console/types";

// -- the shell's timer -------------------------------------------------------

function makeShell(): {shell: BuilderShell; calls: string[]} {
  const calls: string[] = [];
  const orm: OrmService = {
    call<T = unknown>(_model: string, method: string): Promise<T> {
      calls.push(method);
      return Promise.resolve([] as T);
    },
    searchRead<T = unknown>(): Promise<T[]> {
      return Promise.resolve([]);
    },
  };
  const notification: NotificationService = {add: () => undefined};
  const field = {} as FieldService;
  const env = {
    services: {orm, notification, field},
    bus: {trigger: () => undefined},
  };
  const shell = new BuilderShell(env, BuilderShell.fromParams({}));
  return {shell, calls};
}

test("several changes in a row ask for the counters once", async () => {
  const {shell, calls} = makeShell();
  shell.refreshChanges();
  shell.refreshChanges();
  shell.refreshChanges();
  expect(calls).toEqual([]);
  await advanceTime(900);
  expect(calls).toEqual(["packages"]);
});

test("a console that has closed asks the server nothing", async () => {
  const {shell, calls} = makeShell();
  shell.refreshChanges();
  shell.destroy();
  await advanceTime(900);
  expect(calls).toEqual([]);
  // Nor is anything scheduled once it has gone.
  shell.refreshChanges();
  await advanceTime(900);
  expect(calls).toEqual([]);
});

test("leaving is worth a question only while something is unfinished", () => {
  const {shell} = makeShell();
  expect(shell.hasUnfinishedWork).toBe(false);
  shell.draft.applying = true;
  expect(shell.hasUnfinishedWork).toBe(true);
  shell.draft.applying = false;
  // Only `activity` is read of a pane's model here.
  shell.paneModels["home"] = {
    activity: {busy: true, status: "saving", error: "", drag: null, applying: false},
  } as unknown as PaneModel;
  expect(shell.hasUnfinishedWork).toBe(true);
  shell.paneModels["home"] = {
    activity: {busy: false, status: "saved", error: "", drag: null, applying: false},
  } as unknown as PaneModel;
  expect(shell.hasUnfinishedWork).toBe(false);
});

// -- the wait for the Label row ------------------------------------------------

/** The Label row, as the Properties tab draws it once it has asked the
 * server what the node carries. */
function drawLabelRow(root: HTMLElement): HTMLInputElement {
  root.insertAdjacentHTML(
    "beforeend",
    `<div class="o_builder_properties">
       <div class="o_builder_row" data-row="string"><input type="text" value="Colour"/></div>
     </div>`
  );
  return root.querySelector(".o_builder_properties input") as HTMLInputElement;
}

test("the Label row is focused once it is drawn", async () => {
  const root = getFixture()!;
  focusLabelRow(root, {tries: 10, every: 50});
  await advanceTime(120);
  const input = drawLabelRow(root);
  expect(input).not.toBeFocused();
  await advanceTime(60);
  expect(input).toBeFocused();
});

test("the wait is given up when the user moves on", async () => {
  const root = getFixture()!;
  root.insertAdjacentHTML("beforeend", `<input class="elsewhere" type="text"/>`);
  const elsewhere = root.querySelector(".elsewhere") as HTMLInputElement;
  focusLabelRow(root, {tries: 10, every: 50});
  // A key pressed, a pointer put down: the cursor is theirs now.
  elsewhere.focus();
  elsewhere.dispatchEvent(new KeyboardEvent("keydown", {key: "a", bubbles: true}));
  const input = drawLabelRow(root);
  await advanceTime(600);
  expect(input).not.toBeFocused();
  expect(elsewhere).toBeFocused();
});

test("the wait can be cancelled, and a new one replaces the old", async () => {
  const root = getFixture()!;
  const cancel = focusLabelRow(root, {tries: 10, every: 50});
  cancel();
  const input = drawLabelRow(root);
  await advanceTime(600);
  expect(input).not.toBeFocused();
  // A second wait finds the row at once; the first, cancelled, stays so.
  focusLabelRow(root, {tries: 10, every: 50});
  expect(input).toBeFocused();
});
