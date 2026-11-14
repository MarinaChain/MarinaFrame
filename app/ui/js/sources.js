// Sources tab of a vessel: every file that was given to the run (drawings, PDFs, tables, spec
// inputs), as the run's records name them, and a large view of each page. The backend lists
// the files (`list_sources`) and sends one page at a time (`read_source_page`); the UI names a
// file only by its id. A replaced file is an earlier version, never a current one. The words
// here describe files; none says a file or a result is approved or verified.

import { t, locale, applyLocale } from './i18n.js';

import { el, icon, fill } from './dom.js';
import { createDrawingView } from './drawing.js';
import * as fmt from './format.js';

/** The list groups in order: one per kind of file, then the earlier versions. */
export const KIND_GROUPS = [
  { kind: 'drawing', title: 'Drawings', glyph: 'drawing' },
  { kind: 'pdf', title: 'PDFs', glyph: 'sheet' },
  { kind: 'table', title: 'Tables', glyph: 'table' },
  { kind: 'spec', title: 'Spec inputs', glyph: 'file' },
];
const EARLIER_GROUP = { kind: 'earlier', title: 'Earlier versions', glyph: 'reset' };

/** Characters of the SHA-256 shown in the list; the detail shows all of it. */
const SHORT_HASH = 12;

/** Current files grouped by kind (empty groups left out), then the replaced files. */
export function groupSources(sources) {
  const current = sources.filter((source) => source.status !== 'replaced');
  const groups = KIND_GROUPS
    .map((group) => ({ ...group, title: t(`ko2.sources.group.${group.kind}`), items: current.filter((source) => source.kind === group.kind) }))
    .filter((group) => group.items.length);
  const earlier = sources.filter((source) => source.status === 'replaced');
  if (earlier.length) groups.push({ ...EARLIER_GROUP, title: t('ko2.sources.group.earlier'), items: earlier });
  return groups;
}

/** The order in which the list shows the files (for arrow keys). */
function listOrder(sources) {
  return groupSources(sources).flatMap((group) => group.items);
}

/** "Lines plan · 1:50" for one page, from what the intake read; null when nothing was read. */
export function sheetLine(page) {
  if (!page) return null;
  const scale = page.scale ? t('ko2.sources.scale', { scale: page.scale }) : null;
  return [page.sheet_type, scale].filter(Boolean).join(' · ') || null;
}

/** "Used from r0001" while in use; "Used in r0000 to r0002" for an earlier version. */
export function usedLine(source) {
  if (!source.used_from) return null;
  if (!source.used_to) return t('ko2.sources.usedFrom', { revision: source.used_from });
  if (source.used_to === source.used_from) return t('ko2.sources.usedIn', { revision: source.used_from });
  return t('ko2.sources.usedRange', { from: source.used_from, to: source.used_to });
}

/** The short facts of a list row, in reading order. */
export function sourceFacts(source) {
  const pages = source.kind === 'spec' ? null : fmt.plural(source.pages.length, 'page');
  return [
    pages,
    source.pages.length === 1 ? sheetLine(source.pages[0]) : null,
    source.size_bytes === null || source.size_bytes === undefined ? null : fmt.bytes(source.size_bytes),
    usedLine(source),
  ].filter(Boolean);
}

/** A status word for files that are not simply in use. */
export function statusWord(source) {
  if (source.status === 'replaced') return t('ko2.sources.replaced');
  if (source.status === 'unreadable') return t('ko2.sources.unreadable');
  return null;
}

