// The static shell of index.html (js/strings/en.js, js/strings/ko.js): every data-i18n key of
// the page exists in both tables, no data-i18n node holds a child element (applyLocale sets
// textContent, which would delete it), and the English table text equals the HTML text.
// Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { EN } from '../ui/js/strings/en.js';
import { KO } from '../ui/js/strings/ko.js';

const html = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'ui', 'index.html'), 'utf8');

/** Element-by-element matches of the HTML, so nothing is read across element boundaries. */
function elementsWith(attribute) {
  const pattern = new RegExp(`<([a-z][a-z0-9-]*)((?:[^>"]|"[^"]*")*\\b${attribute}="([^"]*)"(?:[^>"]|"[^"]*")*)>`, 'g');
  const found = [];
  for (const match of html.matchAll(pattern)) found.push({ tag: match[1], attrs: match[2], value: match[3] });
  return found;
}

/** The value of one attribute inside an opening tag, or null. */
function attributeOf(attrs, name) {
  const match = new RegExp(`\\b${name}="([^"]*)"`).exec(attrs);
  return match ? match[1] : null;
}

test('every data-i18n key of the page exists in both string tables', () => {
  const keys = elementsWith('data-i18n').map((node) => node.value);
  assert.ok(keys.length > 60, `expected the whole shell, found ${keys.length} keys`);
  for (const key of new Set(keys)) {
    assert.ok(key in EN, `missing in en.js: ${key}`);
    assert.ok(key in KO, `missing in ko.js: ${key}`);
  }
});

test('every data-i18n-attr key of the page exists in both string tables', () => {
  const keys = elementsWith('data-i18n-attr').flatMap((node) =>
    node.value.split(';').map((pair) => pair.split(':')[1].trim()));
  for (const key of new Set(keys)) {
    assert.ok(key in EN, `missing in en.js: ${key}`);
    assert.ok(key in KO, `missing in ko.js: ${key}`);
  }
});

test('no data-i18n node holds a child element, so applyLocale cannot delete one', () => {
  for (const node of elementsWith('data-i18n')) {
    // The element's full span: from its opening tag to the next closing tag of the same name,
    // or to its own end when the HTML writes it self-closed (void elements have no text).
    const open = new RegExp(`<${node.tag}[^>]*\\bdata-i18n="${node.value}"[^>]*>`, 'g');
    for (const tag of html.matchAll(open)) {
      const rest = html.slice(tag.index + tag[0].length);
      const inner = rest.slice(0, rest.indexOf(`</${node.tag}>`) + 2 + node.tag.length);
      assert.doesNotMatch(inner, /<[a-zA-Z]/,
        `shell key "${node.value}" wraps an element; put data-i18n on a span around the text instead`);
    }
  }
});

test('the English table text equals the HTML text for every data-i18n key', () => {
  for (const node of elementsWith('data-i18n')) {
    const pattern = new RegExp(`<${node.tag}([^>]*)\\bdata-i18n="${node.value}"([^>]*)>([^<]*)</${node.tag}>`, 'g');
    const matches = [...html.matchAll(pattern)];
    assert.ok(matches.length > 0, `no text content found for "${node.value}"`);
    for (const match of matches) {
      const text = match[3].trim();
      if (text) assert.equal(EN[node.value], text, `HTML text differs for "${node.value}"`);
    }
  }
});

test('the English table text equals the HTML attribute value for every data-i18n-attr key', () => {
  for (const node of elementsWith('data-i18n-attr')) {
    for (const pair of node.value.split(';')) {
      const [attribute, key] = pair.split(':').map((part) => part.trim());
      const value = attributeOf(node.attrs, attribute);
      // data-tip-title in the HTML is tipTitle in a dataset read; both spellings are allowed.
      if (value === null && attribute === 'data-tip-title') continue;
      assert.notEqual(value, null, `attribute "${attribute}" of key "${key}" not found in the HTML`);
      assert.equal(EN[key], value, `HTML attribute "${attribute}" differs for "${key}"`);
    }
  }
});
