/**
 * How a run first shows: `{ concept, credit, note, whole_vessel_first, section_lines,
 * see_through }`. The web demo gives it from its manifest (`view.demo`, static/backend.js); the
 * desktop app reads it from the run folder (`view.presentation`, app/core/src/presentation.rs).
 * The web demo's value wins, so the public site shows what its selection says.
 */
export function presentationOf(view) {
  return view?.demo || view?.presentation || null;
}
