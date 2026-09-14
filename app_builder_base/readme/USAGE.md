Go to **Studio → Packages** and create a package. Its directory defaults to the
first writable entry on the addons path, preferring one named `custom`.

From then on, anything the builder assigns to that package is written to disk as
you work. The package form shows the generated files, whether any have been
edited by hand, and the git branch they live on.

Three buttons matter:

- **Write to disk** — re-serialize the package. Safe to run at any time; an
  unchanged package produces byte-identical files and no git diff.
- **Reload from disk** — the reverse direction. Re-reads the files into the
  database, which is also how you adopt a hand-edit.
- **Check drift** — compare the files on disk against what the builder last
  generated. A file somebody edited by hand is reported, never silently
  overwritten and never deleted.

## Adopt an existing model

New models are already Python. **Studio → Adopt Existing Model** is for the ones
that are not yet: an `x_` model built by an older version of the studio, or one
made by hand in Settings → Technical. The records, the table and its data are
untouched; only where the definition lives changes.

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

## Production

The editor gates on write access to the package directory. Against a read-only
deployment it disables itself with an explanatory banner rather than failing:
build in development, ship through git, deploy immutably.