/** The facts of the detail list under the page: [term, value, { mono }]. */
function detailFacts(source, byId) {
  const replacement = source.replaced_by ? byId.get(source.replaced_by) : null;
  const sheets = source.pages.map((page) => sheetLine(page)).filter(Boolean);
  return [
    [t('ko2.sources.file'), source.name],
    [t('ko2.sources.role'), source.role],
    [t('ko2.sources.status'), statusWord(source) || t('ko2.sources.inUse')],
    replacement ? [t('ko2.sources.replacedBy'), replacement.name] : null,
    source.version > 1 ? [t('ko2.sources.version'), String(source.version)] : null,
    source.kind === 'spec' ? null : [t('ko2.sources.pages'), String(source.pages.length)],
    sheets.length ? [t('ko2.sources.sheet'), [...new Set(sheets)].join('; ')] : null,
    source.size_bytes === null || source.size_bytes === undefined ? null : [t('ko2.sources.size'), fmt.bytes(source.size_bytes)],
    source.added_ms ? [t('ko2.sources.added'), fmt.fullTime(source.added_ms)] : null,
    usedLine(source) ? [t('ko2.sources.revisions'), usedLine(source)] : null,
    source.sha256 ? ['SHA-256', source.sha256, { mono: true }] : null,
    source.note ? [t('ko2.sources.note'), source.note] : null,
  ].filter(Boolean);
}

function defaultViewer(parts) {
  return createDrawingView({ ...parts, onSelectSection() {}, onHoverCandidate() {} });
}

/**
 * The Sources page. `host` is the vessel page it fills; `invoke` is api.js `invoke`.
 * `createViewer({ host, tooltip, readout })` makes the page viewer (js/drawing.js by default).
 * `show(task, key)` lists the run's files again when `key` changes (a new revision or a
 * replaced sheet). `showPanel(host, task, key, onOpen)` fills the compact list of the
 * inspector's Sources tab; `select(id)` picks a file on the page.
 */
