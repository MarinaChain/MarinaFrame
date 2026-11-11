// The words of the run bar: one status sentence, its one primary action, and the detail lines of
// the run drawer. Pure functions of the TaskView (no DOM), so the wording is tested directly
// (ui-tests/run_status.test.mjs). The run bar itself is drawn in js/run_header.js.

import * as fmt from './format.js';
import { needsCheck } from './run_facts.js';

/** Sheet states that need a new file from the person (js/sheets.js shows the same states). */
const SHEET_PROBLEMS = new Set(['unreadable', 'wrong_scale', 'missing']);
const SHEET_PROBLEM_WORDS = { unreadable: 'unreadable', wrong_scale: 'wrong scale', missing: 'missing' };

/** "Lines too faint." -> "lines too faint": a reason read inside a sentence. */
function inlineReason(reason) {
  const text = String(reason || '').trim().replace(/\.+$/, '');
  return text ? text.charAt(0).toLowerCase() + text.slice(1) : '';
}

/** The sheets of the run that need a new file, in the backend's order. */
export function problemSheets(view) {
  return (view?.sheet_review?.sheets || []).filter((sheet) => SHEET_PROBLEMS.has(sheet.status));
}

/**
 * The status sentence of a run: its parts in reading order and the one primary action.
 * Parts: the run status, the sections that wait for a person, and the first sheet that needs a
 * new file. Action: replace that sheet ({ kind: 'replace', sheetId, label }), or null.
 */
export function statusSentence(view) {
  if (!view) return { parts: [], action: null };
  const parts = [fmt.statusLabel(view.summary.status)];
  const open = (view.sections || []).filter(needsCheck).length;
  if (open) parts.push(`${fmt.plural(open, 'section')} ${open === 1 ? 'needs' : 'need'} you`);
  const sheets = problemSheets(view);
  let action = null;
  if (sheets.length) {
    const first = sheets[0];
    const why = inlineReason(first.reason) || SHEET_PROBLEM_WORDS[first.status];
    parts.push(`${first.label}: ${why}${sheets.length > 1 ? ` (+${sheets.length - 1} more)` : ''}`);
    action = { kind: 'replace', sheetId: first.id, label: first.label };
  }
  if (parts.length === 1 && !open && (view.sections || []).length) parts.push('nothing to check');
  return { parts, action };
}

/** "Traced" -> "traced"; "AI corrected" keeps its capitals. */
function inlineLabel(label) {
  const word = fmt.sourceLabel(label);
  return word.startsWith('AI ') ? word : word.charAt(0).toLowerCase() + word.slice(1);
}

/** "1 traced · 1 interpolated · 1 AI corrected · 2 warnings": the review in words. */
export function reviewWords(view) {
  const words = (view?.source_counts || [])
    .filter((entry) => entry.count > 0)
    .map((entry) => `${entry.count} ${inlineLabel(entry.label)}`);
  const warnings = (view?.warnings || []).length;
  if (warnings) words.push(fmt.plural(warnings, 'warning'));
  return words.join(' · ');
}

/** "0.8-14 %" (a band chip) -> "0.8–14 % from the drawing". */
export function errorWords(chip) {
  return `${String(chip).replace(/(\d)\s*-\s*(\d)/g, '$1–$2')} from the drawing`;
}

/**
 * "3 model requests · $0.0121 list cost", or null without model activity. The Run tab shows it
 * only with Settings > "Show costs and timings" on; History shows it always.
 */
export function costWords(view) {
  const activity = view?.activity;
  if (!activity) return null;
  const cost = activity.list_cost_complete ? fmt.usd(activity.list_cost_usd) : `at least ${fmt.usd(activity.list_cost_usd)}`;
  return `${fmt.plural(activity.requests, 'model request')} · ${cost} list cost`;
}
