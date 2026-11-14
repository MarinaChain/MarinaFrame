// English interface strings (i18n.js). English is the fallback for every other locale.
// Ship terms are in glossary.js, not here.

export const EN = {
  'status.draft': 'Draft',
  'status.read': 'Read',
  'status.guessed': 'Best guess',
  'status.unknown': 'Unknown',
  'status.measured_from_scale': 'Measured',
  'status.derived_from_space_tops': 'Derived',
  'status.unconfirmed_from_uncertain_boxes': 'Unconfirmed',

  'ga.title': 'GA reading',
  'ga.meta': '{shipType} · Draft: a reading of the drawing for an engineer to check',
  'ga.particulars': 'Principal particulars',
  'ga.counts': 'Counts',
  'ga.measured': 'Measured on the drawing (not printed values)',
  'ga.shipTypeUnknown': 'Ship type not read',
  'ga.otherShipType': 'Other ship type',
  'ga.unlabelled': 'Unlabelled {kind}',
  'ga.printed': 'Printed “{text}”',
  'ga.inView': 'In {view}',
  'ga.number': 'No. {number}',

  'settings.language': 'Language',
  'settings.languageHelp': 'The language of the interface. Standard abbreviations (LBP, DWT, Cb) stay in English.',
  'settings.interface': 'Interface',
  'settings.interfaceHelp': 'Lite: the agent runs the design loop and you review its candidates. Advanced: you control each step. Applies to design projects.',
  'settings.lite': 'Lite',
  'settings.advanced': 'Advanced',

  // ui-p0-value: shared quantity display.
  'status.needs_review': 'Needs review',
  'method.empirical': 'Empirical',
  'method.thin_ship': 'Thin-ship theory',
  'method.cfd': 'CFD',
  'method.read_from_ga': 'Read from GA',
  'method.measured': 'Measured',
  'method.hydrostatics': 'Hydrostatics',

  // ui-p0-value: part quantity sources.
  'parts.source.traced': 'Read',
  'parts.source.ai_inferred': 'AI read',
  'parts.source.guessed': 'Guessed',
};
