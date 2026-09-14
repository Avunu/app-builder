Open the **Studio** app. On a fresh database its Home walks you through creating
a package: a name, a place on the addons path (the first writable entry,
preferring one named `custom`), whether to start a git repository. Nothing is
written before the last button, and the review step names the files.

From then on, anything the builder assigns to that package is written to disk as
you work. Home shows the package's health — in sync, edited on disk, an apply
waiting for a restart — and the **Changes** pane shows the generated files, the
ones edited by hand, the git status with a commit box, and the apply history.

Three actions matter, on Home's sidebar and on Changes:

- **Write to disk** — re-serialize the package. Safe to run at any time; an
  unchanged package produces byte-identical files and no git diff.
- **Reload from disk** — the reverse direction. Re-reads the files into the
  database, which is also how you adopt a hand-edit.
- **Check drift** — compare the files on disk against what the builder last
  generated. A file somebody edited by hand is reported, never silently
  overwritten and never deleted.

The package list itself, and the technical lists behind the console's cards
(models, fields, views), are under **Studio → Packages** in developer mode.

## Adopt an existing model

New models are already Python. **Home → Adopt a model** is for the ones that
are not yet: an `x_` model built by an older version of the studio, or one made
by hand in Settings → Technical. Choose it, see the class the studio will write,
review, adopt. The records, the table and its data are untouched; only where
the definition lives changes.

It is lossless because the xmlids Odoo's reflection assigns to a code-defined
model are identical to the ones the studio emitted, and because the metadata is
reclassified rather than deleted. A sandboxed `compute` string is promoted to a
real method with a real `@api.depends`.

Adopting requires the package to be installed as a module (Odoo only imports
Python for installed modules) and takes effect once the package reloads, which
the studio does in process, in the same request -- under `--dev=reload` too,
where it keeps the dev server's own restart out of the way of its writes. It
closes no doors:
afterwards the model behaves like any other the builder owns, with the marked
block kept in sync and everything outside it yours.

## Servers that cannot reload in place

Under several workers, or when the package's reload mode is set to manual, an
apply writes the files and stops: the pill reads *Restart needed*, the apply is
recorded as awaiting a restart, and Odoo loads the package on the way up.
Nothing is half-applied; a rollback from that state restores the files as they
were.

## Production

The editor gates on write access to the package directory. Against a read-only
deployment it disables itself with an explanatory banner rather than failing:
build in development, ship through git, deploy immutably.
