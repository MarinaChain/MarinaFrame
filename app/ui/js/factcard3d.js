// The fact card of the picked part in the 3D view: name, kind, key values with units, a source
// label chip on each value and a link to the source where the run knows it. `cardFor` builds the
// data (no DOM, tested in ui-tests/factcard3d.test.mjs); `renderFactCard` draws it.
//
// Tank values come from the run's capacity plan row (tanks.js capacityFields), steel values from
// the members the structure GLB lists, the other parts from the run's part record (its arguments
// with their source labels). Nothing is computed here but sizes and frames from the part's box.

import { el, icon } from './dom.js';
import { tipAttributes } from './tooltip.js';
import { frameAt, frameLabel } from './reference3d.js';
import { capacityFields, sourceChip, tankNumber } from './tanks.js';
import { kindWord } from './visibility3d.js';
import { swatchToken } from './parts_panel3d.js';

/** The capacity plan values the card shows (the Parts tab and the capacity plan have them all). */
const TANK_KEY_VALUES = ['Content', 'Frames', 'Volume 100 %', 'Weight 98 %', 'LCG', 'TCG', 'VCG'];

/** Plate thickness of steel members: "8 mm", or "6 to 10 mm" when the members differ. */
export function thicknessText(members) {
  const values = (members || []).map((member) => member.thickness_mm).filter(Number.isFinite);
  if (!values.length) return '—';
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  return lo === hi ? `${lo} mm` : `${lo} to ${hi} mm`;
}

/** The source label most members share ("guessed" wins a tie, so a draft never looks surer). */
export function dominantSource(members) {
  const counts = new Map();
  for (const member of members || []) if (member.thickness_source) counts.set(member.thickness_source, (counts.get(member.thickness_source) || 0) + 1);
  let best = null;
  for (const [label, count] of counts) {
    if (!best || count > best.count || (count === best.count && label === 'guessed')) best = { label, count };
  }
  return best?.label || null;
}

/** "Fr 6 to Fr 14" for an x range, or "—" with no reference. */
export function framesText(minX, maxX, reference) {
  if (!reference || !Number.isFinite(minX) || !Number.isFinite(maxX)) return '—';
  const spacing = reference.frameSpacingM.value;
  const zero = reference.frameZeroX.value;
  const first = frameLabel(Math.round(frameAt(minX, spacing, zero)));
  const last = frameLabel(Math.round(frameAt(maxX, spacing, zero)));
  return first === last ? first : `${first} to ${last}`;
}

/** Length, breadth and height of a box as "5.00 × 3.00 × 1.20 m". */
export function sizeText(box) {
  if (!box) return '—';
  const side = (k) => (box.max[k] - box.min[k]).toFixed(2);
  return `${side(0)} × ${side(1)} × ${side(2)} m`;
}

/**
 * The card of one part. `entry` is a list entry (visibility3d.js describeParts), `extras` the mesh's
 * GLB extras, `box` { min, max } in metres (or null), `reference` the hull reference (or null),
 * `context` what the run knows: { row (capacity plan row), component (part record), source ({ label, open }) }.
 * Returns { id, name, kind, kindWord, token, source (the main label), facts [{ name, value, source }],
 * note, link ({ label, open } or null) }.
 */
