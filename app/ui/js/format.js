// Plain-language labels and number formats. All user-facing wording for states lives here.

const STATUS_LABELS = {
  running: 'Running',
  needs_review: 'Needs review',
  draft: 'Draft',
  signed_off: 'Signed off', // a person's sign-off: usable as a starting model. Never "approved".
  declined: 'Declined',
  failed: 'Failed',
  cancelled: 'Cancelled',
  paused: 'Paused',
  blocked: 'Blocked',
};

const SECTION_STATE_LABELS = { chosen: 'Line chosen', guessed: 'Guessed', declined: 'Declined', not_read: 'Not read' };
const SOURCE_LABELS = {
  traced: 'Traced',
  read: 'Read by code',
  repaired: 'Repaired',
  interpolated: 'Interpolated',
  ai_inferred: 'AI inferred',
  ai_corrected: 'AI corrected',
  omitted: 'Not drawn',
};
const CHECK_LABELS = { pass: 'Pass', fail: 'Fail', not_run: 'Not run' };
const CALL_STATE_LABELS = { completed: 'Answered', failed: 'Failed', not_sent: 'Not sent', unknown: 'Result unknown' };

export const statusLabel = (status) => STATUS_LABELS[status] || status;
export const sectionStateLabel = (state) => SECTION_STATE_LABELS[state] || state;
export const sourceLabel = (label) => SOURCE_LABELS[label] || label.replace(/_/g, ' ');
export const isAiSource = (label) => label === 'ai_inferred' || label === 'ai_corrected';
export const checkLabel = (result) => CHECK_LABELS[result] || result;
export const callStateLabel = (state) => CALL_STATE_LABELS[state] || state;

export function plural(count, noun) {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

/** "No sections", "1 section", "3 sections": a list fact that reads well at zero. */
export function countOf(count, noun) {
  return count ? plural(count, noun) : `No ${noun}s`;
}

export function decimal(value, digits) {
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function metres(value, digits = 1) {
  return `${decimal(value, digits)} m`;
}

/**
 * Put the place of each section in place of its id in a step text: the backend titles name
 * sections by id ("Drew the section at st12"), and the rest of the app names them by place
 * ("12.0 m"). `places` maps id to place. Only whole ids are replaced, longest first.
 *
 * Sheet-only runs number their sections "1", "2", ... A bare number in free text is usually a
 * dimension ("depth 7.63 m"), so an id made only of digits is replaced only right after the
 * backend's own words "section at" or "line for", and never inside a decimal number.
 */
export function withPlaces(text, places) {
  if (!text || !places?.size) return text;
  const escape = (id) => id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const byLength = (a, b) => b.length - a.length;
  const named = [...places.keys()].filter((id) => !/^\d+$/.test(id)).sort(byLength).map(escape);
  const numbered = [...places.keys()].filter((id) => /^\d+$/.test(id)).sort(byLength);
  let result = text;
  if (named.length) {
    const pattern = new RegExp(`(?<![\\w-])(${named.join('|')})(?![\\w-])`, 'g');
    result = result.replace(pattern, (id) => places.get(id));
  }
  if (numbered.length) {
    const pattern = new RegExp(`(?<=\\b(?:section at|line for) )(${numbered.join('|')})(?![\\w.-])`, 'g');
    result = result.replace(pattern, (id) => places.get(id));
  }
  return result;
}

/** A small length given in metres, shown in whole millimetres (ink distances). */
export function millimetres(valueM) {
  return `${Math.round(valueM * 1000).toLocaleString()} mm`;
}

export function integer(value) {
  return value.toLocaleString();
}

export function usd(value) {
  // Model calls cost fractions of a cent; show enough digits to tell them apart.
  const digits = value > 0 && value < 0.1 ? 4 : 2;
  return `$${value.toFixed(digits)}`;
}

export function bytes(value) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = value;
  let unit = 0;
  while (size >= 1000 && unit < units.length - 1) {
    size /= 1000;
    unit += 1;
  }
  return `${size >= 10 || unit === 0 ? Math.round(size) : size.toFixed(1)} ${units[unit]}`;
}

export function clock(ms) {
  return new Date(ms).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
}

export function fullTime(ms) {
  return new Date(ms).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** Compact time for the run list: "Now", "12 min", "09:14", "Yesterday", "5 Nov". */
export function shortTime(ms) {
  const now = new Date();
  const then = new Date(ms);
  const minutes = Math.round((now - then) / 60_000);
  if (minutes < 1) return 'Now';
  if (minutes < 60) return `${minutes} min`;
  if (sameDay(now, then)) return clock(ms);
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(yesterday, then)) return 'Yesterday';
  return then.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

/** Time for sentences: "just now", "12 min ago", "today at 09:14", "on 5 Nov at 16:40". */
export function relativeTime(ms) {
  const now = new Date();
  const then = new Date(ms);
  const minutes = Math.round((now - then) / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  if (sameDay(now, then)) return `today at ${clock(ms)}`;
  return `on ${then.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })} at ${clock(ms)}`;
}
