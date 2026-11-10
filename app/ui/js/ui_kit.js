// Shared DOM helpers of the app shell: element lookup, chips, the error toast and path labels.

import { el, icon } from './dom.js';
import * as fmt from './format.js';

export const $ = (id) => document.getElementById(id);

export function showError(error) {
  $('toast-text').textContent = error?.message || 'Something went wrong.';
  $('toast').hidden = false;
}

/**
 * A one- or two-word chip. Longer explanations go in `title` (a tooltip), never inline.
 * `tone` uses the badge colours: accent, pass, fail, warn, draft; `dot: false` drops the
 * leading dot for chips that are labels rather than states.
 */
export function chip(text, { tone = null, status = null, title = null, dot = true, small = false } = {}) {
  const classes = ['badge'];
  if (!dot) classes.push('badge-nodot');
  if (small) classes.push('badge-small');
  const dataset = {};
  if (tone) dataset.tone = tone;
  if (status) dataset.status = status;
  // The inner span lets the text end in an ellipsis when the chip is squeezed.
  return el('span', { class: classes.join(' '), dataset, title: title || text }, el('span', { class: 'badge-text' }, text));
}

export function debounce(fn, ms) {
  let timer = 0;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

export function statusBadge(status) {
  return el('span', { class: 'badge', dataset: { status }, title: fmt.statusLabel(status) },
    el('span', { class: 'badge-text' }, fmt.statusLabel(status)));
}

export function chevron() {
  const node = icon('chevron');
  node.classList.add('chevron');
  return node;
}

/** Show `text` in the chip `node` with a badge tone, and `title` as its tooltip. */
export function setChip(node, text, tone, title) {
  node.textContent = text;
  node.title = title;
  if (tone) node.dataset.tone = tone;
  else delete node.dataset.tone;
}

export const fileName = (path) => path.split(/[\\/]/).filter(Boolean).pop() || path;
const folderName = (path) => path.slice(0, Math.max(0, path.length - fileName(path).length)).replace(/[\\/]$/, '');

/** A path as a bold file name and a muted folder that shortens with an ellipsis. */
export function pathLabel(path) {
  return el('span', { class: 'path-label', title: path },
    el('span', { class: 'path-name' }, fileName(path)),
    // The folder box is right-to-left so the ellipsis cuts the start; the left-to-right
    // marks keep the slashes of the path in their places.
    el('span', { class: 'path-folder' }, `‎${folderName(path)}‎`));
}
