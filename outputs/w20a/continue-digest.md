# Round digest (6 cases)

## dtmb5415-L0
- end: status `paused`, reason `phase1_description_complete`
- decisions: 2; tools: describe_views > describe_vessel
- first blocker: none found
  - model: Nine same-scale body-plan panels in a 3x3 grid, each with a vertical centreline and horizontal baseline; one body family with per-panel centreline/baseline and shared calibration.
  - model (x2): Body plan only: nine half-sections, no title block. Record declared z_max as depth, infer station x from panel order, waterlines from 2 m grid labels; leave loa/lpp/draft null.
- no draft; requests 2; list cost $0.0051

## shipd-1-00045-L2
- end: status `paused`, reason `phase1_description_complete`
- decisions: 2; tools: describe_views > describe_vessel
- first blocker: none found
  - model: Nine same-scale body-plan panels in a 3x3 grid, each with its own centreline and baseline; one family with shared calibration.
  - model (x2): Body plan has nine labelled station panels; record identity and grid-derived depth before section work.
- no draft; requests 2; list cost $0.0054

## shipd-1-00679-L0
- end: status `paused`, reason `phase1_description_complete`
- decisions: 2; tools: describe_views > describe_vessel
- first blocker: none found
  - model: Whole sheet read: two same-scale body-section panels plus title text; naming them lets me trace stations next.
  - model (x2): Read the drawing and record the result.
- no draft; requests 2; list cost $0.0028

## shipd-1-00683-L2
- end: status `paused`, reason `phase1_description_complete`
- decisions: 2; tools: describe_views > describe_vessel
- first blocker: none found
  - model: Survey shows two same-scale body panels (left x=10-40m, right x=50-90m) with shared 47.58 px/m calibration and 2m grid; naming them as one body family plus title block and offsets table.
  - model (x2): Read the drawing and record the result.
- no draft; requests 2; list cost $0.0034

## dtmb5415-3v-L0
- end: status `paused`, reason `phase1_description_complete`
- decisions: 2; tools: describe_views > describe_vessel
- first blocker: none found
  - model: Survey shows profile, half-breadth plan, body plan and title block; naming them with source-pixel bounds lets me calibrate and trace sections next.
  - model (x2): Title block gives LOA 30, beam 13.41, depth 12.53, draft 2.5; profile/plan/body plan show 9 stations and WL2-WL12. Recording these with explicit source labels and calibration warnings before any CAD.
- no draft; requests 2; list cost $0.0037

## shipd-1-00679-3v-L0
- end: status `paused`, reason `phase1_description_complete`
- decisions: 2; tools: describe_views > describe_vessel
- first blocker: none found
  - model: Survey shows profile, half-breadth plan, body plan and title block; naming them with sheet-pixel bounds and shared calibration lets me trace sections next.
  - model (x2): Read the drawing and record the result.
- no draft; requests 2; list cost $0.0037

## Across cases
- termination: phase1_description_complete x6
- first blockers: none x6
- tool totals: describe_views x6, describe_vessel x6
- requests 12; list cost $0.0241
- dominant failure: 0/6 valid drafts; 6/6 failed; most common end `phase1_description_complete` (6/6); most common first blocker `none` (6/6)
- **early stop:** first 6 cases fail the same way (`phase1_description_complete`): stop the round and fix this first
