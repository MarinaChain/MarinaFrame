// Export page (milestone M5), the Export tab of a vessel: choose the outputs of one
// revision, write them into the run's exports folder and show each file in Finder. Every
// export is a draft; nothing here says "approved" or "verified" (engineering sign-off
// happens outside MarinaFrame).

import { el, icon, fill } from './dom.js';
import { glyphChip } from './glyphs.js';
import * as fmt from './format.js';
import { accuracyBlock } from './accuracy.js';

/** The outputs in display order. `kind` matches the backend; `name` is the one-word chip. */
const OUTPUTS = [
  { kind: 'step', name: 'STEP', glyph: 'cube', hint: 'Hull surface for CAD, millimetres, draft stamp in the header.' },
  { kind: 'iges', name: 'IGES', glyph: 'cube', hint: 'Hull surfaces for CAD, millimetres. Use STEP for solids.' },
  { kind: '3dm', name: 'Rhino 3dm', glyph: 'cube', hint: 'Rhino file with a layer per output, millimetres; curved trimmed faces are meshes.' },
  { kind: 'stl', name: 'STL', glyph: 'mesh', hint: 'Triangle mesh for viewers and 3D printing, millimetres.' },
  { kind: 'offsets', name: 'Offsets', glyph: 'table', hint: 'Half-breadths at each station and waterline, CSV for Excel.' },
  { kind: 'hydrostatics', name: 'Hydrostatics', glyph: 'waterline', hint: 'Volume, displacement, centres and coefficients at the design waterline (JSON and CSV).' },
  { kind: 'report', name: 'Report', glyph: 'file', hint: 'PDF review report with station overlays and source labels.' },
  // Only for a run with a tank model or a structure folder (`ofRun`): see app/core run_tables.rs.
  { kind: 'tanks', name: 'Tank tables', glyph: 'table', hint: 'Capacity plan and one sounding table per built tank, CSV with source labels.', ofRun: (view) => Boolean(view?.tank_model) },
  { kind: 'structure', name: 'Steel and OCX', glyph: 'cube', hint: 'Steel weight tables (CSV) and the OCX 3.0.1 structure file, as the run wrote them.', ofRun: (view) => Boolean(view?.structure_files?.length) },
  { kind: 'package', name: 'Package', glyph: 'package', hint: 'One ZIP with all files and the manifest.' },
];

/** What the files of a multi-file output are: "Capacity plan and 3 sounding tables". */
export function filesSummary(kind, files) {
  const count = (test) => files.filter((f) => test(f.file)).length;
  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
  if (kind === 'tanks') {
    const plans = count((name) => name.endsWith('_capacity_plan.csv'));
    const soundings = count((name) => name.includes('_sounding_'));
    return [plans ? 'Capacity plan' : null, soundings ? plural(soundings, 'sounding table') : null].filter(Boolean).join(' and ');
  }
  if (kind === 'structure') {
    const steel = count((name) => name.endsWith('.csv'));
    const ocx = count((name) => name.endsWith('.3docx'));
    return [steel ? plural(steel, 'steel table') : null, ocx ? plural(ocx, 'OCX file') : null].filter(Boolean).join(' and ');
  }
  return '';
}

/** The outputs this run offers: every hull output, tank and steel outputs when the run has them. */
export function outputsOf(view, files = []) {
  return OUTPUTS.filter((o) => !o.ofRun || o.ofRun(view) || files.some((f) => f.kind === o.kind));
}

/** Statuses whose runs can have a build to export. A running run is still changing. */
export function canExport(view) {
  return Boolean(view?.revision) && view.summary.status !== 'running';
}

/**
 * The Export page. `host` is the element it fills; `invoke` is api.js `invoke`.
 * `captureView(task, revision)` gives the 3D view as base64 PNG text (or null) for the report's
 * hero picture. Errors show inside the page.
 */
