// The run-details column (selection review, Thinking, Steps, Checks, Calls, Evidence) can be
// hidden, for people who only want the results. The pure rules live here; js/app.js wires them
// to the page.

/** Key that toggles the column together with ⌘ (Ctrl). 1, 2 and 3 pick the layout. */
export const DETAILS_KEY = '4';

/** Stored choice -> open or not. Anything but "closed" (missing, broken storage) means open. */
export function isDetailsOpen(stored) {
  return stored !== 'closed';
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

/** The run-detail tabs: an icon each; the word is the tooltip title and the spoken name. */
export const TAB_META = {
  thinking: { icon: 'thinking', word: 'Thinking', detail: 'What the AI thought, step by step.' },
  timeline: { icon: 'steps', word: 'Steps', detail: 'Each AI step in order, with its time and cost.' },
  checks: { icon: 'checks', word: 'Checks', detail: 'The automatic checks on the result.' },
  model: { icon: 'calls', word: 'Calls', detail: 'Each call to the AI model, with its cost.' },
  evidence: { icon: 'evidence', word: 'Evidence', detail: 'The marks on the drawing that the result rests on.' },
};

/** Spoken name of a tab with its count: "Checks, 2 failing", "Calls, 5". */
export function tabName(tab, count = 0, { failing = false } = {}) {
  const word = TAB_META[tab].word;
  if (!count) return word;
  return `${word}, ${count}${failing ? ' failing' : ''}`;
}
