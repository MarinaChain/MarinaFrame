# Round digest (4 cases)

## dtmb5415-L0
- end: status `unknown`, reason `none`
- decisions: 0; tools: (none)
- first blocker: none found
- valid draft + STEP; requests 0; list cost n/a

## shipd-1-00045-L2
- end: status `unknown`, reason `none`
- decisions: 0; tools: (none)
- first blocker: none found
- valid draft + STEP; requests 0; list cost n/a

## shipd-1-00679-L0
- end: status `draft_not_verified`, reason `cancelled_after_worker_receipt`
- decisions: 7; tools: inspect_source > build_draft > propose_section > build_draft > render_candidate > propose_section > build_draft
- first blocker (event 17, operation_rejected:select_contours): `guess_requires_operator_confirmation` - guess_requires_operator_confirmation
  - model: s08's chosen stroke failed contour selection and was interpolated; author a blend of s07/s09 to give it a real, fair section.
  - model (x2): s08 correction accepted; rebuild the draft so the authored s03 and s08 sections are used, then render for visual inspection.
- valid draft + STEP; requests 8; list cost $0.0128
- score (dev truth): wrong; RMS 10.80% of half-beam; volume -8.1%

## shipd-1-00683-L2
- end: status `unknown`, reason `none`
- decisions: 0; tools: (none)
- first blocker: none found
- valid draft + STEP; requests 0; list cost n/a

## Across cases
- termination: none x3, cancelled_after_worker_receipt x1
- first blockers: none x3, operation_rejected:guess_requires_operator_confirmation x1
- tool totals: build_draft x3, propose_section x2, inspect_source x1, render_candidate x1
- requests 8; list cost $0.0128
- correct (dev truth, frozen gate): 0/4 cases (1 drafts scored)
- dominant failure: 4/4 valid drafts; 0/4 failed; most common end `none` (3/4); most common first blocker `none` (3/4)
