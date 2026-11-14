// Plain-language labels and number formats. State wording comes from the locale string tables.

import { t, locale } from './i18n.js';

/** Date and time locale: the system's in English, Korean formats in Korean. */
const dateLocale = () => (locale() === 'ko' ? 'ko-KR' : undefined);

const STATUS_LABELS = new Set([
  'running', 'stalled', 'needs_review', 'draft', 'signed_off', 'declined', 'failed', 'cancelled',
  'paused', 'blocked',
]);
const SECTION_STATE_LABELS = new Set(['chosen', 'guessed', 'declined', 'not_read']);
const SOURCE_LABELS = new Set([
  'traced', 'printed', 'read', 'repaired', 'interpolated', 'ai_inferred', 'ai_corrected',
  'omitted',
]);
const CHECK_LABELS = new Set(['pass', 'fail', 'not_run']);
const CALL_STATE_LABELS = new Set(['completed', 'failed', 'not_sent', 'unknown']);

export const statusLabel = (status) => STATUS_LABELS.has(status) ? t(`fmt.status.${status}`) : status;
export const sectionStateLabel = (state) => SECTION_STATE_LABELS.has(state) ? t(`fmt.section.${state}`) : state;
export const sourceLabel = (label) => SOURCE_LABELS.has(label) ? t(`fmt.source.${label}`) : label.replace(/_/g, ' ');
export const checkLabel = (result) => CHECK_LABELS.has(result) ? t(`fmt.check.${result}`) : result;
export const callStateLabel = (state) => CALL_STATE_LABELS.has(state) ? t(`fmt.call.${state}`) : state;
export const isAiSource = (label) => label === 'ai_inferred' || label === 'ai_corrected';

// Each locale owns the full count phrase; unlisted nouns use its generic counter form.
const COUNT_NOUNS = new Set([
  'section', 'part', 'set', 'run', 'warning', 'model request', 'line', 'sheet file', 'item',
  'request', 'step', 'call', 'page', 'file', 'sounding table', 'steel table', 'OCX file',
]);

function countPhrase(count, noun, form) {
  const key = COUNT_NOUNS.has(noun) ? noun.replace(/ /g, '_') : 'generic';
  return t(`count.${key}.${form}`, { count, noun });
}

export function plural(count, noun) {
  return countPhrase(count, noun, count === 1 ? 'one' : 'other');
}

/** A list fact that reads well at zero, in the current language. */
export function countOf(count, noun) {
  return count ? plural(count, noun) : countPhrase(count, noun, 'zero');
}

export function decimal(value, digits) {
  return value.toLocaleString(dateLocale(), { minimumFractionDigits: digits, maximumFractionDigits: digits });
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
  return new Date(ms).toLocaleTimeString(dateLocale(), { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
}

export function fullTime(ms) {
  return new Date(ms).toLocaleString(dateLocale(), { dateStyle: 'medium', timeStyle: 'short' });
}

function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** Compact time for the run list: "Now", "12 min", "09:14", "Yesterday", "5 Nov". */
export function shortTime(ms) {
  const now = new Date();
  const then = new Date(ms);
  const minutes = Math.round((now - then) / 60_000);
  if (minutes < 1) return t('time.now');
  if (minutes < 60) return t('time.minutes', { minutes });
  if (sameDay(now, then)) return clock(ms);
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(yesterday, then)) return t('time.yesterday');
  return then.toLocaleDateString(dateLocale(), { day: 'numeric', month: 'short' });
}

/** Time for sentences: "just now", "12 min ago", "today at 09:14", "on 5 Nov at 16:40". */
export function relativeTime(ms) {
  const now = new Date();
  const then = new Date(ms);
  const minutes = Math.round((now - then) / 60_000);
  if (minutes < 1) return t('time.justNow');
  if (minutes < 60) return t('time.minutesAgo', { minutes });
  if (sameDay(now, then)) return t('time.todayAt', { time: clock(ms) });
  const day = then.toLocaleDateString(dateLocale(), { day: 'numeric', month: 'short' });
  return t('time.dayAt', { day, time: clock(ms) });
}

/** "2 lines found; took the best-supported one (score 0.62)." -> "2 lines · best 0.62". */
export function reasonFacts(reason) {
  const match = /^(\d+) lines? found\b.*\bscore ([\d.]+)/.exec(reason || '');
  return match ? `${plural(Number(match[1]), 'line')} · best ${match[2].replace(/\.$/, '')}` : null;
}

/** A heading before a colon that is at most this long becomes the card title on its own. */
const SHORT_HEADING_MAX = 24;

/**
 * A step title as a short heading and the rest: "Finished: Draft built from ..." gives
 * ["Finished", "Draft built from ..."]; the run's own stop step gives ["Stopped", its title].
 */
export function splitStepTitle(step, title) {
  if (step.kind === 'finish' && step.actor === 'code') return ['Stopped', title];
  const colon = title.indexOf(': ');
  if (colon > 0 && colon <= SHORT_HEADING_MAX) return [title.slice(0, colon), title.slice(colon + 2)];
  return [title, null];
}
