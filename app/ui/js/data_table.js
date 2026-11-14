// Dense data table (docs/design/2026-11-14-workbench-ux-plan.md, phase 0): the one table for long
// engineering lists such as a tank capacity plan or a fleet list. Sort by any column, filter the
// text, read the unit from the header, copy the result to the clipboard; keyboard-first, and an
// unknown value is a dash with a tooltip, never a blank cell.
// The pure helpers (sortRows, filterRows, toTsv) run in Node without a DOM and are tested in
// app/ui-tests/data_table.test.mjs; only createDataTable builds DOM.

import { el, fill, icon } from './dom.js';
import { locale, t } from './i18n.js';

/** Missing and non-finite values are unknown; zero is still a value. */
function isUnknown(value) {
  return value === null || value === undefined ||
    (typeof value === 'string' && !value.trim()) ||
    (typeof value === 'number' && !Number.isFinite(value));
}

/** Read a formatter's visible text without requiring a global DOM in Node. */
function plainText(value) {
  if (value == null) return '';
  return typeof value === 'object' ? (value.textContent ?? '') : String(value);
}

function cellContent(row, column) {
  const value = row[column.key];
  if (isUnknown(value)) return '';
  return column.format ? column.format(value, row) : String(value);
}

/** A column's plain text for one row, or "" when the value is unknown. */
function cellText(row, column) {
  return plainText(cellContent(row, column));
}

/** The header of one column: "Capacity (m³)" — a unit always reads in the header. */
function headerText(column) {
  return column.unit ? `${column.label} (${column.unit})` : column.label;
}

/**
 * `rows` in `direction` order ('asc' or 'desc') by `column`. Numbers sort numerically, strings
 * with the current locale (i18n.js), and a null or unknown value is always last, in both
 * directions. The given order breaks ties, so the sort is stable for equal values.
 */
export function sortRows(rows, column, direction = 'asc') {
  const factor = direction === 'desc' ? -1 : 1;
  const collator = new Intl.Collator(locale(), { numeric: true, sensitivity: 'base' });
  return [...rows].sort((a, b) => {
    const left = a[column.key];
    const right = b[column.key];
    if (isUnknown(left)) return isUnknown(right) ? 0 : 1; // unknown last, in both directions
    if (isUnknown(right)) return -1;
    if (typeof left === 'number' && typeof right === 'number') return factor * (left - right);
    return factor * collator.compare(String(left), String(right));
  });
}

/** The rows whose visible column text contains `query` (case-insensitive), in the given order. */
export function filterRows(rows, columns, query) {
  const needle = String(query ?? '').trim().toLowerCase();
  if (!needle) return [...rows];
  return rows.filter((row) => columns.some((column) => cellText(row, column).toLowerCase().includes(needle)));
}

/**
 * The rows as spreadsheet text: a header line with the units in brackets, then one line per row.
 * A null or unknown value copies as an empty cell and a number as its plain value, so a paste into
 * a spreadsheet gives real numbers, not the rounded display text.
 */
/**
 * A text cell made safe for a spreadsheet: tabs and line breaks become spaces (they would split
 * the cell), and text that starts with = + - or @ gets a leading ' so that a spreadsheet keeps
 * it as text and does not run it as a formula. Labels come from drawings, so they are untrusted.
 */
export function safeCell(text) {
  const flat = String(text).replace(/[\t\r\n]+/g, ' ');
  return /^[=+\-@]/.test(flat) ? `'${flat}` : flat;
}

export function toTsv(columns, rows) {
  const header = columns.map((column) => safeCell(column.unit ? `${column.label} [${column.unit}]` : column.label)).join('\t');
  const line = (row) => columns.map((column) => {
    const value = row[column.key];
    if (isUnknown(value)) return '';
    // Real numbers stay numbers (a negative LCG must paste as -12.5, not as text).
    return typeof value === 'number' ? String(value) : safeCell(cellText(row, column));
  }).join('\t');
  return [header, ...rows.map(line)].join('\n');
}

/**
 * The table with its controls. `columns` are
 * [{ key, label, unit?, align?: 'start'|'end', format?: (value, row) => string|Node, sortable? }],
 * `rowKey(row)` gives each row's stable id, `onSelect(key)` runs on a row click or Enter, and
 * `emptyText` shows when no row passes the filter. Returns { element, setRows, select }:
 *   setRows(rows)  replace the data (keeps the sort, the filter and the selection)
 *   select(key)    set the selected row without opening it
 * The header cells are buttons with aria-sort; Up and Down move the selection while the table
 * body has the focus, and Enter opens the selected row.
 */
