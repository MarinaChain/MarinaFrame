// Keyboard shortcut sheet: "?" (or the palette) shows every key the app answers to.
// Keep this list in step with the keydown handlers in js/app.js, js/mark.js and js/live.js.

import { t } from './i18n.js';
import { el } from './dom.js';

/** Platform modifier: ⌘ on macOS, Ctrl elsewhere. */
const MOD = /Mac|iPhone|iPad/.test(globalThis.navigator?.platform || '') ? '⌘' : 'Ctrl+';

const GROUP_KEYS = [
  ['ko3.shortcut.anywhere', [
    [`${MOD}K`, 'ko3.shortcut.goToAVesselAStationOrAnAction'],
    [`${MOD}N`, 'ko3.shortcut.newVesselFromDrawings'],
    [`${MOD},`, 'ko3.shortcut.settings'],
    [`${MOD}\\`, 'ko3.shortcut.showOrHideTheSidebar'],
    ['?', 'ko3.shortcut.thisList'],
  ]],
  ['ko3.shortcut.reviewADraft', [
    ['N', 'ko3.shortcut.nextSectionToCheck'],
    ['A', 'ko3.shortcut.acceptTheGuessedLine'],
    ['O', 'ko3.shortcut.useTheOtherLine'],
    ['M', 'ko3.shortcut.markTheDrawingAndSayWhatToFix'],
    ['[ ]', 'ko3.shortcut.previousOrNextSection'],
  ]],
  ['ko3.shortcut.views', [
    [`${MOD}1`, 'ko3.shortcut.drawingOnly'],
    [`${MOD}2`, 'ko3.shortcut.drawingAndModel'],
    [`${MOD}3`, 'ko3.shortcut.modelOnly'],
    [`${MOD}4`, 'ko3.shortcut.showOrHideTheDetailsColumn'],
    ['R', 'ko3.shortcut.resetThe3DView'],
    ['+ − 0', 'ko3.shortcut.zoomTheDrawingInOutToFitClickTheDrawingFirst'],
    ['← → ↑ ↓', 'ko3.shortcut.panTheDrawingClickTheDrawingFirst'],
  ]],
  ['ko3.shortcut.3dModelClickTheModelFirst', [
    ['1 2 3 4 5', 'ko3.shortcut.isoProfilePlanBodyPlanFromAheadFromAstern'],
    ['P', 'ko3.shortcut.orthographicOrPerspectiveCamera'],
    ['F', 'ko3.shortcut.fitTheSelectedPart'],
    ['C', 'ko3.shortcut.sectionCutPanelEscEndsTheCut'],
    ['G W E', 'ko3.shortcut.gridDesignWaterlinePlaneFeatureEdges'],
    ['S', 'ko3.shortcut.sectionPlanesAtEverySectionOrAtTheSelectedOneOnly'],
    ['X', 'ko3.shortcut.seeThroughHullTheHullFaintThePartsAndTanksInsideSolid'],
    ['Z', 'ko3.shortcut.fairnessZebraStripesCurvatureMapOff'],
  ]],
  ['ko3.shortcut.reviewPartsPartsTab', [
    ['A', 'ko3.shortcut.acceptThePartAsADraftPart'],
    ['M', 'ko3.shortcut.markThePartAndSayWhatToChange'],
    ['N', 'ko3.shortcut.nextPartToReview'],
  ]],
  ['ko3.shortcut.newVesselPages', [
    ['[ ]', 'ko3.shortcut.previousOrNextPage'],
    ['S', 'ko3.shortcut.skipOrKeepThePageShown'],
  ]],
  ['ko3.shortcut.replayARun', [
    ['Space', 'ko3.shortcut.playOrPause'],
    ['← →', 'ko3.shortcut.previousOrNextAIStep'],
  ]],
];

/** Shortcut labels resolve on demand; key names are unchanged in both languages. */
export function shortcutGroups() {
  return GROUP_KEYS.map(([title, keys]) => [t(title), keys.map(([key, label]) => [key, t(label)])]);
}

export function createShortcutSheet() {
  const close = el('button', { class: 'btn', type: 'button', onclick: () => dialog.close() }, t('ko3.shortcuts.close'));
  const dialog = el('dialog', { class: 'shortcuts', 'aria-labelledby': 'shortcuts-title' },
    el('h2', { id: 'shortcuts-title' }, t('ko3.shortcuts.title')),
    el('div', { class: 'shortcut-groups' }, ...shortcutGroups().map(([title, keys]) => el('section', { class: 'shortcut-group' },
      el('h3', {}, title),
      el('dl', {}, ...keys.flatMap(([key, what]) => [
        el('dt', {}, ...key.split(' ').map((part) => el('kbd', { class: 'key-hint' }, part))),
        el('dd', {}, what),
      ]))))),
    el('div', { class: 'shortcuts-actions' }, close));
  dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
  document.body.append(dialog);
  return {
    open() {
      close.textContent = t('ko3.shortcuts.close');
      dialog.querySelector('h2').textContent = t('ko3.shortcuts.title');
      const sections = dialog.querySelectorAll('.shortcut-group');
      shortcutGroups().forEach(([title, keys], index) => {
        sections[index].querySelector('h3').textContent = title;
        sections[index].querySelectorAll('dd').forEach((node, row) => { node.textContent = keys[row][1]; });
      });
      if (!dialog.open) dialog.showModal();
      close.focus();
    },
  };
}
