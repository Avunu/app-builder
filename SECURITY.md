# Security

App Builder writes Python and XML into a directory on Odoo's `addons_path` and reloads
modules. That is the product, and it is also the whole of its risk. This file says what
that means for the people who run it, how the risk is fenced in, and how to report a
problem.

## The one thing to know

**A Builder Administrator can run arbitrary code as the Odoo process.** Treat the role
exactly as you would treat a shell account for the operating-system user Odoo runs as.

Stock Odoo does not give a database administrator that. Server actions run inside
`safe_eval`, and `base_import_module` refuses Python files, so the administrator of one
database cannot read `odoo.conf`, another database's filestore, or the server's
environment. With App Builder enabled for writing, they can: a model's Python file is
generated from what they typed, written into the addons path, and imported. "Promote to
source" does it on purpose, lifting a sandboxed server action into an ordinary module
method.

So a stolen administrator session, or an XSS against an administrator, is code execution
on the server, with everything the Odoo user can reach: `admin_passwd` and the database
credentials in `odoo.conf`, the filestore, and every other database served by the same
process.

## What stands between an administrator and the server

### 1. Writing code is off until the server's operator turns it on

The builder writes nothing, and reloads nothing, unless the process it runs in was
started with the switch on:

| where               | how                               |
| ------------------- | --------------------------------- |
| process environment | `APP_BUILDER_ENABLE_WRITE=1`      |
| `odoo.conf`         | `app_builder_enable_write = True` |

It defaults to **off**. The environment variable, when it is set, wins over `odoo.conf`,
so `APP_BUILDER_ENABLE_WRITE=0` turns writing off on a host whose shared configuration
turns it on. Accepted values are `1`, `true`, `yes` and `on`, in any case; anything else
is off.

The switch is deliberately not a system parameter, a setting, or anything else stored in
the database. Nobody can flip it from the UI or over RPC. Turning it on takes access to
the server's configuration, which is the access that already amounts to a shell.

With it off:

- every package reports itself read-only, with a sentence that names the switch;
- every operation that needs a Builder Administrator is refused with the same sentence,
  whoever asks, the superuser included: creating a package, applying a change, writing
  files, reloading, rolling back, committing, promoting code, and every edit made
  through the console;
- reading still works, so the console opens and shows what is there.

**Turn it on only where every Settings administrator is trusted with shell access to the
server**: a developer's own machine, or a build environment. Leave it off in production.

### 2. Two groups, both hidden

`Builder User` may read builder metadata. `Builder Administrator` may also change
things. Both sit in the hidden category, so neither can be granted from the Users form,
and `Settings` administrators (`base.group_system`) are Builder Administrators by
implication.

Every method of every `builder.*` model that can be reached over RPC calls one of the
two guards before it does anything else. That is checked mechanically
(`app_builder_base/tests/test_guard_coverage.py`): the test enumerates the public
methods of every builder model of every installed App Builder addon and calls each one
as an internal user in neither group. The only accepted answer is an access error; the
exceptions are listed in that file, each with its reason.

`sudo()` is not a way around the guard. Only the superuser itself (uid 1: module
installation, data loading, scheduled actions) passes without the group. Code that calls
`sudo()` on behalf of an ordinary user is still checked against that user's own groups,
so an addon that forwards a client-supplied context under `sudo()` cannot be made to
write into a package for somebody who is not a builder.

### 3. A read-only filesystem

Independently of the switch, the builder probes the package directory by creating and
removing a temporary file in it. A directory the process cannot write is a read-only
package. An immutable deployment is therefore safe by construction: a Nix-store build, a
read-only container layer, a read-only volume.

This is the strongest of the three, because it does not depend on this project's code
being right. Use it as well as the switch, not instead of it.

## What the Builder User tier can see

The split between the two groups is kept honest, but the lower tier is not a
low-privilege role and should not be handed out as one. A Builder User can:

- read the metadata of every model, field, view, menu, action, access rule, record rule
  and automation in the database, whatever their own access rights say. The console
  reads these as superuser once the guard has passed, because that is what a builder is
  for;
- read every file under a package's directory, and its git history and diff;
- read the builder's own records: packages, applies, and the file contents an apply
  backed up.

A Builder User cannot read files outside a package directory (paths are resolved and
confined to the package root), and domain previews count records as the caller, under
the caller's own access rights and record rules, not as superuser.

## Supported deployment

App Builder is built for, and tested in, this envelope:

- **One Odoo process (`workers = 0`).** A reload re-imports a package's Python in the
  process that asked for it. Other workers keep the old classes until they restart.
  Under several workers, set the package's reload mode to manual and restart after an
  apply.
- **One database per process.** The reload replaces Python modules that are global to
  the process and upgrades the module in the current database only. A second database
  with the same package installed would be left with new classes and an old schema.
  Package records are also per database while the directory is shared, so two databases
  would each keep their own apply history for the same files.
- **A writable addons path entry that is not Odoo's own**, for the environment where
  things are built. Core's directories are listed and never offered.
- **Settings administrators only.** There is no supported way to give the builder to
  anybody else.
- **`--dev=xml` is a development flag.** The builder uses it so that a view written to a
  file is live without a module upgrade. It is not meant for a production server.

The intended workflow follows from that: build in development with the switch on, review
and ship through git, deploy immutably with the switch off.

## Hardening checklist

For any server where the switch is on:

- run Odoo as a dedicated, unprivileged operating-system user, never as root;
- serve a single database from the process (`db_name` set, `list_db = False`, a
  `dbfilter` that matches one name);
- keep `odoo.conf` readable by the Odoo user only, and expect anybody who is a Builder
  Administrator to be able to read it anyway;
- give `Settings` to as few accounts as possible, and require two-factor authentication
  for them;
- do not expose the server to the internet.

For production:

- leave the switch off;
- mount the addons path read-only;
- there is no reason to uninstall the builder: with the switch off it is a viewer.

## Supported versions

Security fixes are made on the current release of the `18.0` series. Older releases are
not patched; upgrade to the latest one.

## Reporting a vulnerability

Please do not open a public issue for a security problem.

Report it privately through GitHub: on
[the repository](https://github.com/Avunu/app-builder), **Security → Report a
vulnerability**. If that is not available to you, write to the maintainer at
<kevin@avu.nu>.

Say what you found, how to reproduce it, and which version you were running. You should
have an acknowledgement within a week. Please give us a reasonable time to ship a fix
before publishing.

Reports that amount to "a Builder Administrator can run code" describe the product
rather than a flaw in it, as set out above. A way to reach that capability _without_
being a Builder Administrator, or with the switch off, is exactly what we want to hear
about.
