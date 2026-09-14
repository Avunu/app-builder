# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The canvas: the real view, rendered, with every node named.

The console shows the view as Odoo renders it -- the same compiler, the same
widgets, a real record -- and lets the user drop things onto it. For that
the browser needs two things it cannot make itself: the arch with a token on
every node (``canvas_stamp``), and the field descriptions the view compiler
expects, which ``get_views`` would supply for the *unstamped* view.

So the canvas does what ``get_view`` does, step by step, on our own copy of
the arch: postprocess it as the view's own model, drop what the user's groups
hide, describe the fields -- and skips the one thing ``get_view`` adds, the
registry-wide cache. The stamped arch must never be cached: the cache is
keyed on the view and the language, not on who asked or why, and a token-laden
arch in it would be served to every user of that view until the next write.
Nothing here writes, and ``test_canvas_is_pure`` holds it to that.

The tree stamped is the *combined* arch, not ``_get_view()``'s: some models
patch their arch at read time (``analytic_line.py``, ``account_move.py``),
which would shift every ordinal against the tree the editor edits. What the
canvas cannot show is stated as a known limit rather than worked around.
"""

from lxml import etree

from odoo import _, api, models
from odoo.exceptions import UserError

from ..tools import canvas_stamp, manualfield


class StudioViewEditor(models.AbstractModel):
    _inherit = "studio.view.editor"

    # Types with no rendering of their own to drop onto. A search view is
    # edited as three lists; a report is a document, previewed by
    # `studio.report`.
    EDITABLE_AS = {"qweb": "report", "search": "search_lists"}

    @api.model
    def canvas(self, view_id, options=None):
        """Everything the console needs to render one view and address it.

        ``options`` may carry ``show_invisible`` (render nodes the view
        hides), ``res_id`` (the record the user came from, shown when it
        still exists), ``package_id`` (which package's extension to report
        as the source; the suggested one otherwise) and ``draft_id``, which
        is accepted now so a client can already send it and read once
        pending fields are spliced in.

        Returned: the view, the stamped arch, the field descriptions of the
        model and of every inline subview's comodel, the version the arch
        was stamped from, the node table, and what the console shows around
        the canvas -- history, package, source, record count.
        """
        self._assert_studio_user()
        options = dict(options or {})
        view = self.env["ir.ui.view"].browse(view_id).exists()
        if not view:
            raise UserError(_("The view no longer exists."))
        package = self._canvas_package(view, options.get("package_id"))
        payload = {
            "view": {
                "id": view.id,
                "name": view.name,
                "type": view.type,
                "model": view.model,
                "mode": view.mode,
                "js_class": None,
            },
            "arch": None,
            "models": {},
            "arch_version": self.arch_version(view.id),
            "res_id": False,
            "root": None,
            "nodes": {},
            "pending": [],
            "draft_id": False,
            "editable_as": self.EDITABLE_AS.get(view.type, "canvas"),
            "source": self._canvas_source(view, package),
            "history": self.env["studio.view.edit"].stack_for(view.id),
            "package": {
                "id": package.id,
                "name": package.name,
                "writable": package.writable,
            }
            if package
            else None,
            "record_count": 0,
        }
        if not view.model or view.model not in self.env:
            # A report template: previewed as a document, not as a view.
            return payload

        Model = self.env[view.model]
        # What get_view checks first (`ir_ui_view.py:2824`): a view of a
        # model the user may not read is not theirs to look at either.
        Model.browse().check_access("read")
        root = etree.fromstring(view.get_combined_arch().encode())
        stamped = canvas_stamp.stamp(root, view.type)
        record_count = self._record_count(view.model)
        meta = canvas_stamp.prepare_for_canvas(
            stamped.arch,
            view.type,
            show_invisible=bool(options.get("show_invisible")),
            # An empty list or kanban renders nothing to drop onto; sample
            # rows give it columns and cards.
            sample=view.type in ("list", "kanban") and record_count == 0,
        )
        draft = self._canvas_draft(view, options.get("draft_id"))
        payload["draft_id"] = draft.id if draft else False
        payload["pending"] = self._splice_pending(
            stamped, root, view, draft, payload["arch_version"]
        )
        arch, models = self._postprocess_canvas(view, Model, stamped.arch)
        self._fill_hidden(stamped.nodes, arch)
        for token, node in stamped.nodes.items():
            if node["kind"] in ("field", "column"):
                node["field"] = self._canvas_field_info(
                    view.model, stamped.elements[token]
                )

        payload.update(
            {
                "arch": arch,
                "models": {
                    model: {
                        "fields": self.env[model].fields_get(
                            allfields=names,
                            attributes=Model._get_view_field_attributes(),
                        )
                    }
                    for model, names in models.items()
                },
                "res_id": self._canvas_res_id(Model, options.get("res_id")),
                "root": stamped.root,
                "nodes": stamped.nodes,
                "record_count": record_count,
            }
        )
        payload["view"]["js_class"] = meta["js_class"]
        return payload

    @api.model
    def _postprocess_canvas(self, view, Model, arch):
        """``get_view``'s pipeline on our copy: the arch string and the
        fields each model in it uses.

        Postprocessing runs on the view *as sudo*, as ``_get_view`` does --
        it resolves other models' default subviews and needs to see them
        all -- and the access-rights pass runs as the real user, since it
        is their groups that decide what the view hides. ``_postprocess_debug``
        exists from 19 on and is called when it does, so the arch string
        matches what ``get_view`` would hand the same user.
        """
        arch, models = view.sudo().postprocess_and_fields(arch, model=Model._name)
        models = Model._get_view_fields(view.type, models)
        View = self.env["ir.ui.view"]
        node = View._postprocess_access_rights(etree.fromstring(arch))
        if hasattr(View, "_postprocess_debug"):
            node = View._postprocess_debug(node)
        return etree.tostring(node, encoding="unicode").replace("\t", ""), models

    @api.model
    def _fill_hidden(self, nodes, arch):
        """Say why a node the table lists is not on the canvas.

        ``groups``: the node -- or an ancestor -- carries ``groups`` the
        user is not in, so the access-rights pass took it out of the arch
        and nothing renders it. Still in the table, still addressable: a
        manager who cannot see a field can still move it. ``invisible``: a
        literal ``invisible`` the view compiler drops; it renders when the
        canvas is asked to show hidden nodes, and the client dims it.

        From 19 on, ``_postprocess_debug`` hides a ``base.group_no_one``
        node from a non-debug user by writing a literal ``invisible`` onto
        it instead of taking it out; the node is then in the arch and still
        never renders, and "show invisible" cannot help since the rewrite
        ran before it. So a literal the final arch carries and the view's
        own attributes do not is read as ``groups`` too.
        """
        present = {}
        for element in etree.fromstring(arch.encode()).iter():
            if isinstance(element.tag, str):
                token = canvas_stamp.token_of(element)
                if token:
                    present[token] = element
        for token, node in nodes.items():
            invisible_attrs = ("invisible", "column_invisible")
            if node["kind"] == "pending":
                # A ghost is ours, spliced after the walk; the arch carries
                # it under a token of its own and nothing hides it.
                continue
            if node["dom"] and token not in present:
                node["hidden"] = "groups"
            elif any(
                node["attrs"].get(attr) in canvas_stamp.INVISIBLE_LITERALS
                for attr in invisible_attrs
            ):
                node["hidden"] = "invisible"
            elif token in present and any(
                present[token].get(attr) in canvas_stamp.INVISIBLE_LITERALS
                for attr in invisible_attrs
            ):
                node["hidden"] = "groups"

    @api.model
    def _canvas_draft(self, view, draft_id=None):
        """The draft whose pending fields this canvas shows, or an empty one.

        The one the client names when it names one, it is this model's and
        it is the user's own; otherwise the newest draft the user has on
        the model, the same one ``editing_context`` reports. Drafts are per
        user -- two people building the same model do not see each other's
        tray -- and a canvas that spliced somebody else's ghosts on request
        would be the one way around that. Never created here: looking is
        not editing, and a draft that exists only because somebody opened
        the console would have to be explained away in the tray.
        """
        Draft = self.env["studio.model.draft"]
        if draft_id:
            draft = Draft.browse(draft_id).exists()
            if (
                draft
                and draft.model == view.model
                and draft.create_uid.id == self.env.uid
            ):
                return draft
        return Draft.browse(self._open_draft_id(view.model))

    # The tag a ghost is: the one tag that renders in a form group, as a
    # list column and in a kanban card alike. A `<div>` would not.
    PENDING_TAG = "widget"
    PENDING_WIDGET = "app_builder_pending"
    PENDING_TOKEN_PREFIX = "p_"

    @api.model
    def _splice_pending(self, stamped, root, view, draft, arch_version):
        """Fields staged on a draft, drawn where they will land.

        For each field the draft is adding with an anchor on this view, a
        ``<widget name="app_builder_pending">`` goes into the stamped copy
        at the anchor -- beside the neighbour, or as the last child for
        ``inside`` -- and the node table gains an entry for it under
        ``p_<name>``, movable so it can be dragged to a new anchor and
        selectable so its properties can be opened. The copy is ours: the
        real arch is untouched and ``get_combined_arch()`` never sees a
        ghost.

        Every field the draft is adding is listed, spliced or not, so the
        tray can count them; ``placed`` says which ones the canvas shows.
        An anchor that no longer resolves -- its neighbour was removed
        since the drop -- is not guessed at: the field will be placed by
        the balanced fallback on Apply, so its ghost is drawn where that
        fallback puts a field, and says so (``resolved`` off) rather than
        vanishing from the canvas while the pill still counts it. A field
        anchored on another view of the model is listed and not drawn.

        Anchors on real nodes are resolved against the *original* tree,
        all of them, before the first ghost is spliced: a positional xpath
        counts siblings, and a ghost already in the copy would shift the
        count for the next one. An anchor on another ghost is resolved
        against the copy, where that ghost is; the anchors come in drop
        order, and a ghost is only ever anchored on one dropped earlier.
        """
        if not draft:
            return []
        by_token = {}
        for element in stamped.arch.iter():
            if isinstance(element.tag, str):
                token = canvas_stamp.token_of(element)
                if token:
                    by_token[token] = element
        token_of_element = {id(el): token for token, el in stamped.elements.items()}
        entries = draft._pending_anchored()
        # Real neighbours first, on the untouched tree.
        neighbours = {}
        for entry in entries:
            anchor = entry["anchor"]
            if (
                anchor
                and anchor.get("view_id") == view.id
                and not anchor.get("pending")
            ):
                found = self._resolve_anchor(root, anchor, arch_version)
                neighbours[entry["name"]] = (
                    token_of_element.get(id(found)) if found is not None else None
                )
        pending = []
        ghosts = {}
        for entry in entries:
            anchor = entry.pop("anchor")
            token = self.PENDING_TOKEN_PREFIX + entry["name"]
            listed = {
                **entry,
                "token": token,
                "placed": False,
                "resolved": False,
                "view_id": (anchor or {}).get("view_id") or False,
            }
            pending.append(listed)
            if not anchor or anchor.get("view_id") != view.id:
                continue
            position = anchor.get("position") or "after"
            if anchor.get("pending"):
                neighbour_token = ghosts.get(anchor["pending"])
            else:
                neighbour_token = neighbours.get(entry["name"])
            resolved = neighbour_token is not None and neighbour_token in by_token
            if resolved and (
                position != "inside"
                and stamped.nodes[neighbour_token]["parent"] is None
            ):
                # Nothing goes beside the view itself; an anchor that says
                # so is not one a drop could have minted.
                resolved = False
            if not resolved:
                neighbour_token, position = self._fallback_spot(stamped, by_token, view)
                if neighbour_token is None:
                    continue
            by_token[token] = self._splice_ghost(
                stamped,
                by_token[neighbour_token],
                neighbour_token,
                position,
                token,
                {**entry, "draft_id": draft.id, "resolved": resolved},
            )
            ghosts[entry["name"]] = token
            listed["placed"] = True
            listed["resolved"] = resolved
        return pending

    @api.model
    def _fallback_spot(self, stamped, by_token, view):
        """Where the balanced fallback would put a field of this view, as a
        ``(token, position)`` on the stamped copy, or ``(None, None)``.

        The same slot ``placement.place_in_form`` fills -- the emptiest
        column of the first two-column group in the sheet, else the end of
        the sheet -- and the end of a list; a kanban has no such slot.
        Close enough to say "here, roughly" while the ghost's caption says
        the exact place is not known.
        """
        nodes = stamped.nodes
        if view.type == "list":
            return stamped.root, "inside"
        if view.type != "form":
            return None, None
        host = next((t for t, n in nodes.items() if n["kind"] == "sheet"), stamped.root)
        columns = [
            grandchild
            for child in nodes[host]["children"]
            if nodes.get(child, {}).get("kind") == "group"
            for grandchild in nodes[child]["children"]
            if nodes.get(grandchild, {}).get("kind") == "group"
        ]
        if columns:
            target = min(
                columns,
                key=lambda t: sum(
                    1 for c in nodes[t]["children"] if nodes[c]["tag"] == "field"
                ),
            )
            return target, "inside"
        return (host, "inside") if host in by_token else (None, None)

    @api.model
    def _splice_ghost(self, stamped, neighbour, neighbour_token, position, token, info):
        """Put one ghost into the stamped copy and the node table."""
        ghost = etree.Element(self.PENDING_TAG)
        ghost.set("name", self.PENDING_WIDGET)
        ghost.set(
            "class",
            "o_studio_pending %s%s" % (canvas_stamp.TOKEN_PREFIX, token),
        )
        ghost.set("colspan", "2")
        ghost.set(
            "options",
            repr(
                {
                    "name": info["name"],
                    "label": info["label"],
                    "ttype": info["ttype"],
                    "resolved": bool(info.get("resolved", True)),
                }
            ),
        )
        if position == "inside":
            neighbour.append(ghost)
            parent_token = neighbour_token
        else:
            parent = neighbour.getparent()
            index = parent.index(neighbour) + (1 if position == "after" else 0)
            parent.insert(index, ghost)
            parent_token = stamped.nodes[neighbour_token]["parent"]
        parent_node = stamped.nodes[parent_token]
        siblings = parent_node["children"]
        if position == "inside":
            place = len(siblings)
        else:
            place = siblings.index(neighbour_token) + (1 if position == "after" else 0)
        siblings.insert(place, token)
        for index, sibling in enumerate(siblings):
            if sibling in stamped.nodes:
                stamped.nodes[sibling]["index"] = index
        stamped.nodes[token] = {
            "tag": self.PENDING_TAG,
            "name": info["name"],
            "kind": "pending",
            "parent": parent_token,
            "children": [],
            "index": place,
            "string": info["label"],
            "container": False,
            "orientation": "column",
            "accepts": [],
            "movable": True,
            "removable": True,
            "selectable": True,
            "hidden": None,
            "attrs": {},
            "dom": True,
            "field": None,
            "view_id": None,
            "label": None,
            "pending": {
                "draft_id": info["draft_id"],
                "name": info["name"],
                "ttype": info["ttype"],
                "string": info["label"],
                "resolved": bool(info.get("resolved", True)),
            },
        }
        return ghost

    @api.model
    def _resolve_anchor(self, root, anchor, arch_version):
        """The node of ``root`` an anchor is beside, or ``None``.

        The xpath as minted while the arch is the one it was minted on --
        and only then: a positional locator on a changed tree resolves to
        *some* node, the wrong one. Otherwise the neighbour is found again
        by what it was -- "the field called email" -- which survives
        anything but its own removal.
        """
        if anchor.get("pending"):
            # Beside another staged field: nothing in this tree to find.
            return None
        if anchor.get("arch_version") == arch_version and anchor.get("xpath"):
            found = self._resolve_xpath(root, anchor["xpath"])
            if found and len(found) == 1:
                return found[0]
        descriptor = anchor.get("descriptor")
        if not descriptor:
            return None
        return self._find_descriptor(root, descriptor)

    @api.model
    def _anchor_locator(self, view, root, anchor):
        """The locator an anchored placement applies, with what it expects
        to find there: ``(xpath, expectation)``, or ``None`` when the
        neighbour is gone.

        The neighbour is resolved whichever way the anchor allows -- the
        minted xpath while the arch is unchanged, the descriptor after --
        and the locator is minted from the node found, as a live drop's
        is. The expectation travels with it for the same reason a live
        drop's does: a positional path minted on the combined arch may
        name another node in the primary arch an owned view is edited
        through, and ``_assert_owned_locators`` can only refuse that when
        told what the node should be.
        """
        version = self._version_of(view.id, self._neutral_combined_arch(view))
        node = self._resolve_anchor(root, anchor, version)
        if node is None:
            return None
        return (
            self._locator_for(node, self._occurrences(root)),
            self._expectation_for(node),
        )

    @api.model
    def _pending_locator(self, root, name):
        """The locator of the real ``<field name>`` a staged neighbour has
        become, with its expectation, or ``None`` when the view does not
        show it -- or shows it only inside a subview, which is another
        model's field of the same name."""
        found = [
            node
            for node in root.iter("field")
            if node.get("name") == name
            and not any(a.tag == "field" for a in node.iterancestors())
        ]
        if len(found) != 1:
            return None
        return (
            self._locator_for(found[0], self._occurrences(root)),
            self._expectation_for(found[0]),
        )

    @api.model
    def _canvas_field_info(self, model_name, element, comodel_fields=False):
        """``_field_info`` plus where the field came from.

        The definition section of the properties panel edits a manual
        field's label in ``ir.model.fields`` and shows a core field's as a
        fact, so it has to know which it is looking at.

        ``comodel_fields`` -- every stored field of a relational field's
        comodel -- is what the panel's options need for the *selected*
        node and nothing else needs for any node, so the canvas leaves it
        out: a partner form has some thirty relational fields, and the
        field list of ``res.users`` once per each of them, on every drop,
        is tens of kilobytes that ``describe_node`` supplies on demand.
        """
        info = self._field_info(model_name, element)
        if info is not None:
            info["origin"] = self._field_origin(model_name, info["name"])
            if not comodel_fields:
                info.pop("comodel_fields", None)
        return info

    @api.model
    def _field_origin(self, model_name, field_name):
        """``manual`` for a field that lives only in ``ir.model.fields``."""
        record = self.env["ir.model.fields"]._get(model_name, field_name)
        return "manual" if record and record.state == "manual" else "core"

    @api.model
    def _canvas_res_id(self, Model, wanted):
        """The record to render: the one asked for if it exists, else any.

        A form of no record is a form of placeholders, and a canvas that
        renders the record the user was just looking at is one they
        recognise. The fallback is the first record the user can read,
        archived or not, and ``False`` when there is none -- the form then
        renders empty, which is still a form to drop onto.
        """
        if Model._abstract:
            return False
        if wanted and Model.browse(wanted).exists():
            return wanted
        return Model.with_context(active_test=False).search([], limit=1).id or False

    @api.model
    def _canvas_package(self, view, package_id=None):
        """The package a drop on this canvas would record into."""
        Package = self.env["studio.package"]
        if package_id:
            chosen = Package.browse(package_id).exists()
            if chosen:
                return chosen
        # Ownership is an xmlid lookup, which only an administrator may
        # make; a builder without that right still gets the right package.
        owner = view.sudo().studio_package_id
        return Package.browse(owner.id) if owner else Package.search([])._suggested()

    @api.model
    def _canvas_source(self, view, package):
        """The arch the console shows as "what the studio wrote", or ``None``.

        The view itself when the package owns it outright, else the
        package's extension of it when there is one already. ``None`` says
        nothing has been written yet, which the View tab shows as such.
        """
        if not package:
            return None
        # Ownership is an xmlid lookup, which only an administrator may
        # make; the fact itself is not a secret.
        if self._owns_outright(view.sudo(), package):
            source = view
        else:
            source = self.sudo()._find_extension(view, package)
            if not source:
                return None
        return {
            "view_id": source.id,
            "name": source.name,
            "owned": source == view,
            "arch": source.arch,
        }

    @api.model
    def describe_node(self, view_id, descriptor):
        """What the properties panel shows for one node.

        ``locate_target``'s answer for a token descriptor, without the xpath
        the browser must never hold, and with what the panel needs beyond
        it: where a field came from, and what of its definition can be
        edited here. A manual field's label, help and flags are rows of
        ``ir.model.fields`` and can be written; a core field's are facts
        from Python and are shown read-only.
        """
        self._assert_studio_user()
        view = self.env["ir.ui.view"].browse(view_id).exists()
        if not view:
            raise UserError(_("The view no longer exists."))
        self._assert_arch_version(view, descriptor.get("arch_version"))
        root = etree.fromstring(view.get_combined_arch().encode())
        node = self._find_descriptor(root, descriptor)
        if node is None:
            return {"found": False}
        info = (
            self._canvas_field_info(view.model, node, comodel_fields=True)
            if view.model
            else None
        )
        return {
            "found": True,
            "tag": node.tag,
            "attrs": dict(node.attrib),
            "field": info,
            "definition": self._field_definition(view.model, info) if info else None,
        }

    # What a manual field's definition lets the panel change.
    MANUAL_FIELD_EDITABLE = (
        "field_description",
        "help",
        "required",
        "readonly",
        "index",
    )

    @api.model
    def _field_definition(self, model_name, info):
        """The model-level facts of a field, and which of them are editable."""
        record = self.env["ir.model.fields"]._get(model_name, info["name"])
        if not record:
            return None
        editable = []
        if info["origin"] == "manual":
            editable = list(self.MANUAL_FIELD_EDITABLE)
            if record.ttype in manualfield.TRANSLATABLE:
                editable.append("translate")
            if record.ttype == "selection":
                editable.append("selection")
        values = {
            "field_description": record.field_description,
            "help": record.help or "",
            "required": bool(record.required),
            "readonly": bool(record.readonly),
            "index": bool(record.index),
            "translate": bool(record.translate),
            "ttype": record.ttype,
            "relation": record.relation or False,
        }
        if record.ttype == "selection":
            values["selection"] = [
                {"value": s.value, "label": s.name, "sequence": s.sequence}
                for s in record.selection_ids
            ]
        return {"origin": info["origin"], "editable": editable, "values": values}
