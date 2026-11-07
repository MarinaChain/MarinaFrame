// Small DOM helpers. Elements are built with properties and text nodes, never from HTML
// strings, so data from a run folder cannot inject markup.

const SVG_NS = 'http://www.w3.org/2000/svg';

function append(node, children) {
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

/** HTML element. `attrs` keys: class, dataset (object), on<Event> (function), others as attributes. */
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, '');
    else node.setAttribute(key, value);
  }
  return append(node, children);
}

/** Replace a node's children, skipping null, undefined and false. */
export function fill(node, ...children) {
  node.replaceChildren();
  return append(node, children);
}

/** SVG element with attributes. */
export function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== null && value !== undefined) node.setAttribute(key, value);
  }
  return append(node, children);
}

/** An icon from the sprite in index.html. */
export function icon(name) {
  return svg('svg', { class: 'icon', 'aria-hidden': 'true' }, svg('use', { href: `#i-${name}` }));
}

export function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}