export function createDataTable({ columns, rows = [], caption, rowKey, onSelect, emptyText }) {
  const keyOf = rowKey || ((row) => row.id);
  let data = [...rows];
  let sortColumn = null;
  let sortDirection = 'asc';
  let query = '';
  let selectedKey = null;
  const notifySelect = onSelect || null;
  let renderedRows = [];

  const search = el('input', {
    type: 'search', class: 'table-search', placeholder: t('table.filter'),
    'aria-label': t('table.filterLabel'), autocomplete: 'off',
    oninput: (event) => { query = event.target.value; render(); },
  });
  const count = el('span', { class: 'table-count', 'aria-live': 'polite' });
  const copyButton = el('button', {
    class: 'btn', type: 'button', title: t('table.copyTitle'), onclick: () => copyTsv(),
  }, icon('table'), t('table.copy'));
  // One header cell per column, with its sort button when the column sorts. `render` writes the
  // aria attributes; the head is built once.
  const headCells = columns.map((column) => {
    const plain = el('span', { class: 'table-head' }, headerText(column));
    if (column.sortable === false) return { column, th: el('th', { scope: 'col' }, plain) };
    const button = el('button', {
      type: 'button', class: 'table-sort', onclick: () => sortBy(column),
    }, headerText(column), icon('chevron', 'table-sort-mark'));
    return { column, button, th: el('th', { scope: 'col' }, button) };
  });
  const head = el('tr', {}, ...headCells.map((cell) => cell.th));
  const body = el('tbody', { class: 'table-body', tabindex: '0', onkeydown: onBodyKeys });
  const table = el('table', { class: 'data-table' },
    caption ? el('caption', { class: 'visually-hidden' }, caption) : null,
    el('thead', {}, head), body);
  const element = el('div', { class: 'table-wrap' },
    el('div', { class: 'table-bar' }, search, count, copyButton),
    el('div', { class: 'table-scroll' }, table));

  /** The rows as they show: sorted (when a column is sorted) and filtered by the query. */
  function viewRows() {
    const sorted = sortColumn ? sortRows(data, sortColumn, sortDirection) : data;
    return filterRows(sorted, columns, query);
  }

  function render() {
    const rowsInView = viewRows();
    // A selection the filter removed does not stay on a row that is gone.
    if (!rowsInView.some((row) => keyOf(row) === selectedKey)) selectedKey = null;
    renderedRows = rowsInView;
    if (rowsInView.length) {
      fill(body, ...rowsInView.map((row) => {
        const key = keyOf(row);
        return el('tr', {
          tabindex: '-1',
          onclick: () => { select(key); notifySelect?.(key); },
        }, ...columns.map((column) => {
          const content = cellContent(row, column);
          const unknown = !plainText(content).trim();
          const numeric = column.align === 'end' || (!column.align && typeof row[column.key] === 'number');
          return el('td', {
            class: numeric ? 'table-num' : null,
            title: unknown ? t('table.unknown') : null,
          }, unknown ? '—' : content);
        }));
      }));
      updateSelection();
    } else {
      fill(body, el('tr', { class: 'table-empty' }, el('td', { colspan: String(columns.length) },
        emptyText || t('table.noRows'))));
    }
    // The count, and the state of each header cell: which column sorts, and which way.
    count.replaceChildren(t('table.count', { shown: rowsInView.length, total: data.length }));
    for (const { column, th, button } of headCells) {
      const active = column === sortColumn;
      th.setAttribute('aria-sort', button ? (active ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none') : 'none');
      if (!button) continue;
      button.setAttribute('aria-label', active
        ? t('table.sortedBy', { column: headerText(column), direction: t(sortDirection === 'asc' ? 'table.asc' : 'table.desc') })
        : t('table.sortBy', { column: headerText(column) }));
      button.setAttribute('data-active', active ? 'true' : 'false');
    }
  }

  function sortBy(column) {
    if (sortColumn === column) sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
    else { sortColumn = column; sortDirection = 'asc'; }
    render();
  }

  /** Copy the sorted and filtered rows as spreadsheet text; the button says what happened. */
  async function copyTsv() {
    let copied = false;
    try {
      const clipboard = globalThis.navigator?.clipboard;
      if (typeof clipboard?.writeText === 'function') {
        await clipboard.writeText(toTsv(columns, viewRows()));
        copied = true;
      }
    } catch { /* not copied: the label below says so */ }
    copyButton.replaceChildren(copied ? t('table.copied') : t('table.copyFailed'));
    copyButton.title = copied ? t('table.copiedTitle') : t('table.copyFailedTitle');
    setTimeout(() => {
      copyButton.replaceChildren(icon('table'), t('table.copy'));
      copyButton.title = t('table.copyTitle');
    }, 1600);
  }

  /** Up and Down move the selection while the body has the focus; Enter opens the selected row. */
  function onBodyKeys(event) {
    if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown' && event.key !== 'Enter') return;
    const rowsInView = viewRows();
    if (!rowsInView.length) return;
    event.preventDefault();
    const current = rowsInView.findIndex((row) => keyOf(row) === selectedKey);
    if (event.key === 'Enter') {
      select(keyOf(rowsInView[Math.max(current, 0)]));
      notifySelect?.(selectedKey);
      return;
    }
    const next = current < 0 ? 0 : event.key === 'ArrowDown'
      ? Math.min(current + 1, rowsInView.length - 1) : Math.max(current - 1, 0);
    select(keyOf(rowsInView[next]));
    body.children[next]?.focus();
  }

  // Selection changes must not replace focused rows and drop keyboard focus.
  function updateSelection() {
    renderedRows.forEach((row, index) => {
      const selected = keyOf(row) === selectedKey;
      body.children[index].className = selected ? 'is-selected' : '';
      body.children[index].setAttribute('aria-selected', String(selected));
    });
  }

  function select(key) {
    selectedKey = renderedRows.some((row) => keyOf(row) === key) ? key : null;
    updateSelection();
  }

  function setRows(rows) {
    data = [...rows];
    render();
  }

  render();
  return { element, setRows, select };
}
