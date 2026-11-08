# Round digest (4 cases)

## dtmb5415-L0
- end: status `draft_not_verified`, reason `open_guesses_block_review`
- decisions: 13; tools: inspect_source > render_candidate > inspect_source > propose_section > inspect_source > propose_section > inspect_source x2 > build_draft > propose_section > render_candidate x2 > finish
- first blocker (event 12, model_output_rejected:None): `investigation_argument_bounds` - investigation_argument_bounds
  - model: The plan view looks like a plausible hull; I render the profile view to check the sheer and keel before validating and finishing.
  - model (x2): All panels inspected, draft valid, body/plan/profile rendered and consistent; the only anomaly (s09 bulbous foot) resisted three corrections, so it is handed to a person rather than abandoned.
- valid draft + STEP; requests 16; list cost $0.0252
- score (dev truth): wrong; RMS 4.47% of half-beam; volume +0.9%

## shipd-1-00045-L2
- end: status `draft_not_verified`, reason `repeated_identical_action_refusals`
- decisions: 4; tools: enumerate_strokes > propose_section > inspect_source > assign_station
- first blocker (event 22, operation_rejected:select_contours): `guess_requires_operator_confirmation` - guess_requires_operator_confirmation
  - model (x3): Selection is refused for model choice; assign the s03 best candidate as its station line with the label read from the panel.
- valid draft + STEP; requests 9; list cost $0.0088

## shipd-1-00679-L0
- end: status `draft_not_verified`, reason `repeated_identical_action_refusals`
- decisions: 7; tools: propose_section > build_draft > propose_section > build_draft > render_candidate > propose_section x2
- first blocker (event 17, model_output_rejected:None): `typed_contract_rejected` - typed_contract_rejected
  - model (x3): The s09 traced stroke visibly follows the wrong curve; a neighbour blend gives a plausible stern section instead.
- valid draft + STEP; requests 11; list cost $0.0097
- score (dev truth): wrong; RMS 10.89% of half-beam; volume -1.3%

## shipd-1-00683-L2
- end: status `draft_not_verified`, reason `best_draft_after_non_improving_edits`
- decisions: 10; tools: inspect_source x3 > propose_section x2 > render_candidate > propose_section x4
- first blocker (event 22, operation_rejected:select_contours): `guess_requires_operator_confirmation` - guess_requires_operator_confirmation
  - model (x3): Author s09 from the left-panel V curve since no contour can be assigned to it.
- valid draft + STEP; requests 12; list cost $0.0127

## Across cases
- termination: repeated_identical_action_refusals x2, open_guesses_block_review x1, best_draft_after_non_improving_edits x1
- first blockers: operation_rejected:guess_requires_operator_confirmation x2, model_output_rejected:investigation_argument_bounds x1, model_output_rejected:typed_contract_rejected x1
- tool totals: propose_section x14, inspect_source x9, render_candidate x5, build_draft x3, finish x1, enumerate_strokes x1, assign_station x1
- requests 48; list cost $0.0564
- correct (dev truth, frozen gate): 0/4 cases (2 drafts scored)
- dominant failure: 4/4 valid drafts; 0/4 failed; most common end `repeated_identical_action_refusals` (2/4); most common first blocker `operation_rejected:guess_requires_operator_confirmation` (2/4)
