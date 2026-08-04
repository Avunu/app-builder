Carries what `mail` and `sms` add to the records App Builder writes to source.

The engine depends on `base` alone, so it cannot name a field that `mail`
declares — but those fields hold real decisions. This addon installs itself
whenever both sides are present and adds them to the generated files:

- **`ir.model`** — `is_mail_thread`, `is_mail_activity`, `is_mail_blacklist`.
  Writing one of these is what gives a custom model its chatter, so a model
  that lost the flag on reload would come back with no message history and
  views that no longer load.
- **`ir.model.fields`** — `tracking`, so a field logged in the chatter still is
  after a fresh install.
- **`ir.actions.server`** — the configuration for Send Email, Send SMS, Create
  Activity and Add/Remove Followers. Without it an automation kept its type and
  lost its template, which is worse than losing the rule outright: it still
  fires.

There is nothing to configure. It is `auto_install`, and it adds no models,
views or menus of its own.
