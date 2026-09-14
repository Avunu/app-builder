Build custom models and fields visually; they land in your source tree as you
work.

Adds a guided **New Model** wizard that creates the model, a name field, an
access rule, list and form views, an action and a menu in one step — and assigns
all of it to a studio package, so the addon directory exists before you close
the dialog.

**Compose** opens a model in the studio console, where fields are dropped onto
the model's own views and the class itself -- every field, in the order it is
written -- is edited from the View tab. The field editor covers every field
type Odoo supports, and the picker offers what people are actually choosing
rather than what the ORM calls it: Priority arrives with its four values and
its stars, Image renders as an image, a Related field asks only which field it
follows and works the rest out.

Computed fields are there too. A compute is *data* in Odoo —
`ir.model.fields.compute` is a sandboxed expression, not code — so one added
here works immediately, with no code file and no server restart. Write the body
and say which fields it reads; the method name is derived, because generating
two answers to "what is this method called" is how a field stops being found
once its model graduates to Python.

Also adds a `Studio Package` column to the custom model and field lists, so you
can see at a glance which addon a customization belongs to.
