// Which parts of the whole-vessel 3D view show: hide, isolate and show all, and the searchable
// part list. No DOM and no three.js here, so the rules are tested alone (ui-tests/visibility3d.test.mjs).
//
// One word per idea:
//   Hide     the part is not drawn and cannot be picked.
//   Isolate  the part stays as it is; every other part turns ghost (faint, not pickable).
//   Show all ends every hide and the isolate.

/** What a part looks like now. */
export const PART_STATES = { shown: 'shown', ghost: 'ghost', hidden: 'hidden' };

/** Kinds of part in list order, with the word the list and the card show. */
export const PART_KINDS = [
  ['hull', 'Hull'],
  ['part', 'Part'],
  ['tank', 'Tank'],
  ['steel', 'Steel'],
];
const KIND_WORDS = new Map(PART_KINDS);

/** The word of a part kind ("tank" -> "Tank"). */
export function kindWord(kind) {
  return KIND_WORDS.get(kind) || 'Part';
}

/** Part id of a steel member group; steel meshes carry no part node name of their own. */
export function steelPartId(group) {
  return `steel:${group}`;
}

/** The shell parts that are the hull itself (the GLB names it hull, or ends or starts with hull). */
export const HULL_NAME = /(^|_)hull($|_)/;

/**
 * The hide and isolate state. `stateOf(id)`: a hidden part is hidden; else with an isolated part
 * every other part is ghost; else shown. `version` rises on every change, so a view can skip work.
 */
export function createPartVisibility() {
  const hidden = new Set();
  let isolated = null;
  let version = 0;
  const changed = () => { version += 1; };
  return {
    get version() { return version; },
    get isolatedId() { return isolated; },
    get hiddenIds() { return [...hidden]; },
    /** True when any part is hidden or isolated (Show all has something to do). */
    get active() { return hidden.size > 0 || isolated !== null; },
    stateOf(id) {
      if (hidden.has(id)) return PART_STATES.hidden;
      if (isolated !== null && id !== isolated) return PART_STATES.ghost;
      return PART_STATES.shown;
    },
    /** Hide a part, or show it again when it is hidden (a toggle). */
    toggleHide(id) {
      if (hidden.has(id)) hidden.delete(id);
      else hidden.add(id);
      changed();
    },
    /** Isolate a part (it is shown, whatever it was); isolating the isolated part ends the isolate. */
    toggleIsolate(id) {
      if (isolated === id) {
        isolated = null;
      } else {
        isolated = id;
        hidden.delete(id);
      }
      changed();
    },
    showAll() {
      hidden.clear();
      isolated = null;
      changed();
    },
    /** Forget ids that are not in the model any more (a new model was loaded). */
    keepOnly(ids) {
      const known = new Set(ids);
      for (const id of [...hidden]) if (!known.has(id)) hidden.delete(id);
      if (isolated !== null && !known.has(isolated)) isolated = null;
      changed();
    },
  };
}

/** "hull_body" -> "Hull body": a part's node name as a title, when the file gives no label. */
export function humanName(id) {
  const text = (id || '').replace(/[_-]+/g, ' ').trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * The part list from what the model holds. `shell` is [{ partId, label }] (the hull and the other
 * whole-vessel parts), `tanks` [{ partId, label, content_class, content_label }], `steel`
 * [{ group, group_label, members }]. Returns [{ id, name, kind, detail, contentClass, group }]
 * in list order: hull, other parts, tanks by name, steel groups.
 */
export function describeParts({ shell = [], tanks = [], steel = [] }) {
  const entries = [];
  for (const part of shell) {
    const kind = HULL_NAME.test(part.partId || '') ? 'hull' : 'part';
    entries.push({ id: part.partId, name: part.label || humanName(part.partId), kind, detail: '', contentClass: null, group: null });
  }
  entries.sort((a, b) => (a.kind === b.kind ? 0 : a.kind === 'hull' ? -1 : 1));
  const tankEntries = tanks.map((tank) => ({
    id: tank.partId, name: tank.label || tank.partId, kind: 'tank',
    detail: tank.content_label || '', contentClass: tank.content_class || 'other', group: null,
  }));
  tankEntries.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
  entries.push(...tankEntries);
  for (const group of steel) {
    const members = group.members?.length || 0;
    entries.push({
      id: steelPartId(group.group), name: group.group_label || group.group, kind: 'steel',
      detail: members ? `${members} ${members === 1 ? 'member' : 'members'}` : '', contentClass: null, group: group.group,
    });
  }
  return entries;
}

/**
 * The entries a search leaves: every word of `query` must start a word of the name, the kind
 * word or the detail (case does not matter). An empty query keeps all.
 */
export function filterParts(entries, query) {
  const words = (query || '').toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return entries;
  return entries.filter((entry) => {
    const haystack = `${entry.name} ${kindWord(entry.kind)} ${entry.detail}`.toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(Boolean);
    return words.every((word) => haystack.some((token) => token.startsWith(word)));
  });
}
