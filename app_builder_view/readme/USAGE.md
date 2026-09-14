Open any list, form or kanban and click **Studio** in the top bar, or pick
**Edit this view** from the cog menu: the console opens full-screen on the view
you were looking at, with the record you were looking at in it. The **Studio**
app opens the console on its Home: the package, its health, the guided tiles
(Build an app, Adopt a model, Open a view, Edit menus, Changes), the models it
defines, and a getting-started checklist. The top bar's crumb — package ›
model › view — is where everything is scoped, and every pane follows it.

## The sidebar

- **Add** holds three groups of tiles: **Components** (Tabs, Columns, Group,
  Separator, Button), **New Fields** (one per field type the package can make;
  a type it cannot is shown disabled with the reason) and **Existing Fields**
  (every field of the model not yet on the view, searchable). Drag a tile onto
  the canvas: bars appear between the elements that can take it, the chip
  names the spot under the pointer — "after Email", "into Notes", "at the end
  of the sheet" — and dropping on nothing does nothing. Resting on a notebook
  tab while dragging switches to it.
- **View** edits the view's own settings, shows invisible elements when asked,
  and shows the source of what this package has written for the view together
  with its recent changes.
- **Properties** opens when you click something. It lists the element's options
  as label / control rows — the same rows for a core field and one you added —
  and, for a field, its definition: label, help, required, the values of a
  selection. A field the package owns is edited in place; a core field shows
  what it is. **Remove from view** is at the bottom, and removing a group asks
  first, with the number of fields it would take.

  A form draws a field's label only inside a group. A field dropped anywhere
  else — on the sheet, in a tab, in columns — is given a label of its own
  (`<label for>`, the way core's views do it) so it reads the same; the
  **Show label** switch under the Label row takes it away or brings it back,
  and says so when a label is not shown. The Label row itself renames a field
  you added in the database; for a field your package defines in Python it
  relabels this view only, and **Edit definition** below renames the field
  itself, on Apply.

Moving is a drag too: pick up a field, a button or a tab and drop it where it
should be; a group or a notebook is picked up by the grip on its selection
frame, so that a click on it still selects what it holds. List columns reorder
by dragging their headings, and take a dropped field between them. In a kanban
the drop zones are laid out on one card, outlined as the template's stand-in,
and a drop into any card edits the template — every card follows.

## Saving, undoing, applying

Every edit is written when it is made: **Saved** in the status pill means the
inheriting view is on disk. **Undo** and **Redo** (Ctrl+Z, Ctrl+Shift+Z) walk
the view's own history, whoever made the edits.

A **new field** on a model the package owns as Python is the one thing that
cannot be immediate: a real column needs the class re-imported. So the drop
stages the field and shows it *in place* as a pending ghost, the pill reads
"N pending · Apply", and **Apply** places everything staged in one reload.
Until then the ghost can be moved, re-anchored or discarded like anything
else. On a core model, or on an `x_` model, a new field is created and placed
at once.

## Around the view

The top bar's tabs — Home, Views, Reports, Automations, Webhooks, Access
Control, Filter Rules, Approvals, Menu, Changes — are the studio's other
surfaces, each a pane of the same console scoped to the model in front of you
(a tab that needs a model is dimmed until there is one). A record pane lists
the model's records of that kind as cards with a sentence each; **New** starts
from a template and asks only what a record cannot exist without, and the
sidebar edits the rest as label / control rows. Odoo's own form is one button,
*Advanced…*. **Changes** shows what is pending, the written files and their
drift, git with a commit box, and the apply history with roll back. The view
switcher lists the model's other views and offers to add the types the package
can scaffold. **Close** returns to where you came from, with the edits already
showing. The URL carries the pane, the package, the model and the record, so
a reload lands where you were.
