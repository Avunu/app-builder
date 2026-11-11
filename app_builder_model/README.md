# App Builder: Models & Fields

Visually build models and fields that are written to source.

Build custom models and fields visually; they land in your source tree as you work.

**Build an app**, from the builder's Home: a name, the features it starts with (each
tile says what it builds and what it costs), who can use it, where its menu goes — then
one button writes the model as Python, reloads, and builds the views, the menu and the
access lines. The review step names every file. The console opens on the new model's
form with the next steps beside it.

**Adopt a model** brings a hand-made `x_` model under Python; a feature can be added to
a Python model later from Home's model list, staged and applied like any other change
(Tags and Lines are decided when the app is built: each is a second model).

Fields are dropped onto the model's own views in the console, and the class itself --
every field, in the order it is written -- is edited from the View tab. The field editor
covers every field type Odoo supports, and the picker offers what people are actually
choosing rather than what the ORM calls it: Priority arrives with its four values and
its stars, Image renders as an image, a Related field asks only which field it follows
and works the rest out.

Computed fields are there too. A compute is _data_ in Odoo — `ir.model.fields.compute`
is a sandboxed expression, not code — so one added here works immediately, with no code
file and no server restart. Write the body and say which fields it reads; the method
name is derived, because generating two answers to "what is this method called" is how a
field stops being found once its model graduates to Python.

Also adds a `Builder Package` column to the custom model and field lists (under Builder
→ Packages, in developer mode), so you can see at a glance which addon a customization
belongs to.

## Credits

**Author:** Avunu LLC

**Contributors:**

- Kevin Shenk \<kevin@avu.nu\> (https://avu.nu)

## Licence

AGPL-3. See the [repository licence](../LICENSE).
