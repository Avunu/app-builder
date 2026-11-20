# End-to-end probes

Tests that **cannot** be `TransactionCase`s.
`ir.module.module._button_immediate_function` raises outright when
`threading.current_thread().testing` is set, so every path that installs, upgrades or
reloads a module is unreachable from the normal suite. These probes drive real
registries in a real process instead.

```sh
# in the dev shell, with nothing else running: a throwaway PostgreSQL cluster on a
# unix socket and a fresh database with app_builder installed (about two minutes)
scripts/ci-e2e.sh

# or against the dev shell's own PostgreSQL (`devenv up`), cloning a database that
# already has the addons installed
app_builder_base/tests/e2e/run_probes.sh -c odoo.conf -t <an_installed_db>
```

CI runs the first form on every pull request and every push to `develop`
(`.github/workflows/e2e.yml`, the `e2e / probes` check), and keeps the whole output as
the `e2e-probes` artifact. The terminal only shows the verdict lines; `-l <file>` keeps
the rest, and a probe that fails prints its last lines.

`run_probes.sh` takes its database server from `odoo.conf`, or from `PGHOST`, `PGPORT`
and `PGUSER` when they are set, and gives Odoo two free ports the kernel picks, so two
runs on one machine do not meet. A probe passes when it exits 0 and printed its `RESULT`
line with no `FAIL` above it.

Two things to know before running them in a checkout you are working in:

- The probes write their packages (`x_*_probe`) into the first writable directory of the
  addons path, which is this repository, and remove them again.
- The builder stages and commits what it writes when that directory is inside a git
  repository. The commit runs the repository's pre-commit hooks, and pre-commit sets
  unstaged changes aside while its hooks run: for those seconds your uncommitted edits
  are not in the working tree. They come back, but do not edit, build or copy the tree
  while the probes run. Apply also commits the package before it writes
  (`builder: before apply`) whenever the hooks let that commit through, so the branch
  you are on can gain `builder: ...` commits holding `x_*_probe` files. When it ends,
  `run_probes.sh` puts the probes' index entries back to what `HEAD` held before the
  run, and if `HEAD` moved it lists the new commits and prints the `git reset --soft`
  that drops them; it resets nothing itself. In CI the checkout is detached and thrown
  away, so none of this matters there.

## `probe_reimport.py` — is in-process re-import sound?

The load-bearing question behind the builder's "Apply" step: can a generated model file
be rewritten and re-imported inside a live process, without a server restart?

**Answer: yes, and the order is the whole trick.**

```python
# 1. purge the module's Python so it is imported again at all
del sys.modules["odoo.addons.<pkg>"]            # and every submodule
MetaModel.module_to_models.pop("<pkg>", None)   # append-only: skip this and every
                                                # class registers a second time
# 2. only now upgrade, so init_models runs and the schema follows
module.button_immediate_upgrade()
```

Two measured facts justify each half:

- **Purge without upgrading** puts the new class in the registry but leaves the table
  alone — `Registry.new` only runs `init_models` for modules marked `to upgrade`, so the
  field exists in the ORM and not in Postgres.
- **Upgrade without purging** reports success and changes nothing: `load_openerp_module`
  early-returns when `odoo.addons.<pkg>` is already in `sys.modules`, so the data files
  re-run against the _old_ classes. The probe asserts this explicitly, because it is the
  failure that looks like it worked.

## The other measurement: removing a field

Dropping a field from the generated `.py` **drops its column and its data**
(`_process_end` → `IrModelFields.unlink` → `_drop_column` →
`ALTER TABLE … DROP COLUMN CASCADE`). The probe creates a row, removes the field, and
confirms the loss.

That is ordinary Odoo behaviour for any addon, but it means the builder cannot let a
click do it: a destructive spec diff has to emit a
`migrations/<version>/pre-migration.py` that renames the column aside first.
`migrate_module(package, 'pre')` runs long before `_process_end`, so by then the column
no longer exists under its old name and `_drop_column` drops nothing.

## `probe_reflection.py` -- does the database agree with the source? (I2)

For a Python-backed model the old round-trip invariant is false by construction: the
database is produced by class loading, not by the files being compared. What replaces it
is a _prediction_. `expected_reflection(spec)` reimplements what `_reflect_model_params`
/ `_reflect_field_params` will write, and the probe asserts the registry matches after a
real install in a fresh process.

Two things it encodes that are easy to get wrong:

- **Only the keys reflection maintains may be compared.** Those are UPSERTed to the
  class's value on every `init_models`. Everything else -- `compute`, `depends`,
  `domain`, `group_expand`, `tracking` -- keeps whatever the row happened to hold and is
  not a function of the class.
- **The comparison runs at `lang=None`.** `upsert_en` writes only the `en_US` slot of a
  translated column, so any other language compares against a value reflection never
  wrote.

It also asserts every field comes back `state='base'`, which is what catches a
half-completed adoption before it becomes a competing-definition bug.

## `probe_scaffold.py` -- does one gesture produce a usable app?

The acceptance test. It builds an app with `builder.app.create_app`, then logs in as a
**plain internal user** -- no builder group, no settings access -- and asks whether they
can read the model, create a record, and see the menu.

That last question is the whole point. `IrModelAccess.check` returns True immediately
for `env.su`, so an app with missing or wrong ACLs looks perfect to the administrator
who built it and is invisible to everybody it was built for. The previous wizard shipped
exactly that: it parented the generated menu under the builder root, which is gated on
the builder group, so a manager could build "Projects", hand it to staff, and nobody
could find it. Nothing in the product would have told them.

It also checks the source is honest -- no `x_` prefix, `mail.thread` as a real mixin,
and re-rendering the file produces no diff.

## Not yet probed

- **Graduate, apply, run the action.** `builder.graduate.code.graduate(apply=True)`
  reloads the package, which no `TransactionCase` can do, so `app_builder_ui`'s suite
  compiles the generated method out of the written file and patches it onto the registry
  class instead. A probe should graduate a code action that uses each bound name (`env`,
  `record`, `json`, `log`, `action = ...`), apply for real, and run the action in a
  fresh registry.