export function createExport({ host, invoke, captureView = () => null }) {
  let task = null;
  let view = null;
  let revision = null;
  let openIssues = 0; // sections still a guess or declined
  let openParts = 0; // whole-vessel parts guessed or not built, not accepted
  const chosen = new Set(OUTPUTS.map((o) => o.kind));
  let files = []; // ExportedFile[] in the folder now
  let notBuilt = new Set();
  let formatResults = {};
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
    const failures = (output.kind === 'package' ? ['glb', 'ocx'] :
      output.kind === 'structure' ? ['ocx'] : [output.kind])
      .map((kind) => ({ kind, ...formatResults[kind] }))
      .filter((result) => result.status === 'failed');
    const written = failures.length && output.kind !== 'package' && output.kind !== 'structure' ? [] : filesOf(output.kind);
    const size = written.reduce((sum, f) => sum + f.bytes, 0);
    let state;
    if (failures.length) {
      state = el('span', { class: 'badge badge-small' }, 'Failed');
    } else if (notBuilt.has(output.kind)) {
      state = el('span', { class: 'badge badge-small', title: 'This build has no such file.' }, el('span', { class: 'badge-text' }, 'Not built'));
    } else if (written.length) {
      state = el('span', { class: 'export-size', title: written.map((f) => f.file).join('\n') }, fmt.bytes(size));
    } else {
      state = el('span', { class: 'export-size export-size-none' }, '—');
    }
    const finder = el('button', {
      class: `btn btn-ghost btn-icon${written.length ? '' : ' export-finder-none'}`,
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
        el('span', { class: 'export-hint' }, output.hint),
        ...failures.map((failure) => el('span', { class: 'export-hint' }, `${failure.kind.toUpperCase()}: ${failure.reason}`)),
        filesSummary(output.kind, written) ? el('span', { class: 'export-hint' }, `Written: ${filesSummary(output.kind, written)}.`) : null)),
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

  /** What is still open, as icon counts; the files show the draft as it is now. */
  function issuesLine() {
    if (!openIssues && !openParts) return null;
    return el('p', { class: 'export-issues', role: 'note' }, icon('warn'),
      el('span', {}, 'Still open:'),
      openIssues ? glyphChip('flag', 'sections', {
        count: openIssues, countedName: `${fmt.plural(openIssues, 'section')} still a guess or declined`, tone: 'warn',
        detail: 'The files show the draft as it is now.',
      }) : null,
      openParts ? glyphChip('cube', 'parts', {
        count: openParts, countedName: `${fmt.plural(openParts, 'part')} guessed or not built`, tone: 'warn',
        detail: 'The files show the draft as it is now.',
      }) : null);
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
      disabled: busy || !outputsOf(view, files).some((o) => chosen.has(o.kind)),
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
        ' Each file carries this stamp. Engineering approval happens outside MarinaFrame.'),
      issuesLine(),
      accuracyBlock(view),
      // A person's sign-off of the parts goes with the files as a note; the files stay drafts.
      view?.sign_off ? el('p', { class: 'export-signoff' }, el('strong', {}, `Signed off by ${view.sign_off.name}, ${new Date(view.sign_off.time_ms).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}: `), `${view.sign_off.statement}. The files stay drafts.`) : null,
      el('div', { class: 'export-list', role: 'group', 'aria-label': 'Outputs to export' }, ...outputsOf(view, files).map(outputRow)),
      error ? el('p', { class: 'form-error', role: 'alert' }, error) : null,
      el('div', { class: 'export-actions' }, folderButton, el('span', { class: 'export-actions-spacer' }), exportButton)));
  }

  function apply(result) {
    files = result.files;
    folder = result.folder;
    notBuilt = new Set(result.not_built || []);
    formatResults = result.format_results || {};
  }

  /** The 3D view as a picture for the report (also inside the package), or null when none is wanted or shown. */
  function viewerPicture(outputs) {
    if (!outputs.includes('report') && !outputs.includes('package')) return null;
    try {
      return captureView(task, revision);
    } catch {
      // The report is complete without the picture.
      return null;
    }
  }

  async function runExport() {
    if (busy || !outputsOf(view, files).some((o) => chosen.has(o.kind))) return;
    busy = true;
    error = '';
    render();
    try {
      const outputs = outputsOf(view, files).map((o) => o.kind).filter((kind) => chosen.has(kind));
      apply(await invoke('export_run', { task, revision, outputs, viewer_image: viewerPicture(outputs) }));
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
        formatResults = {};
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
