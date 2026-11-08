// Export page (milestone M5), the Export tab of a vessel: choose the outputs of one
// revision, write them into the run's exports folder and show each file in Finder. Every
// export is a draft; nothing here says "approved" or "verified" (engineering sign-off
// happens outside MarinaFrame).

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

/**
 * The Export page. `host` is the element it fills; `invoke` is api.js `invoke`.
 * Errors show inside the page.
 */
export function createExport({ host, invoke }) {
  let task = null;
  let view = null;
  let revision = null;
  let openIssues = 0; // sections still a guess or declined
  let openParts = 0; // whole-vessel parts guessed or not built, not accepted
  const chosen = new Set(OUTPUTS.map((o) => o.kind));
  let files = []; // ExportedFile[] in the folder now
  let notBuilt = new Set();
  let folder = null;
  let busy = false;
  let error = '';

  function filesOf(kind) {
    return files.filter((f) => f.kind === kind);
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
      class: 'btn btn-ghost btn-icon',
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
        disabled: busy,
        onclick: () => toggle(output.kind),
      },
      el('span', { class: 'export-check', 'aria-hidden': 'true' }),
      icon(output.glyph),
      el('span', { class: 'export-text' },
        el('span', { class: 'export-name' }, output.name),
        el('span', { class: 'export-hint' }, output.hint))),
      state,
      finder);
  }

  /** Why the page cannot export now, in plain words; null when it can. */
  function blockedText() {
    if (!view) return 'Open a run to export its draft.';
    if (view.summary.status === 'running') return 'The AI is still working on this run. Export opens when the run stops.';
    if (!view.revision) return 'This run has no build yet. Export needs a built hull.';
    return null;
  }

  function issuesLine() {
    const lines = [];
    if (openIssues) lines.push(`${openIssues} ${openIssues === 1 ? 'section is' : 'sections are'} still a guess or declined.`);
    if (openParts) lines.push(`${openParts} ${openParts === 1 ? 'part is' : 'parts are'} guessed or not built.`);
    if (!lines.length) return null;
    return el('p', { class: 'export-issues', role: 'note' }, icon('warn'),
      el('span', {}, `${lines.join(' ')} The files show the draft as it is now.`));
  }

  function render() {
    const blocked = blockedText();
    const head = el('header', { class: 'page-head' },
      el('h1', { id: 'export-title' }, 'Export'),
      revision ? el('span', { class: 'badge', dataset: { tone: 'brand' }, title: `Revision ${revision}` }, el('span', { class: 'badge-text' }, revision)) : null);
    if (blocked) {
      fill(host, el('div', { class: 'page-body export-page' }, head,
        el('div', { class: 'page-empty' }, icon('export'), el('p', {}, blocked))));
      return;
    }
    const exportButton = el('button', {
      class: 'btn btn-primary btn-large',
      type: 'button',
      disabled: busy || chosen.size === 0,
      onclick: () => runExport(),
    }, busy ? 'Exporting…' : 'Export');
    const folderButton = el('button', {
      class: 'btn btn-large',
      type: 'button',
      disabled: !files.length,
      onclick: () => reveal(folder),
    }, icon('folder'), 'Show folder');
    fill(host, el('div', { class: 'page-body export-page' },
      head,
      el('p', { class: 'export-stamp' },
        el('strong', {}, 'Draft, not for construction.'),
        ' Each file carries this stamp. Engineering sign-off happens outside MarinaFrame.'),
      issuesLine(),
      el('div', { class: 'export-list', role: 'group', 'aria-label': 'Outputs to export' }, ...OUTPUTS.map(outputRow)),
      error ? el('p', { class: 'form-error', role: 'alert' }, error) : null,
      el('div', { class: 'export-actions' }, folderButton, el('span', { class: 'export-actions-spacer' }), exportButton)));
  }

  function apply(result) {
    files = result.files;
    folder = result.folder;
    notBuilt = new Set(result.not_built || []);
  }

  async function runExport() {
    if (busy || !chosen.size) return;
    busy = true;
    error = '';
    render();
    try {
      const outputs = OUTPUTS.map((o) => o.kind).filter((kind) => chosen.has(kind));
      apply(await invoke('export_run', { task, revision, outputs }));
    } catch (failure) {
      error = failure?.message || 'The export did not finish.';
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
      error = failure?.message || 'The folder could not be opened.';
      render();
    }
  }

  return {
    /**
     * Show the page for the current revision of a task (`taskView` is its TaskView);
     * `issues` is the number of sections that are still a guess or declined, `parts` the
     * number of whole-vessel parts guessed or not built and not accepted.
     */
    async show(taskPath, taskView, issues = 0, partsOpen = 0) {
      const changed = taskPath !== task || taskView?.revision !== revision;
      task = taskPath;
      view = taskView;
      openIssues = issues;
      openParts = partsOpen;
      if (changed) {
        revision = taskView?.revision || null;
        files = [];
        notBuilt = new Set();
        folder = null;
        error = '';
      }
      render();
      if (!changed || !canExport(taskView)) return;
      try {
        apply(await invoke('list_exports', { task, revision }));
      } catch (failure) {
        error = failure?.message || '';
      }
      render();
    },
  };
}
