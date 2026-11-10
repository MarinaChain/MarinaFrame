// The app-wide ⌘ (Ctrl) shortcuts as plain rules: which command a key press asks for.
// js/commands.js runs the command; js/shortcuts.js lists the keys for people.

import { DETAILS_KEY } from './details.js';

/** ⌘1, ⌘2 and ⌘3 pick the layout of the run workspace. */
const LAYOUT_KEYS = { 1: 'drawing', 2: 'split', 3: 'model' };

/**
 * The command a ⌘ (Ctrl) key press asks for, or null: `{ command }`, and `{ command:
 * 'layout', layout }` for the layout keys. Key presses without ⌘ or Ctrl give null.
 */
export function shortcutCommand({ key, metaKey = false, ctrlKey = false, shiftKey = false }) {
  if (!metaKey && !ctrlKey) return null;
  if (key === '\\') return { command: 'toggle-rail' };
  if (key.toLowerCase() === 'n') return { command: shiftKey ? 'new-run' : 'new-vessel' };
  if (key.toLowerCase() === 'k') return { command: 'palette' };
  if (key === ',') return { command: 'settings' };
  if (key === DETAILS_KEY) return { command: 'details' };
  if (key in LAYOUT_KEYS) return { command: 'layout', layout: LAYOUT_KEYS[key] };
  return null;
}