export function cardFor({ entry, extras = {}, box = null, reference = null, context = {} }) {
  const { row = null, component = null, source = null } = context;
  const base = { id: entry.id, name: entry.name, kind: entry.kind, kindWord: kindWord(entry.kind), token: swatchToken(entry), facts: [], note: '', source: null, link: source || null };
  const size = { name: 'Size', value: sizeText(box), source: null };
  const frames = { name: 'Frames', value: box ? framesText(box.min[0], box.max[0], reference) : '—', source: null };

  if (entry.kind === 'tank') {
    if (row) {
      // The capacity plan row, as the Parts tab shows it (the Name is the card's title).
      const fields = capacityFields(row).filter((field) => TANK_KEY_VALUES.includes(field.name));
      return { ...base, source: row.sources?.volume || null, facts: [...fields, size], note: row.notes || '' };
    }
    const labels = extras.source_labels || {};
    return {
      ...base, source: labels.content_class || null,
      facts: [{ name: 'Content', value: extras.content_label || extras.content || '—', source: labels.content_class || null }, frames, size],
      note: 'This tank is not in the run\'s capacity plan.',
    };
  }

  if (entry.kind === 'steel') {
    const members = extras.members || [];
    const label = dominantSource(members);
    return {
      ...base, source: label,
      facts: [
        { name: 'Members', value: String(members.length), source: null },
        { name: 'Thickness', value: thicknessText(members), source: label },
        frames, size,
      ],
      note: 'Steel is shown by member group. Draft, not for construction.',
    };
  }

  // The hull and the other parts: the part record's values with their labels, else the box.
  const facts = [];
  for (const argument of component?.arguments || []) facts.push({ name: argument.name.charAt(0).toUpperCase() + argument.name.slice(1), value: argument.value, source: argument.source || null });
  if (Number.isFinite(component?.volume_m3)) facts.push({ name: 'Volume', value: tankNumber(component.volume_m3, 2, 'm³'), source: null });
  facts.push(frames, size);
  const labels = (component?.arguments || []).map((argument) => argument.source);
  const weakest = ['guessed', 'ai_inferred', 'traced'].find((label) => labels.includes(label)) || null;
  return { ...base, source: weakest, facts, note: '' };
}

/** A docked card shows this many facts until it is expanded. */
export const KEY_FACTS = 3;

/**
 * The facts a docked card shows folded: the first `count` with a value (the card lists the
 * important ones first: the part record's values, the capacity plan's content, frames, volume).
 * Returns { facts, more } with `more` the number of facts left for the expanded card.
 */
export function keyFacts(card, count = KEY_FACTS) {
  const known = card.facts.filter((fact) => fact.value && fact.value !== '—');
  const facts = known.slice(0, count);
  return { facts, more: card.facts.length - facts.length };
}

/**
 * The card as DOM. `onClose()` clears the pick; a link's `open()` runs when it is pressed.
 * In the details column the card is whole. Docked in the 3D pane (`docked`) it shows its title
 * row and `keyCount` key facts; the title row is a button that expands it to every fact.
 */
export function renderFactCard(card, { onClose, docked = false, expanded = false, keyCount = KEY_FACTS, onToggle = () => {} }) {
  const close = el('button', { class: 'model-part-tool', type: 'button', 'aria-label': 'Close the card', onclick: () => onClose(), ...tipAttributes('Close the card').attrs }, icon('close'));
  const whole = !docked || expanded;
  const shown = whole ? { facts: card.facts, more: 0 } : keyFacts(card, keyCount);
  const link = whole && card.link
    ? el('button', { class: 'model-card-link', type: 'button', onclick: () => card.link.open?.() }, icon('drawing'), el('span', {}, card.link.label || 'Source'))
    : null;
  const more = shown.more ? `${shown.more} more` : 'Fewer';
  const title = [el('strong', {}, card.name), el('span', {}, card.kindWord, docked && (shown.more || expanded) ? ` · ${more}` : '')];
  const titleNode = docked
    ? el('button', {
      class: 'model-card-title model-card-toggle', type: 'button', 'aria-expanded': String(expanded),
      ...tipAttributes(expanded ? 'Show the key facts only' : 'Show every fact').attrs, 'aria-label': `${card.name}, ${card.kindWord}`,
      onclick: () => onToggle(),
    }, ...title)
    : el('div', { class: 'model-card-title' }, ...title);
  const classes = ['model-card', docked ? 'is-docked' : 'is-column', shown.facts.length ? '' : 'is-collapsed'].filter(Boolean).join(' ');
  return el('section', { class: classes, 'aria-label': `${card.name}, ${card.kindWord}` },
    el('header', { class: 'model-card-head' },
      el('span', { class: 'model-swatch', style: { background: `var(${card.token})` }, 'aria-hidden': 'true' }),
      titleNode,
      sourceChip(card.source),
      close),
    shown.facts.length ? el('dl', { class: 'model-card-facts' }, ...shown.facts.flatMap((fact) => [
      el('dt', {}, fact.name),
      el('dd', {}, fact.value, ' ', sourceChip(fact.source)),
    ])) : null,
    whole && card.note ? el('p', { class: 'model-card-note' }, card.note) : null,
    link);
}