export function createSources({ host, invoke, createViewer = defaultViewer }) {
  let task = null;
  let loadedKey = null;
  let listing = null; // Promise of { sources, revision }
  let sources = [];
  let error = '';
  let loading = false;
  let selectedId = null;
  let pageIndex = 0; // position in the selected file's recorded pages
  let viewToken = 0;
  let shownLocale = locale();
  let shownView = null; // what the large view shows now, so a refresh keeps zoom and pan
  let panel = null; // { host, onOpen } of the inspector's compact list
  const previews = new Map(); // `${task}|${id}|${page}|${size}` -> Promise of a preview
  const rowButtons = new Map(); // id -> list row of the page, for focus

  // ---------------------------------------------------------------- page skeleton

  const list = el('div', { class: 'sources-list', role: 'listbox', 'aria-label': t('ko2.sources.sourceFiles'), 'data-i18n-attr': 'aria-label:ko2.sources.sourceFiles' });
  const count = el('span', { class: 'page-head-meta' });
  const title = el('h2', { class: 'source-view-title' });
  const meta = el('span', { class: 'pane-meta source-view-meta', 'aria-live': 'polite' });
  const readout = el('span', { class: 'zoom-readout', 'aria-live': 'off' }, '100%');
  const button = (glyph, key, onclick) => el('button', {
    class: 'btn btn-ghost btn-icon', type: 'button', 'aria-label': t(key), title: t(key), 'data-i18n-attr': `aria-label:${key};title:${key}`, onclick,
  }, icon(glyph));
  const previousPage = button('chevron', 'ko2.sources.previous', () => stepPage(-1));
  previousPage.classList.add('source-page-back');
  const nextPage = button('chevron', 'ko2.sources.next', () => stepPage(1));
  const pager = el('span', { class: 'source-pager' }, previousPage, nextPage);
  const zoomTools = el('span', { class: 'source-zoom' },
    button('zoom-out', 'ko2.sources.zoomOut', () => viewer.zoomOut()),
    readout,
    button('zoom-in', 'ko2.sources.zoomIn', () => viewer.zoomIn()),
    button('fit', 'ko2.sources.fit', () => viewer.fitPage()));
  const viewerHost = el('div', {
    class: 'drawing-host source-host', tabindex: '0', role: 'region',
    'aria-label': t('ko2.sources.viewerHelp'), 'data-i18n-attr': 'aria-label:ko2.sources.viewerHelp',
  });
  const tooltip = el('div', { class: 'tooltip', role: 'tooltip', hidden: true });
  const message = el('div', { class: 'source-message', role: 'status' });
  const textView = el('pre', { class: 'source-text selectable-text', tabindex: '0', hidden: true });
  const stage = el('div', { class: 'source-stage' }, viewerHost, tooltip, textView, message);
  const details = el('dl', { class: 'source-details' });
  const view = el('section', { class: 'source-view', 'aria-label': t('ko2.sources.selected'), 'data-i18n-attr': 'aria-label:ko2.sources.selected' },
    el('div', { class: 'pane-head source-view-head' },
      title, meta,
      el('div', { class: 'pane-tools' }, pager, zoomTools)),
    stage,
    details);
  const pageBody = el('div', { class: 'sources-page' },
    el('section', { class: 'sources-side', 'aria-labelledby': 'sources-title' },
      el('div', { class: 'page-head sources-head' },
        el('h1', { id: 'sources-title', 'data-i18n': 'ko2.sources.sources' }, t('ko2.sources.sources')),
        count),
      el('p', { class: 'sources-intro', 'data-i18n': 'ko2.sources.intro' }, t('ko2.sources.intro')),
      list),
    view);
  host.append(pageBody);
  const viewer = createViewer({ host: viewerHost, tooltip, readout });

  viewerHost.addEventListener('keydown', (event) => {
    const step = { PageUp: -1, PageDown: 1 }[event.key];
    if (!step) return;
    event.preventDefault();
    stepPage(step);
  });
  list.addEventListener('keydown', (event) => {
    const step = { ArrowDown: 1, ArrowUp: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    const order = listOrder(sources);
    const at = order.findIndex((source) => source.id === selectedId);
    const next = order[Math.min(order.length - 1, Math.max(0, at + step))];
    if (next) select(next.id, { focus: true });
  });

  // ---------------------------------------------------------------- data

  const byId = () => new Map(sources.map((source) => [source.id, source]));
  const selected = () => sources.find((source) => source.id === selectedId) || null;

  function preview(id, page, size) {
    const key = `${task}|${id}|${page}|${size}`;
    if (!previews.has(key)) {
      const load = invoke('read_source_page', { task, source_id: id, page, size });
      previews.set(key, load.catch((failure) => {
        previews.delete(key);
        throw failure;
      }));
    }
    return previews.get(key);
  }

  const dataUrl = (shown) => `data:${shown.mime};base64,${shown.base64}`;

  const isLoaded = (nextTask, key) => nextTask === task && key === loadedKey && listing !== null;

  /** List the run's files again for a new task or key. */
  function load(nextTask, key) {
    if (nextTask !== task) {
      selectedId = null;
      pageIndex = 0;
      previews.clear();
    }
    task = nextTask;
    loadedKey = key;
    error = '';
    if (!task) {
      sources = [];
      listing = Promise.resolve({ sources: [] });
      return listing;
    }
    loading = true;
    const asked = task;
    listing = invoke('list_sources', { task })
      .then((result) => {
        if (asked !== task) return result;
        sources = result.sources || [];
        if (!sources.some((source) => source.id === selectedId)) {
          selectedId = listOrder(sources).find((source) => source.previewable)?.id ?? listOrder(sources)[0]?.id ?? null;
          pageIndex = 0;
        }
        return result;
      })
      .catch((failure) => {
        if (asked === task) {
          sources = [];
          error = failure?.message || t('ko2.sources.folderError');
        }
        return { sources: [] };
      })
      .finally(() => {
        if (asked === task) loading = false;
      });
    return listing;
  }

  // ---------------------------------------------------------------- list rows

  function thumbnail(source) {
    const frame = el('span', { class: 'source-thumb', 'aria-hidden': 'true' }, icon(KIND_GROUPS.find((g) => g.kind === source.kind)?.glyph || 'file'));
    if (!source.previewable || source.kind === 'spec' || !source.pages.length) return frame;
    const asked = task;
    preview(source.id, source.pages[0].index, 'thumb')
      .then((shown) => {
        if (asked !== task || !shown.base64) return;
        fill(frame, el('img', { src: dataUrl(shown), alt: '', width: String(shown.width), height: String(shown.height) }));
      })
      .catch(() => {}); // The kind icon stays; the large view says why the page cannot show.
    return frame;
  }

  /** One file: thumbnail, name, role and facts. `compact` is the inspector's list. */
  function row(source, { compact = false, onPick }) {
    const status = statusWord(source);
    const isSelected = !compact && source.id === selectedId;
    const button = el('button', {
      class: `source-row${compact ? ' source-row-compact' : ''}`,
      type: 'button',
      role: compact ? null : 'option',
      'aria-selected': compact ? null : String(isSelected),
      tabindex: compact || isSelected ? '0' : '-1',
      dataset: { source: source.id, status: source.status },
      onclick: () => onPick(source.id),
    },
    thumbnail(source),
    el('span', { class: 'source-text-col' },
      el('span', { class: 'source-name' }, source.name),
      el('span', { class: 'source-role' }, source.role,
        status ? el('span', { class: 'badge badge-small', dataset: { tone: source.status === 'replaced' ? 'draft' : 'warn' } }, status) : null),
      el('span', { class: 'source-facts' }, sourceFacts(source).join(' · '))));
    if (!compact) rowButtons.set(source.id, button);
    return button;
  }

  function groupedList(onPick, { compact = false } = {}) {
    return groupSources(sources).map((group) => el('section', { class: 'source-group', dataset: { kind: group.kind } },
      el('h3', { class: 'source-group-title' }, icon(group.glyph), group.title, el('span', { class: 'source-group-count' }, String(group.items.length))),
      ...group.items.map((source) => row(source, { compact, onPick }))));
  }

  /** Words for a list that has nothing to show: loading, error or empty. Null when it has rows. */
  function listState(onRetry) {
    if (!task) return el('p', { class: 'page-empty' }, icon('info'), t('ko2.sources.noRun'));
    if (error) {
      return el('div', { class: 'page-empty source-error', role: 'alert' }, icon('warn'),
        el('span', {}, el('strong', {}, t('ko2.sources.listError')), error),
        el('button', { class: 'btn btn-small', type: 'button', onclick: onRetry }, t('ko2.sources.retry')));
    }
    if (loading && !sources.length) return el('p', { class: 'page-empty' }, icon('info'), t('ko2.sources.readingFolder'));
    if (!sources.length) {
      return el('p', { class: 'page-empty source-empty' }, icon('info'),
        t('ko2.sources.empty'));
    }
    return null;
  }

  function retry() {
    listing = null;
    show(task, loadedKey);
    if (panel) showPanel(panel.host, task, loadedKey, panel.onOpen);
  }

  // ---------------------------------------------------------------- page view

  function stepPage(step) {
    const source = selected();
    if (!source) return;
    const next = pageIndex + step;
    if (next < 0 || next >= source.pages.length) return;
    pageIndex = next;
    renderView();
  }

  function showMessage(strong, text) {
    fill(message, el('strong', {}, strong), text ? el('span', {}, text) : null);
    message.hidden = false;
  }

  function renderView() {
    const source = selected();
    const viewKey = `${task}|${loadedKey}|${source?.id}|${pageIndex}|${sources.length}|${error}`;
    if (viewKey === shownView) return;
    shownView = viewKey;
    const token = ++viewToken;
    message.hidden = true;
    textView.hidden = true;
    viewerHost.hidden = false;
    // Zoom belongs to a page picture; a spec input or a missing file has none.
    zoomTools.hidden = !source?.previewable || source.kind === 'spec';
    fill(details, ...(source ? detailFacts(source, byId()) : []).flatMap(([term, value, options]) => [
      el('dt', {}, term), el('dd', { class: options?.mono ? 'mono selectable-text' : null }, value)]));
    const pages = source?.pages.length || 0;
    title.textContent = source ? source.name : t('ko2.sources.noFile');
    pager.hidden = pages < 2;
    previousPage.disabled = pageIndex <= 0;
    nextPage.disabled = pageIndex >= pages - 1;
    if (!source) {
      meta.textContent = '';
      viewer.setPage(null, null);
      viewerHost.hidden = true;
      if (sources.length) showMessage(t('ko2.sources.pick'), '');
      return;
    }
    if (!source.previewable) {
      meta.textContent = statusWord(source) || '';
      viewer.setPage(null, null);
      viewerHost.hidden = true;
      showMessage(t('ko2.sources.cannotShow'), source.note || t('ko2.sources.notInFolder'));
      return;
    }
    if (source.kind === 'spec') {
      meta.textContent = source.role;
      viewerHost.hidden = true;
      textView.hidden = false;
      textView.textContent = t('ko2.sources.readingFile');
      preview(source.id, 0, 'full')
        .then((shown) => { if (token === viewToken) textView.textContent = shown.text ?? ''; })
        .catch((failure) => {
          if (token !== viewToken) return;
          textView.hidden = true;
          showMessage(t('ko2.sources.showError'), failure?.message || '');
        });
      return;
    }
    const page = source.pages[pageIndex];
    const where = pages > 1 ? t('ko2.sources.pageCount', { page: pageIndex + 1, total: pages }) : t('ko2.sources.onePage');
    meta.textContent = [where, sheetLine(page)].filter(Boolean).join(' · ');
    const pageKey = `${task}|${source.id}|${page.index}`;
    viewer.setPage(null, null);
    showMessage(t('ko2.sources.readingPage'), '');
    preview(source.id, page.index, 'full')
      .then((shown) => {
        if (token !== viewToken) return;
        message.hidden = true;
        viewer.setPage({ path: pageKey, width: shown.width, height: shown.height }, dataUrl(shown));
        const size = page.width_px && page.height_px ? `${page.width_px} × ${page.height_px} px` : `${shown.width} × ${shown.height} px`;
        meta.textContent = [where, sheetLine(page), size].filter(Boolean).join(' · ');
      })
      .catch((failure) => {
        if (token !== viewToken) return;
        viewerHost.hidden = true;
        showMessage(t('ko2.sources.pageError'), failure?.message || '');
      });
  }

  function renderList() {
    const state = listState(retry);
    count.textContent = sources.length ? fmt.plural(sources.length, 'file') : '';
    rowButtons.clear();
    fill(list, state || groupedList((id) => select(id)));
    view.hidden = Boolean(state);
    // Without files the message takes the page width; there is no page to show beside it.
    pageBody.dataset.state = state ? 'message' : 'list';
  }

  function renderPanel() {
    if (!panel) return;
    fill(panel.host,
      el('p', { class: 'sources-panel-intro' }, t('ko2.sources.panelIntro')),
      listState(retry) || groupedList((id) => panel.onOpen(id), { compact: true }));
  }

  function render() {
    renderList();
    renderView();
    renderPanel();
  }

  /** Pick a file (and its first page) on the page; `focus` moves the keyboard to its row. */
  function select(id, { focus = false } = {}) {
    if (!sources.some((source) => source.id === id)) return;
    if (id !== selectedId) pageIndex = 0;
    selectedId = id;
    renderList();
    renderView();
    if (focus) rowButtons.get(id)?.focus?.();
  }

  /** Show the page for `task`; `key` changes when the run's files may have changed. */
  function refreshLocale() {
    if (shownLocale === locale()) return;
    shownLocale = locale();
    shownView = null;
    applyLocale(pageBody);
    render();
  }

  function show(nextTask, key) {
    refreshLocale();
    if (isLoaded(nextTask, key)) return listing;
    const pending = load(nextTask, key);
    render();
    return pending.then(render);
  }

  /** Fill the inspector's compact list. `onOpen(id)` opens the file on the Sources page. */
  function showPanel(panelHost, nextTask, key, onOpen) {
    refreshLocale();
    const samePanel = panel?.host === panelHost;
    panel = { host: panelHost, onOpen };
    if (samePanel && isLoaded(nextTask, key)) return listing;
    const pending = isLoaded(nextTask, key) ? listing : load(nextTask, key);
    render();
    return pending.then(render);
  }

  return {
    show,
    showPanel,
    select,
    /** The selected file and page, for tests and the palette. */
    get selection() {
      return selectedId ? { id: selectedId, page: selected()?.pages[pageIndex]?.index ?? 0 } : null;
    },
  };
}
