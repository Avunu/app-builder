import * as compat from "./compat";
const TOKEN_RE = /\bo_studio_n_(p_[A-Za-z0-9_]+|\d+)\b/;
const HEADING = "th[data-name]";
const CARD = ".o_kanban_record:not(.o_kanban_ghost)";
function ownToken(el) {
  if (!el || !el.classList) {
    return null;
  }
  const match = TOKEN_RE.exec(el.className || "");
  if (!match) {
    return null;
  }
  const captured = match[1];
  if (captured === void 0) {
    return null;
  }
  return captured.startsWith("p_") ? captured : `o_studio_n_${captured}`;
}
function classOf(token) {
  return token.startsWith("p_") ? `o_studio_n_${token}` : token;
}
function tokenOf(el, nodes) {
  if (!el || !el.closest) {
    return null;
  }
  const heading = el.closest(HEADING);
  if (heading && heading.dataset["name"]) {
    const token = columnToken(heading.dataset["name"], nodes);
    if (token) {
      return { token, el: heading };
    }
  }
  let cursor = el.nodeType === Node.ELEMENT_NODE ? el : el.parentElement;
  const wrap = cursor && cursor.closest("label.o_form_label, .o_wrap_label");
  if (wrap && !stampedBetween(cursor, wrap)) {
    const widget = compat.labelWidget(wrap);
    if (widget) {
      cursor = widget;
    }
  }
  while (cursor) {
    const token = ownToken(cursor);
    if (token) {
      return { token, el: cursor };
    }
    cursor = cursor.parentElement;
  }
  return null;
}
function stampedBetween(from, until) {
  let cursor = from;
  while (cursor) {
    if (ownToken(cursor)) {
      return true;
    }
    if (cursor === until) {
      return false;
    }
    cursor = cursor.parentElement;
  }
  return false;
}
function columnToken(name, nodes) {
  for (const [token, node] of Object.entries(nodes ?? {})) {
    if (node.kind === "column" && node.name === name) {
      return token;
    }
  }
  return null;
}
function elementsFor(token, root, nodes) {
  if (!root || !token) {
    return [];
  }
  const node = nodes && nodes[token];
  if (node && node.kind === "column" && node.name) {
    const heading = root.querySelector(`th[data-name="${cssEscape(node.name)}"]`);
    return heading ? [heading] : [];
  }
  return [...root.querySelectorAll(`.${classOf(token)}`)];
}
function rectFor(node, instance) {
  if (!instance) {
    return null;
  }
  const kind = node ? node.kind : null;
  if (kind === "field" && instance.matches(".o_field_widget, .o_form_label")) {
    return compat.rowRect(instance);
  }
  if (kind === "label" && instance.matches(".o_form_label")) {
    return compat.rowRect(instance);
  }
  if (kind === "sheet") {
    const inner = instance.querySelector(":scope > .o_form_sheet");
    return (inner || instance).getBoundingClientRect();
  }
  if (kind === "card") {
    const card = instance.closest(".o_kanban_record");
    return (card || instance).getBoundingClientRect();
  }
  return instance.getBoundingClientRect();
}
function instanceAt(token, root, nodes, point) {
  const instances = elementsFor(token, root, nodes);
  if (!point || instances.length <= 1) {
    return instances[0] || null;
  }
  const under = instances.find((el) => within(el.getBoundingClientRect(), point));
  if (under) {
    return under;
  }
  const card = cardAt(root, point);
  if (card) {
    const inCard = instances.find((el) => card.contains(el));
    if (inCard) {
      return inCard;
    }
  }
  return instances[0] ?? null;
}
function cardsOf(root) {
  return root ? [...root.querySelectorAll(CARD)] : [];
}
function cardAt(root, point) {
  if (!root || !point) {
    return null;
  }
  return cardsOf(root).find((card) => within(card.getBoundingClientRect(), point)) || null;
}
function cardOf(el) {
  return el && el.closest ? el.closest(CARD) : null;
}
function firstVisibleCard(root, scrollEl = root) {
  const cards = cardsOf(root);
  if (!cards.length) {
    return null;
  }
  const view = scrollEl ? scrollEl.getBoundingClientRect() : null;
  if (!view) {
    return cards[0] ?? null;
  }
  return cards.find((card) => {
    const r = card.getBoundingClientRect();
    return (r.width || r.height) && r.bottom > view.top && r.top < view.bottom && r.right > view.left && r.left < view.right;
  }) ?? cards[0] ?? null;
}
function centreOf(el) {
  const r = el.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}
function within(r, point) {
  return point.x >= r.left && point.x <= r.right && point.y >= r.top && point.y <= r.bottom;
}
function tabFor(token, root) {
  if (!root || !token) {
    return null;
  }
  return root.querySelector(`${compat.TAB_SELECTOR}.${token}`);
}
function describeTab(tab) {
  const name = tab.getAttribute("name") || null;
  const strip = tab.closest(".nav");
  const tabs = strip ? [...strip.querySelectorAll(".nav-link")] : [tab];
  return { name, index: tabs.indexOf(tab) };
}
function findTab(root, page) {
  if (!root || !page) {
    return null;
  }
  if (page.name) {
    const byName = root.querySelector(
      `${compat.TAB_SELECTOR}[name="${cssEscape(page.name)}"]`
    );
    if (byName) {
      return byName;
    }
  }
  const tabs = root.querySelectorAll(compat.TAB_SELECTOR);
  return tabs[page.index] || null;
}
function cssEscape(value) {
  return window.CSS && window.CSS.escape ? window.CSS.escape(value) : String(value).replace(/["\\]/g, "\\$&");
}
export {
  cardAt,
  cardOf,
  cardsOf,
  centreOf,
  classOf,
  columnToken,
  describeTab,
  elementsFor,
  findTab,
  firstVisibleCard,
  instanceAt,
  ownToken,
  rectFor,
  tabFor,
  tokenOf
};
