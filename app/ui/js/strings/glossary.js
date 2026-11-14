// Ship-term glossary: the one place for ship terms in English and Korean (i18n.js reads it as
// "term.<id>" for one item and "terms.<id>" for a heading over several).
//
// Status: draft. A designer of the pilot yard must review the Korean terms before the pilot,
// because each yard has its own words. Standard abbreviations stay in English in all locales:
// they are in `abbr` and are never translated.

export const GLOSSARY_STATUS = 'draft: needs review by a yard designer';

/** id: { en, enPlural?, ko, abbr? }. Korean has one form for one item and several. */
export const GLOSSARY = {
  // design: workbench particulars; length stays neutral when its basis is not supplied.
  length: { en: 'Length', ko: '길이', abbr: 'L' },
  cargo_capacity: { en: 'Cargo capacity', ko: '화물 용량' },
  service_speed: { en: 'Service speed', ko: '운항 속도', abbr: 'Vs' },
  brake_power: { en: 'Brake power', ko: '제동 출력', abbr: 'PB' },
  daily_fuel: { en: 'Fuel per day', ko: '일일 연료 소비량' },
  loa: { en: 'Length overall', ko: '전장', abbr: 'LOA' },
  lbp: { en: 'Length between perpendiculars', ko: '수선간장', abbr: 'LBP' },
  breadth_moulded: { en: 'Breadth (moulded)', ko: '형폭', abbr: 'B' },
  depth_moulded: { en: 'Depth (moulded)', ko: '형심', abbr: 'D' },
  design_draft: { en: 'Design draft', ko: '계획흘수', abbr: 'T' },
  scantling_draft: { en: 'Scantling draft', ko: '구조흘수', abbr: 'Ts' },
  deadweight: { en: 'Deadweight', ko: '재화중량', abbr: 'DWT' },
  lightship: { en: 'Lightship weight', ko: '경하중량' },
  displacement: { en: 'Displacement', ko: '배수량' },
  block_coefficient: { en: 'Block coefficient', ko: '방형계수', abbr: 'Cb' },
  stability: { en: 'Stability', ko: '복원성' },
  cargo_hold: { en: 'Cargo hold', enPlural: 'Cargo holds', ko: '화물창' },
  cargo_hatch: { en: 'Cargo hatch', enPlural: 'Cargo hatches', ko: '화물창구' },
  cargo_crane: { en: 'Cargo crane', enPlural: 'Cargo cranes', ko: '화물 크레인' },
  cargo_tank: { en: 'Cargo tank', enPlural: 'Cargo tanks', ko: '화물탱크' },
  slop_tank: { en: 'Slop tank', enPlural: 'Slop tanks', ko: '슬롭탱크' },
  ballast_tank: { en: 'Ballast tank', enPlural: 'Ballast tanks', ko: '평형수탱크' },
  fuel_tank: { en: 'Fuel tank', enPlural: 'Fuel tanks', ko: '연료유탱크' },
  other_tank: { en: 'Other tank', enPlural: 'Other tanks', ko: '기타 탱크' },
  engine_room: { en: 'Engine room', enPlural: 'Engine room', ko: '기관실' },
  accommodation_deck: { en: 'Accommodation deck', enPlural: 'Accommodation decks', ko: '거주구 갑판' },
  container_bay: { en: 'Container bay', enPlural: 'Container bays', ko: '컨테이너 베이' },
  other_space: { en: 'Other space', enPlural: 'Other spaces', ko: '기타 구역' },
  bulk_carrier: { en: 'Bulk carrier', ko: '벌크선' },
  tanker: { en: 'Tanker', ko: '탱커' },
  container_ship: { en: 'Container ship', ko: '컨테이너선' },
  general_cargo: { en: 'General cargo ship', ko: '일반화물선' },
};
