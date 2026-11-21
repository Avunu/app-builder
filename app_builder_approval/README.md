# App Builder: Approval rules

Turn on tier validation from the builder, and write the rules to source.

Turns approval rules on for a model, and writes them to source with everything else.

**Odoo Studio asks "which button?"; this engine answers "which state transition?"** That
is worth knowing before you start, and it is not a limitation chosen here:
`base_tier_validation` gates `write()`, firing when a record's state field moves out of
one set of values into another. There is no hook of any kind for gating a named method
or a button. For most real approvals the two coincide — the button people mean is
_Confirm_, and confirming is a state change — and where they do not, this says so rather
than generating a rule that silently never fires.

Turning it on writes **two** classes:

- the gated model gains the `tier.validation` mixin and the class attributes that
  configure it, including `_tier_validation_manual_config = False` — the default is
  `True`, which means "this model wires up its own approval UI", and a generated model
  has nobody to do that;
- `tier.definition` gains an override of `_get_tier_validation_model_names`, because the
  base implementation returns an empty list and without it your model never appears in
  the approval rule's own model picker.

## What the gate covers

The engine asks for approval when a `write()` moves a record **out of** one of the
origin states **into** one of the gated states, and at no other moment. A status field
the builder made is an ordinary writable column with a clickable statusbar, so that rule
alone would leave two ways round it, and this addon closes both:

- **Every other state is an origin.** Leave the origin states empty and they are every
  value that is not a gated one. A narrower list is refused: with only "Draft → Done"
  gated, anybody could click "In Progress" and then "Done" and never be asked. What is
  written into the class is that rule rather than today's list (`_state_from` is a
  property over a generated `_builder_gate_origins`), so a stage you add to the status
  field later is gated too. A field whose values cannot be listed (a selection built by
  a function) cannot be gated, because coverage cannot be checked there.
- **Creation is gated too.** `tier.validation` has no `create()`, so a record created
  already in a gated state would never meet the gate. The generated class carries a
  `_create` override that puts such a record through the engine's own write-time check —
  a reviewer creating it approves it in passing, anybody else is told to ask. It is
  written into your package, not inherited from this addon, so it still guards on a
  database the builder is not installed on.

Every way of creating a record counts as creating it, so once a rule matches:

- **Duplicate** starts the copy over: Odoo does not copy a field named `state` unless it
  says so, so the builder's status field puts the duplicate back at its default and
  nothing is asked. A duplicate that does land in a gated state (a status field that is
  copied, or a default passed to `copy()`) is refused for anybody who cannot approve it,
  and a reviewer who makes it approves it in passing.
- **Import** of rows in a gated state is treated the same way.
- **Module data** is the exception: records a module ships, loaded by the superuser
  while it installs or upgrades, are loaded as they are, so a rule loaded first cannot
  make a package uninstallable.

What it does not cover is the engine's own: a rule fires only for records its condition
matches before the write, and with no rule for a model nothing is asked at all.

Turning approvals on writes the `_create` override and `_builder_gate_origins`; changing
or removing the gate rewrites or removes them. A `_create` somebody else wrote in the
builder's block, or either method edited by hand, is never replaced or dropped silently:
the change is refused and says which method is in the way.

Once the gate is on, the Approvals pane says what it enforces — which status field, from
which states into which, and the cancel state — and offers **Change…** and **Turn off
approvals** (`update_gate` and `disable_gate` on `builder.approval`; both rewrite the
class in the package and reload). Both are offered only for a gate your package wrote,
in a package that can be written; otherwise the buttons are off and the pane says why.
Turning the gate off asks first, and says what it does to data:

- the rules stay where they are — they are your records — and simply stop firing;
- the reviews already asked for stay in their history;
- `validation_status`, the one stored column the mixin added, is removed with the mixin,
  and its values are kept under a renamed column, as for any confirmed removal. That is
  all turning approvals off confirms: anything else waiting to be removed from the
  package still has to be applied on its own.

## Installing

This addon is **not** installed automatically. It is Alpha, it overrides
`tier.definition` and it writes Python into your models, so it is something to choose
rather than something that arrives because `base_tier_validation` happened to be there.
Until it is installed, approval rules are not written to the generated source.

## What is written

Rules themselves are `tier.definition` records, written into
`security/<model>_approval.xml` beside that model's access rules. In-flight approvals
are not: `tier.review` holds one database's integer record ids and user ids, and none of
it means anything after a fresh install.

Install `base_tier_validation_formula` for Python conditions (its bridge,
`app_builder_approval_formula`, then installs itself), `_forward` for delegation, or
`_server_action` to run something on approval.

## Credits

**Author:** Avunu LLC

**Contributors:**

- Kevin Shenk \<kevin@avu.nu\> (https://avu.nu)

## Licence

AGPL-3. See the [repository licence](../LICENSE).
