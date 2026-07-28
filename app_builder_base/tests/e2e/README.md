# End-to-end probes

Tests that **cannot** be `TransactionCase`s. `ir.module.module._button_immediate_function`
raises outright when `threading.current_thread().testing` is set, so every path that
installs, upgrades or reloads a module is unreachable from the normal suite. These probes
drive real registries in a real process instead.

```sh
app_builder_base/tests/e2e/run_probes.sh -c odoo.conf -t <an_installed_db>
```

## `probe_reimport.py` — is in-process re-import sound?

The load-bearing question behind the studio's "Apply" step: can a generated model file be
rewritten and re-imported inside a live process, without a server restart?

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
- **Upgrade without purging** reports success and changes nothing:
  `load_openerp_module` early-returns when `odoo.addons.<pkg>` is already in `sys.modules`,
  so the data files re-run against the *old* classes. The probe asserts this explicitly,
  because it is the failure that looks like it worked.

## The other measurement: removing a field

Dropping a field from the generated `.py` **drops its column and its data**
(`_process_end` → `IrModelFields.unlink` → `_drop_column` → `ALTER TABLE … DROP COLUMN
CASCADE`). The probe creates a row, removes the field, and confirms the loss.

That is ordinary Odoo behaviour for any addon, but it means the studio cannot let a click
do it: a destructive spec diff has to emit a `migrations/<version>/pre-migration.py` that
renames the column aside first. `migrate_module(package, 'pre')` runs long before
`_process_end`, so by then the column no longer exists under its old name and `_drop_column`
drops nothing.

## `probe_reflection.py` -- does the database agree with the source? (I2)

For a Python-backed model the old round-trip invariant is false by construction: the database
is produced by class loading, not by the files being compared. What replaces it is a
*prediction*. `expected_reflection(spec)` reimplements what `_reflect_model_params` /
`_reflect_field_params` will write, and the probe asserts the registry matches after a real
install in a fresh process.

Two things it encodes that are easy to get wrong:

- **Only the keys reflection maintains may be compared.** Those are UPSERTed to the class's
  value on every `init_models`. Everything else -- `compute`, `depends`, `domain`,
  `group_expand`, `tracking` -- keeps whatever the row happened to hold and is not a function
  of the class.
- **The comparison runs at `lang=None`.** `upsert_en` writes only the `en_US` slot of a
  translated column, so any other language compares against a value reflection never wrote.

It also asserts every field comes back `state='base'`, which is what catches a half-completed
adoption before it becomes a competing-definition bug.
