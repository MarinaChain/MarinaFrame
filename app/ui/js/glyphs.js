// Compact icon chips: an icon (and a count) in place of a word. The word is the chip's
// accessible name and its tooltip title (tooltip.js); a longer explanation is the tooltip
// detail. Meaning never rests on the icon or on colour alone.

import { el, icon } from './dom.js';
import { tipAttributes } from './tooltip.js';
import * as fmt from './format.js';

/** Icon name of each section source label (index.html sprite, `i-<name>`). */
const SOURCE_ICONS = {
  traced: 'src-traced',
  repaired: 'src-repaired',
  interpolated: 'src-interpolated',
  ai_inferred: 'src-ai_inferred',
  ai_corrected: 'src-ai_corrected',
  omitted: 'src-omitted',
};

/** Icon name of each section state. */
const STATE_ICONS = { chosen: 'st-chosen', guessed: 'st-guessed', declined: 'st-declined', not_read: 'st-not_read' };
/** Badge tone of each section state (styles.css .badge[data-tone]). */
const STATE_TONES = { chosen: 'brand', guessed: 'draft', declined: 'warn' };

/** What each glyph means: the legend popover. Short; the chip tooltips give the case at hand. */
export const LEGEND = [
  { icon: 'src-traced', source: 'traced', name: 'Traced', meaning: 'Followed from the ink' },
  { icon: 'src-repaired', source: 'repaired', name: 'Repaired', meaning: 'Traced, small gaps closed' },
  { icon: 'src-interpolated', source: 'interpolated', name: 'Interpolated', meaning: 'No ink; bridged from neighbours' },
  { icon: 'src-ai_inferred', source: 'ai_inferred', name: 'AI inferred', meaning: 'Drawn by the AI, no ink' },
  { icon: 'src-ai_corrected', source: 'ai_corrected', name: 'AI corrected', meaning: 'Traced, then corrected by the AI' },
  { icon: 'src-omitted', source: 'omitted', name: 'Not drawn', meaning: 'Not on the sheet' },
  { icon: 'st-guessed', state: 'guessed', tone: 'draft', name: 'Guessed', meaning: 'A person must confirm it' },
  { icon: 'st-chosen', state: 'chosen', tone: 'brand', name: 'Line chosen', meaning: 'This line is in use' },
  { icon: 'st-declined', state: 'declined', tone: 'warn', name: 'Declined', meaning: 'No usable line' },
  { icon: 'flag', tone: 'warn', name: 'To check', meaning: 'Waits for a person' },
  { icon: 'read', name: 'Read', meaning: 'Value read from the drawing' },
  { icon: 'not-built', tone: 'warn', name: 'Not built', meaning: 'Part has no geometry' },
];

/**
 * An icon chip. `label` is the word: the accessible name and the tooltip title. `detail` is
 * the tooltip's full description. `count` shows a number after the icon (`countedName`
 * names the chip with its count, else "<count> <label>"). `focusable` puts the
 * chip in the tab order so its tooltip is reachable by keyboard; chips inside a labelled
 * control (a tile, a list button) leave it off; `hoverTip: false` also drops the tooltip.
 */
export function glyphChip(iconName, label, { count = null, countedName = null, tone = null, source = null, detail = null, focusable = true, hoverTip = true, small = true } = {}) {
  const classes = ['badge', 'badge-glyphchip'];
  if (small) classes.push('badge-small');
  if (source) classes.push('badge-source');
  const dataset = {};
  if (tone) dataset.tone = tone;
  if (source) dataset.source = source;
  const name = count === null ? label : countedName || `${count} ${label}`;
  const glyph = icon(iconName, 'badge-glyph');
  // A chip inside a labelled control is not focusable; it keeps a hover tooltip unless the
  // control has its own hover card (hoverTip: false).
  const tip = focusable || hoverTip ? tipAttributes(name, detail) : { attrs: { 'aria-label': name }, describer: null };
  return el('span', {
    class: classes.join(' '),
    role: 'img',
    tabindex: focusable ? '0' : null,
    dataset,
    ...tip.attrs,
  }, glyph, count === null ? null : el('span', { class: 'badge-count', 'aria-hidden': 'true' }, String(count)), tip.describer);
}

/** Source-label chip: the label's icon in its colour. */
export function sourceGlyph(label, { count = null, detail = null, focusable = true, hoverTip = true, small = true } = {}) {
  const name = fmt.sourceLabel(label);
  return glyphChip(SOURCE_ICONS[label] || 'src-omitted', name, {
    count, countedName: count === null ? null : `${fmt.plural(count, 'section')}: ${name}`, source: label, detail: detail || legendMeaning(label), focusable, hoverTip, small,
  });
}

/** The legend's meaning of a source label or state, as a default tooltip detail. */
function legendMeaning(key) {
  const item = LEGEND.find((entry) => entry.source === key || entry.state === key);
  return item ? `${item.meaning}.` : null;
}

/** Section-state chip: Guessed, Line chosen, Declined, Not read. */
export function stateGlyph(state, { detail = null, focusable = true, hoverTip = true, small = true } = {}) {
  return glyphChip(STATE_ICONS[state] || 'info', fmt.sectionStateLabel(state), {
    tone: STATE_TONES[state] || null, detail: detail || legendMeaning(state), focusable, hoverTip, small,
  });
}

/** The legend: a small popover listing every glyph with its word and meaning. */
export function legendPopover() {
  return el('details', { class: 'legend-pop' },
    el('summary', { class: 'btn btn-ghost btn-icon btn-small', ...tipAttributes('Icon legend').attrs }, icon('legend')),
    el('dl', { class: 'legend-list' }, ...LEGEND.flatMap((item) => {
      const glyph = icon(item.icon, 'badge-glyph');
      return [
        el('dt', {}, el('span', {
          class: item.source ? 'badge badge-small badge-glyphchip badge-source' : 'badge badge-small badge-glyphchip',
          dataset: { ...(item.source ? { source: item.source } : {}), ...(item.tone ? { tone: item.tone } : {}) },
          'aria-hidden': 'true',
        }, glyph), item.name),
        el('dd', {}, item.meaning),
      ];
    })));
}
