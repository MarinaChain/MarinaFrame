# Round digest (4 cases)

## dtmb5415-L0
- end: status `draft_not_verified`, reason `open_guesses_block_review`
- decisions: 11; tools: inspect_source > select_contours > build_draft > render_candidate > propose_section x2 > inspect_source > propose_section > build_draft > render_candidate > finish
- first blocker (event 26, model_output_rejected:None): `operation_contract` - operation_contract
  - model: Draft rebuilt with corrected s01/s09. Render body view to visually inspect the hull before finishing.
  - model (x2): Draft is valid, closed-shell, and the body render matches the monotone U sections with the S-shaped stern at s09. Remaining open guesses (s01, s09 authored) are disclosed for human review.
- valid draft + STEP; requests 9; list cost $0.0110

## dtmb5415-L1
- end: status `no_progress`, reason `repeated_identical_action_refusals`
- decisions: 44; tools: inspect_source > enumerate_strokes > assign_station > enumerate_strokes > assign_station > enumerate_strokes > assign_station > enumerate_strokes > assign_station > enumerate_strokes > assign_station > enumerate_strokes > ... (+22 more runs)
- first blocker (event 11, model_output_rejected:None): `notes_limit` - notes_limit
  - model: All nine sections inspected and assigned; select the best per-section contour so the draft can build.
  - model (x2): All nine sections are inspected and assigned; the draft is blocked only because no contour is selected. Build the draft now to see whether the authored s01 plus assigned traces produce a valid hull.
- build attempted 7x, none valid; requests 52; list cost $0.0977

## dtmb5415-L2
- end: status `draft_not_verified`, reason `open_guesses_block_review`
- decisions: 35; tools: inspect_source > propose_section x9 > build_draft > render_candidate > propose_section x8 > build_draft > render_candidate x2 > propose_section x3 > build_draft > render_candidate > propose_section x4 > build_draft > ... (+2 more runs)
- first blocker (event 114, repeat:build_draft): `repeated_identical_action` - same tool+arguments as event 56
  - model: Draft valid with all nine sections; render oblique to visually confirm the hull before finishing.
  - model (x2): Best complete draft built and rendered; all sections inspected and authored to traced hollows.
- valid draft + STEP; requests 34; list cost $0.0516

## dtmb5415-L3
- end: status `no_progress`, reason `repeated_identical_action_refusals`
- decisions: 40; tools: inspect_source > enumerate_strokes x3 > assign_station > enumerate_strokes x2 > assign_station x2 > enumerate_strokes > assign_station > enumerate_strokes > assign_station > enumerate_strokes > assign_station > enumerate_strokes > ... (+5 more runs)
- first blocker (event 26, operation_rejected:select_contours): `model_traced_candidate_requires_person` - model_traced_candidate_requires_person
  - model (x3): Repeated re-authoring of s08 did not change the knot count; build_draft now to see the actual CAD and its warnings before further revision.
- build attempted 2x, none valid; requests 47; list cost $0.1113

## Across cases
- termination: open_guesses_block_review x2, repeated_identical_action_refusals x2
- first blockers: model_output_rejected:operation_contract x1, model_output_rejected:notes_limit x1, repeat:repeated_identical_action x1, operation_rejected:model_traced_candidate_requires_person x1
- tool totals: propose_section x61, enumerate_strokes x18, assign_station x17, build_draft x15, inspect_source x8, render_candidate x7, finish x2, select_contours x1
- requests 142; list cost $0.2716
- dominant failure: 4/4 failed; most common end `open_guesses_block_review` (2/4); most common first blocker `model_output_rejected:operation_contract` (1/4)
