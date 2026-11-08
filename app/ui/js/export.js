// Export sheet (milestone M5): choose the outputs of one revision, write them into the
// run's exports folder and show each file in Finder. Every export is a draft; nothing
// here says "approved" or "verified" (engineering sign-off happens outside MarinaFrame).

import { el, icon, fill } from './dom.js';
import * as fmt from './format.js';

/** The outputs in display order. `kind` matches the backend; `name` is the one-word chip. */
const OUTPUTS = [
  { kind: 'step', name: 'STEP', glyph: 'cube', hint: 'Hull surface for CAD, millimetres, draft stamp in the header.' },
  { kind: 'stl', name: 'STL', glyph: 'mesh', hint: 'Triangle mesh for viewers and 3D printing, millimetres.' },
  { kind: 'offsets', name: 'Offsets', glyph: 'table', hint: 'Half-breadths at each station and waterline, CSV for Excel.' },
  { kind: 'hydrostatics', name: 'Hydrostatics', glyph: 'waterline', hint: 'Volume, displacement, centres and coefficients at the design waterline (JSON and CSV).' },
  { kind: 'report', name: 'Report', glyph: 'file', hint: 'PDF review report with station overlays and source labels.' },
  { kind: 'package', name: 'Package', glyph: 'package', hint: 'One ZIP with all files and the manifest.' },
];

/** Statuses whose runs can have a build to export. A running run is still changing. */
export function canExport(view) {
  return Boolean(view?.revision) && view.summary.status !== 'running';
}

/** `invoke` is api.js `invoke`. Errors show inside the sheet. */
export function createExport({ invoke }) {
  let task = null;
  let revision = null;
  const chosen = new Set(OUTPUTS.map((o) => o.kind));
  let files = []; // ExportedFile[] in the folder now
  let notBuilt = new Set();
  let folder = null;
  let busy = false;

  const title = el('h2', { id: 'export-title' }, 'Export');
  const revisionChip = el('span', { class: 'badge badge-small', dataset: { tone: 'brand' } });
  const stamp = el('p', { class: 'export-stamp' },
    el('strong', {}, 'Draft, not for construction.'),
    ' Each file carries this stamp. Engineering sign-off happens outside MarinaFrame.');
  const list = el('div', { class: 'export-list', role: 'group', 'aria-label': 'Outputs to export' });
  const error = el('p', { class: 'form-error', role: 'alert', hidden: true });
  const folderButton = el('button', { class: 'btn btn-ghost', type: 'button', onclick: () => reveal(folder) },
    icon('folder'), 'Show folder');
  const closeButton = el('button', { class: 'btn', type: 'button', onclick: () => sheet.close() }, 'Close');
  const exportButton = el('button', { class: 'btn btn-primary', type: 'button', onclick: () => runExport() }, 'Export');

  const sheet = el('dialog', { class: 'sheet export-sheet', id: 'export-sheet', 'aria-labelledby': 'export-title' },
    el('div', { class: 'sheet-body' },
      el('div', { class: 'sheet-head' }, title, revisionChip),
      stamp,
      list,
      error,
      el('div', { class: 'sheet-actions export-actions' },
        folderButton, el('span', { class: 'export-actions-spacer' }), closeButton, exportButton)));
  document.body.append(sheet);

  function filesOf(kind) {
    return files.filter((f) => f.kind === kind);
  }

  function showError(message) {
    error.textContent = message || '';
    error.hidden = !message;
  }

  function toggle(kind) {
    if (busy) return;
    if (chosen.has(kind)) chosen.delete(kind);
    else chosen.add(kind);
    render();
  }

  function outputRow(output) {
    const pressed = chosen.has(output.kind);
    const written = filesOf(output.kind);
    const size = written.reduce((sum, f) => sum + f.bytes, 0);
    let state;
    if (notBuilt.has(output.kind)) {
      state = el('span', { class: 'badge badge-small', title: 'This build has no such file.' }, el('span', { class: 'badge-text' }, 'Not built'));
    } else if (written.length) {
      state = el('span', { class: 'export-size', title: written.map((f) => f.file).join('\n') }, fmt.bytes(size));
    } else {
      state = el('span', { class: 'export-size export-size-none' }, '—');
    }
    const finder = el('button', {
      class: 'btn btn-ghost btn-icon btn-small',
      type: 'button',
      title: 'Show in Finder',
      'aria-label': `Show ${output.name} in Finder`,
      disabled: !written.length,
      onclick: () => reveal(written[0]?.path),
    }, icon('folder'));
    return el('div', { class: 'export-row', dataset: { kind: output.kind } },
      el('button', {
        class: 'export-toggle',
        type: 'button',
        'aria-pressed': String(pressed),
        title: output.hint,
        disabled: busy,
        onclick: () => toggle(output.kind),
      },
      el('span', { class: 'export-check', 'aria-hidden': 'true' }),
      icon(output.glyph),
      el('span', { class: 'export-name' }, output.name)),
      state,
      finder);
  }

  function render() {
    fill(revisionChip, el('span', { class: 'badge-text' }, revision || ''));
    fill(list, ...OUTPUTS.map(outputRow));
    folderButton.disabled = !files.length;
    closeButton.disabled = busy;
    exportButton.disabled = busy || chosen.size === 0;
    exportButton.textContent = busy ? 'Exporting…' : 'Export';
  }

  function apply(result) {
    files = result.files;
    folder = result.folder;
    notBuilt = new Set(result.not_built || []);
  }

  async function runExport() {
    if (busy || !chosen.size) return;
    busy = true;
    showError(null);
    render();
    try {
      const outputs = OUTPUTS.map((o) => o.kind).filter((kind) => chosen.has(kind));
      apply(await invoke('export_run', { task, revision, outputs }));
    } catch (failure) {
      showError(failure?.message || 'The export did not finish.');
    } finally {
      busy = false;
      render();
    }
  }

  async function reveal(path) {
    if (!path) return;
    try {
      await invoke('reveal_export', { task, path });
    } catch (failure) {
      showError(failure?.message || 'The folder could not be opened.');
    }
  }

  // Escape closes the sheet, except while the export runs.
  sheet.addEventListener('cancel', (event) => { if (busy) event.preventDefault(); });

  return {
    /** Open the sheet for the current revision of a task (`view` is its TaskView). */
    async open(taskPath, view) {
      if (!canExport(view)) return;
      if (taskPath !== task || view.revision !== revision) {
        files = [];
        notBuilt = new Set();
        folder = null;
      }
      task = taskPath;
      revision = view.revision;
      showError(null);
      render();
      sheet.showModal();
      try {
        apply(await invoke('list_exports', { task, revision }));
        render();
      } catch (failure) {
        showError(failure?.message);
      }
    },
  };
}
