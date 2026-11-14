// Korean interface strings (i18n.js). A key that is missing here shows in English.
// Ship terms are in glossary.js. Status words follow the draft rule: never 승인 or 검증.

export const KO = {
  'status.draft': '초안',
  'status.read': '판독',
  'status.guessed': '추정',
  'status.unknown': '알 수 없음',
  'status.measured_from_scale': '측정',
  'status.derived_from_space_tops': '산출',
  'status.unconfirmed_from_uncertain_boxes': '미확인',

  'ga.title': 'GA 판독',
  'ga.meta': '{shipType} · 초안: 엔지니어 검토용 도면 판독 결과',
  'ga.particulars': '주요 제원',
  'ga.counts': '수량',
  'ga.measured': '도면에서 측정한 값 (도면 표기값 아님)',
  'ga.shipTypeUnknown': '선종 미판독',
  'ga.otherShipType': '기타 선종',
  'ga.unlabelled': '표기 없는 {kind}',
  'ga.printed': '도면 표기 “{text}”',
  'ga.inView': '{view} 도면',
  'ga.number': 'No. {number}',

  'settings.language': '언어',
  'settings.languageHelp': '화면 언어입니다. LBP, DWT, Cb 같은 표준 약어는 영어로 표시합니다.',
  'settings.interface': '화면 모드',
  'settings.interfaceHelp': 'Lite: 에이전트가 설계 루프를 실행하고 사용자는 후보안을 검토합니다. Advanced: 각 단계를 직접 제어합니다. 설계 프로젝트에 적용됩니다.',
  'settings.lite': 'Lite',
  'settings.advanced': 'Advanced',

  // ui-p0-value: shared quantity display.
  'status.needs_review': '검토 필요',
  'method.empirical': '경험식',
  'method.thin_ship': '박선 이론',
  'method.cfd': 'CFD',
  'method.read_from_ga': 'GA 판독',
  'method.measured': '도면 측정',
  'method.hydrostatics': '정수역학 계산',
};
