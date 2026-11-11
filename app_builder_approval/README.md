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

Rules themselves are `tier.definition` records, written into
`security/<model>_approval.xml` beside that model's access rules. In-flight approvals
are not: `tier.review` holds one database's integer record ids and user ids, and none of
it means anything after a fresh install.

Install `base_tier_validation_formula` for Python conditions, `_forward` for delegation,
or `_server_action` to run something on approval — each is picked up automatically.

## Credits

**Author:** Avunu LLC

**Contributors:**

- Kevin Shenk \<kevin@avu.nu\> (https://avu.nu)

## Licence

AGPL-3. See the [repository licence](../LICENSE).
