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
