// Interface language (docs/design/2026-11-14-workbench-ux-plan.md, section 7): English and
// Korean. `t(key)` returns the string of the current locale, or the English string when the
// locale has none, or the key itself when no locale has it (so a gap shows, it does not break).
//
// Ship terms come from the glossary (strings/glossary.js): one place, reviewed by a yard
// designer. Standard abbreviations (LBP, DWT, Cb, GM, MCR, EEDI) stay in English in all locales.
// Status words follow the draft rule: no word for "approved" or "verified" in any locale.
//
// Pure except `applyLocale`, which writes the page (tested in app/ui-tests/i18n.test.mjs).

import { EN } from './strings/en.js';
import { KO } from './strings/ko.js';
import { GLOSSARY } from './strings/glossary.js';

export const LOCALES = ['en', 'ko'];
export const DEFAULT_LOCALE = 'en';
/** The name of each locale in its own language, for the language switch. */
export const LOCALE_NAMES = { en: 'English', ko: '한국어' };

const TABLES = { en: EN, ko: KO };
let current = DEFAULT_LOCALE;

/** A supported locale code, or the default. */
export function normalizeLocale(code) {
  return LOCALES.includes(code) ? code : DEFAULT_LOCALE;
}

export function setLocale(code) {
  current = normalizeLocale(code);
  return current;
}

export function locale() {
  return current;
}

/**
 * The string for `key` in the current locale. `{name}` placeholders take values from `params`.
 * Keys that start with "term." (one item) or "terms." (a heading) read the glossary.
 */
export function t(key, params = {}) {
  // A missing key must never break a render: show nothing rather than throw.
  if (typeof key !== 'string' || !key) return '';
  const text = lookup(key, current) ?? lookup(key, DEFAULT_LOCALE) ?? key;
  return text.replace(/\{(\w+)\}/g, (match, name) => (name in params ? String(params[name]) : match));
}

/**
 * A glossary term as a label: in Korean the standard abbreviation follows the term, because
 * designers use both ("수선간장 (LBP)"). English shows the term only.
 */
export function termLabel(id) {
  const text = t(`term.${id}`);
  const abbr = GLOSSARY[id]?.abbr;
  return current !== DEFAULT_LOCALE && abbr ? `${text} (${abbr})` : text;
}

function lookup(key, code) {
  if (key.startsWith('term.')) return GLOSSARY[key.slice('term.'.length)]?.[code];
  if (key.startsWith('terms.')) {
    const entry = GLOSSARY[key.slice('terms.'.length)];
    // English has a plural heading; other locales use the one form.
    return code === 'en' ? (entry?.enPlural ?? entry?.en) : entry?.[code];
  }
  return TABLES[code][key];
}

/**
 * Write the current locale into the page: `<html lang>`, the text of every `[data-i18n]` node,
 * and the attributes named in `data-i18n-attr` ("title:key;aria-label:key").
 */
export function applyLocale(root = document) {
  const html = root.documentElement || root.ownerDocument?.documentElement;
  if (html) html.lang = current;
  for (const node of root.querySelectorAll('[data-i18n]')) node.textContent = t(node.dataset.i18n);
  for (const node of root.querySelectorAll('[data-i18n-attr]')) {
    for (const pair of node.dataset.i18nAttr.split(';')) {
      const [attribute, key] = pair.split(':').map((part) => part.trim());
      if (attribute && key) node.setAttribute(attribute, t(key));
    }
  }
}
