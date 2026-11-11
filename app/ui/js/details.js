// The run-details column (selection review, Thinking, Steps, Checks, Calls, Evidence, Sources) folds
// to a thin rail of icons, so the drawing and the 3D model get the width. The pure rules live here;
// js/inspector.js wires them to the page.

/** Key that toggles the column together with ⌘ (Ctrl). 1, 2 and 3 pick the layout. */
export const DETAILS_KEY = '4';

/**
 * With no stored choice, a window at least this wide (CSS px) starts with the column open; a
 * laptop window starts with the rail, so the drawing and the model get the width.
 */
export const WIDE_WINDOW_PX = 1800;

/**
 * Stored choice -> open or not. "open" and "closed" are a person's choice; anything else (none
 * yet, broken storage) follows the window width.
 */
export function isDetailsOpen(stored, windowWidth = WIDE_WINDOW_PX) {
  if (stored === 'open') return true;
  if (stored === 'closed') return false;
  return windowWidth >= WIDE_WINDOW_PX;
}

/** The value to store for a choice. */
export function storedDetails(open) {
  return open ? 'open' : 'closed';
}

/** The count badge on the toggle: the open review items, "99+" when very many, hidden at zero. */
export function reviewBadge(count) {
  const items = Math.max(0, Math.floor(Number(count) || 0));
  return { hidden: items === 0, text: items > 99 ? '99+' : String(items), items };
}

/** Title for the toggle and the edge handle; the badge count goes into the spoken name. */
export function toggleNames(open, count) {
  const title = `${open ? 'Hide' : 'Show'} details (⌘${DETAILS_KEY})`;
  const items = reviewBadge(count).items;
  const spoken = `${open ? 'Hide' : 'Show'} details${items ? `, ${items} to check` : ''}`;
  return { title, spoken };
}

/** Name of the rail's review button: "2 to check (N)"; null hides it when nothing is open. */
export function reviewRailName(count) {
  const badge = reviewBadge(count);
  if (badge.hidden) return null;
  return { title: `${badge.items} to check (N)`, spoken: `Review, ${badge.items} to check` };
}

/**
 * Whether a step row of the Thinking tab shows its detail: as the person last left it, else
 * open only when the step waits for the person (it offers a button, such as Keep anyway).
 */
export function stepStartsOpen(sequence, { expanded, collapsed, waits }) {
  if (expanded.has(sequence)) return true;
  if (collapsed.has(sequence)) return false;
  return waits;
}

/** The run-detail tabs: an icon each; the word is the tooltip title and the spoken name. */
export const TAB_META = {
  thinking: { icon: 'thinking', word: 'Thinking', detail: 'What the AI thought, step by step.' },
  timeline: { icon: 'steps', word: 'Steps', detail: 'Each AI step in order, with its time and cost.' },
  checks: { icon: 'checks', word: 'Checks', detail: 'The automatic checks on the result.' },
  model: { icon: 'calls', word: 'Calls', detail: 'Each call to the AI model, with its cost.' },
  evidence: { icon: 'evidence', word: 'Evidence', detail: 'The marks on the drawing that the result rests on.' },
  sources: { icon: 'sources', word: 'Sources', detail: 'The files this run was given: drawings, sheets and spec inputs.' },
};

/** Spoken name of a tab with its count: "Checks, 2 failing", "Calls, 5". */
export function tabName(tab, count = 0, { failing = false } = {}) {
  const word = TAB_META[tab].word;
  if (!count) return word;
  return `${word}, ${count}${failing ? ' failing' : ''}`;
}

/** The run-detail tabs in their order on the page. */
export const TABS = Object.keys(TAB_META);

/** Arrow keys walk the tabs: the next or the previous one, wrapping at the ends. */
const TAB_STEPS = { ArrowRight: 1, ArrowLeft: -1 };

/** The tab that `key` moves to from `tab`, or null when the key does not move between tabs. */
export function tabAfter(tab, key) {
  const step = TAB_STEPS[key];
  if (!step) return null;
  return TABS[(TABS.indexOf(tab) + step + TABS.length) % TABS.length];
}
