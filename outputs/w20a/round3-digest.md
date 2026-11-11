# Round digest (6 cases)

## dtmb5415-L0
- end: status `paused`, reason `requested_step_boundary`
- decisions: 7; tools: describe_views > propose_sheet_setup x6
- first blocker: none found
  - model: Confirm station 5 calibration matches stations 1-4 (50.44 px/m, 2 m grid) before tracing all nine sections.
  - model (x2): Confirm station 6 calibration matches stations 1-5 (50.44 px/m, 2 m grid) before tracing all nine sections.
- no draft; requests 7; list cost $0.0168

## shipd-1-00683-L2
- end: status `paused`, reason `phase1_description_complete`
- decisions: 4; tools: describe_views > propose_sheet_setup x2 > describe_vessel
- first blocker: none found
  - model: Confirm fore-half datums (centreline 568, baseline 813, 2 m grid) so s01-s04 map before proposing sections.
  - model (x2): Record principal dimensions, station/waterline grid and form before authoring sections; beam measured from ink, LOA/draft inferred.
- no draft; requests 4; list cost $0.0064

## shipd-1-00045-L2
- end: status `paused`, reason `phase1_description_complete`
- decisions: 3; tools: describe_views > propose_sheet_setup > describe_vessel
- first blocker (event 8, model_output_rejected:None): `operation_contract` - operation_contract
  - model: Confirm the body-plan scale and datums from the nine-panel grid before tracing sections.
  - model (x2): Record principal dimensions, nine station identities and form from the body plan before tracing sections; beam measured from ink, length/draft inferred and flagged.
- no draft; requests 3; list cost $0.0141

## shipd-1-00679-L0
- end: status `paused`, reason `requested_step_boundary`
- decisions: 3; tools: describe_views > propose_sheet_setup x2
- first blocker (event 23, model_output_rejected:None): `operation_contract` - operation_contract
  - model: Establish left body-plan scale/datum from declared calibration and visible 2 m grid before tracing stations.
  - model (x2): Establish right body-panel datum so stations 6 and 5 can be traced against the same declared calibration as the left panel.
- no draft; requests 3; list cost $0.0104

## dtmb5415-3v-L0
- end: status `paused`, reason `requested_step_boundary`
- decisions: 5; tools: describe_views > propose_sheet_setup x3 > describe_vessel
- first blocker (event 30, worker_result:describe_vessel): `invalid_tool_arguments` - Investigation arguments are outside their bounds or name unknown sections.
  - model: Record principal dimensions from title block and station/waterline grid before CAD; body plan shows 9 stations with U/V sections.
  - model: Record title-block principal dimensions and the measured station/waterline grid before CAD; body plan shows nine nested U/V sections.
  - model: Record title-block dimensions and measured station/waterline grid; body plan shows 9 nested U/V sections with a skeg, so form is round-bilge displacement.
- no draft; requests 7; list cost $0.0130

## shipd-1-00679-3v-L0
- end: status `paused`, reason `requested_step_boundary`
- decisions: 6; tools: describe_views > propose_sheet_setup x3 > describe_vessel x2
- first blocker (event 28, model_output_rejected:None): `typed_contract_rejected` - typed_contract_rejected
  - model: Record principal dimensions from title block, station/waterline/buttock identities and form from the three views before CAD. Station x values are ai_inferred because declared 10-90 m conflicts with...
  - model (x2): Record title-block principals, station/waterline/buttock identities and form; station x remapped to LOA 23.21 m because declared 10-90 m conflicts with the sheet.
- no draft; requests 6; list cost $0.0137

## Across cases
- termination: requested_step_boundary x4, phase1_description_complete x2
- first blockers: none x2, model_output_rejected:operation_contract x2, worker_result:invalid_tool_arguments x1, model_output_rejected:typed_contract_rejected x1
- tool totals: propose_sheet_setup x17, describe_views x6, describe_vessel x5
- requests 30; list cost $0.0744
- dominant failure: 0/6 valid drafts; 6/6 failed; most common end `requested_step_boundary` (4/6); most common first blocker `none` (2/6)
