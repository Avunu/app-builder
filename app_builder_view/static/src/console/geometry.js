import * as compat from "./compat";
import { cardAt, cardsOf, elementsFor, instanceAt, rectFor, tabFor } from "./identity";
function instanceOf(token, root, nodes, point = null) {
  const node = nodes[token];
  if (!node || !root) {
    return null;
  }
  let instance = node.kind === "page" ? tabFor(token, root) : instanceAt(token, root, nodes, point);
  if (!instance && node.kind === "card") {
    instance = cardAt(root, point) || cardsOf(root)[0] || null;
  }
  return instance && instance.isConnected ? instance : null;
}
function outlineRect(token, root, nodes, point = null) {
  const instance = instanceOf(token, root, nodes, point);
  if (!instance) {
    return null;
  }
  const rect = rectFor(nodes[token], instance);
  return rect && (rect.width || rect.height) ? plain(rect) : null;
}
function contentElement(token, root, nodes, point = null) {
  const node = nodes[token];
  const instance = instanceOf(token, root, nodes, point);
  if (!node || !instance) {
    return null;
  }
  if (node.kind === "sheet") {
    return instance.querySelector(":scope > .o_form_sheet") || instance;
  }
  if (node.kind === "notebook") {
    return instance.querySelector(":scope > .o_notebook_headers") || instance;
  }
  if (node.kind === "page") {
    if (!instance.classList.contains("active")) {
      return null;
    }
    const notebook = instance.closest(".o_notebook");
    return notebook ? notebook.querySelector(":scope > .o_notebook_content > .tab-pane") : null;
  }
  if (node.kind === "card") {
    return instance.closest(".o_kanban_record") || instance;
  }
  return instance;
}
function contentRect(token, root, nodes, point = null) {
  const el = contentElement(token, root, nodes, point);
  if (!el) {
    return null;
  }
  const rect = el.getBoundingClientRect();
  return rect.width || rect.height ? plain(rect) : null;
}
function flowOf(el) {
  if (!el || !el.isConnected) {
    return null;
  }
  const style = window.getComputedStyle(el);
  if (!["flex", "inline-flex"].includes(style.display)) {
    return null;
  }
  return style.flexDirection.startsWith("column") ? "column" : "row";
}
function isActivePage(token, root, nodes) {
  const node = nodes[token];
  if (!node || node.kind !== "page") {
    return true;
  }
  const tab = tabFor(token, root);
  return Boolean(tab && tab.classList.contains("active"));
}
function childEntries(token, root, nodes, container) {
  const node = nodes[token];
  if (!node || !container) {
    return [];
  }
  const entries = [];
  for (const child of node.children) {
    const childNode = nodes[child];
    if (!childNode) {
      continue;
    }
    let el = null;
    if (childNode.kind === "page") {
      el = tabFor(child, root);
    } else {
      el = elementsFor(child, root, nodes).find(
        (candidate) => container.contains(candidate)
      );
    }
    if (!el || !container.contains(el)) {
      continue;
    }
    const rect = rectFor(childNode, el);
    if (!rect || !rect.width && !rect.height) {
      continue;
    }
    entries.push({ token: child, el, rect: plain(rect) });
  }
  entries.sort((a, b) => domOrder(a.el, b.el));
  return entries;
}
function tabsOf(root) {
  return root ? [...root.querySelectorAll(compat.TAB_SELECTOR)] : [];
}
function toContent(rect, scrollEl) {
  const base = scrollEl.getBoundingClientRect();
  return {
    top: rect.top - base.top + scrollEl.scrollTop,
    left: rect.left - base.left + scrollEl.scrollLeft,
    width: rect.width,
    height: rect.height
  };
}
function contains(rect, point, slack = 0) {
  return point.x >= rect.left - slack && point.x <= rect.left + rect.width + slack && point.y >= rect.top - slack && point.y <= rect.top + rect.height + slack;
}
function plain(rect) {
  return { top: rect.top, left: rect.left, width: rect.width, height: rect.height };
}
function domOrder(a, b) {
  if (a === b) {
    return 0;
  }
  const position = a.compareDocumentPosition(b);
  if (position & Node.DOCUMENT_POSITION_FOLLOWING) {
    return -1;
  }
  if (position & Node.DOCUMENT_POSITION_PRECEDING) {
    return 1;
  }
  return 0;
}
export {
  childEntries,
  contains,
  contentElement,
  contentRect,
  flowOf,
  instanceOf,
  isActivePage,
  outlineRect,
  plain,
  tabsOf,
  toContent
};
