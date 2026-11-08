// Welcome and setup check (storyboard F1-F2). Three checks: the AI key, the CAD worker
// (Python) and the runs folder. A missing key is not a stop: the person can continue
// without the AI, and new runs then use the deterministic draft.
// Contract: get_setup_status in docs/APP_SPEC.md.

import { el, icon, fill } from './dom.js';

/**
 * `host` is the view element. `onDone()` leaves the welcome screen. The pickers and
 * `invoke` come from api.js; `openSettings()` shows Settings.
 */
export function createWelcome({ host, invoke, pickFile, pickFolder, canPickPaths, onDone, openSettings }) {
  let status = null;
  let checking = false;
  let error = '';

  async function check() {
    checking = true;
    render();
    try {
      status = await invoke('get_setup_status', {});
      error = '';
    } catch (failure) {
      error = failure?.message || 'The setup check did not finish.';
    } finally {
      checking = false;
      render();
    }
    return status;
  }

  /** Save one changed setting, then check again. */
  async function saveSetting(field, value) {
    if (!value) return;
    try {
      const settings = await invoke('get_settings', {});
      await invoke('set_settings', { ...settings, [field]: value });
    } catch (failure) {
      error = failure?.message || 'The setting was not saved.';
    }
    await check();
  }

  function aiRow() {
    const ai = status.ai;
    let message = 'The AI reads the drawing and builds the draft.';
    if (!ai.enabled) message = 'AI drafting is off. New runs use the deterministic draft.';
    else if (!ai.key_found) message = 'No model key found. Without a key, new runs use the deterministic draft.';
    return row({
      ok: ai.active,
      title: 'AI',
      message,
      path: ai.active ? '' : ai.key_file,
      pathTitle: 'Put your OpenCode Go key in this file, one key per line (chmod 600).',
      action: el('button', { class: 'btn', type: 'button', onclick: openSettings }, 'Settings'),
    });
  }

  function workerRow() {
    const worker = status.worker;
    return row({
      ok: worker.ok,
      title: 'CAD worker',
      message: worker.ok ? worker.message : `${worker.message} The worker builds the hull and its files.`,
      path: worker.path,
      action: canPickPaths()
        ? el('button', {
          class: 'btn',
          type: 'button',
          onclick: async () => saveSetting('worker_python', await pickFile({ title: 'Choose the Python for the worker', defaultPath: worker.path || undefined })),
        }, icon('file'), 'Choose…')
        : null,
    });
  }

  function runsRow() {
    const runs = status.runs_folder;
    return row({
      ok: runs.ok,
      title: 'Runs folder',
      message: runs.message,
      path: runs.path,
      action: canPickPaths()
        ? el('button', {
          class: 'btn',
          type: 'button',
          onclick: async () => saveSetting('runs_folder', await pickFolder({ title: 'Choose the runs folder', defaultPath: runs.path || undefined })),
        }, icon('folder'), 'Choose…')
        : null,
    });
  }

  function row({ ok, title, message, path, pathTitle = null, action }) {
    return el('li', { class: 'setup-row', dataset: { ok: String(ok) } },
      el('span', { class: 'setup-mark', 'aria-hidden': 'true' }, ok ? icon('check') : icon('warn')),
      el('span', { class: 'setup-text' },
        el('span', { class: 'setup-title' }, title, el('span', { class: 'badge badge-small', dataset: { tone: ok ? 'pass' : 'warn' } },
          el('span', { class: 'badge-text' }, ok ? 'Ready' : 'Needs setup'))),
        el('span', { class: 'setup-message' }, message),
        path ? el('span', { class: 'setup-path', title: pathTitle || path }, path.replace(/^\/Users\/[^/]+/, '~')) : null),
      action);
  }

  function render() {
    const ready = status && status.worker.ok && status.runs_folder.ok;
    const aiActive = Boolean(status?.ai.active);
    const startText = !ready ? 'Continue anyway' : aiActive ? 'Start' : 'Continue without AI';
    fill(host, el('div', { class: 'welcome' },
      el('div', { class: 'welcome-card' },
        el('img', { class: 'welcome-mark', src: 'assets/mark.svg', alt: '', width: '48', height: '40' }),
        el('h1', { id: 'welcome-title' }, 'Welcome to MarinaFrame'),
        el('p', { class: 'welcome-lead' },
          'Drop a ship drawing set. The AI reads it and builds a draft hull while you watch; you check the few places that need an expert.'),
        status
          ? el('ul', { class: 'setup-list', 'aria-label': 'Setup check' }, aiRow(), workerRow(), runsRow())
          : el('p', { class: 'welcome-checking', role: 'status' }, el('span', { class: 'spinner', 'aria-hidden': 'true' }), 'Checking the setup…'),
        error ? el('p', { class: 'form-error', role: 'alert' }, error) : null,
        el('div', { class: 'welcome-actions' },
          el('button', { class: 'btn btn-large', type: 'button', disabled: checking, onclick: check }, icon('reset'), checking ? 'Checking…' : 'Check again'),
          el('span', { class: 'welcome-spacer' }),
          el('button', { class: 'btn btn-primary btn-large', type: 'button', disabled: !status, onclick: onDone }, startText)),
        el('p', { class: 'welcome-note' }, 'Every result is a draft. You can sign a draft off as a starting model; engineering approval happens outside this app.'))));
  }

  return {
    /** Show the screen and run the check. Resolves to the status. */
    show() {
      render();
      return check();
    },
    /** The check without showing the screen (at start). */
    check: () => invoke('get_setup_status', {}),
  };
}
