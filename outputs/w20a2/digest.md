# Round digest (6 cases)

## dtmb5415-L0
- end: status `paused`, reason `phase1_description_complete`
- decisions: 2; tools: describe_views > describe_vessel
- first blocker: none found
  - model: Survey the nine same-scale body-plan panels as one mirrored family with shared calibration before tracing.
  - model (x2): Read the drawing and record the result.
- no draft; requests 2; list cost $0.0051

## shipd-1-00045-L2
- end: status `paused`, reason `phase1_description_complete`
- decisions: 3; tools: describe_views > read_region > describe_vessel
- first blocker: none found
  - model: Title crop is unreadable at thumbnail scale; need exact printed LOA/LWL/BEAM/DEPTH/DRAFT before describing the vessel.
  - model (x2): Title crop is illegible; record declared station grid and spec depth, leaving undeclared principal dimensions null rather than inventing them.
- no draft; requests 3; list cost $0.0078

## shipd-1-00679-L0
- end: status `paused`, reason `phase1_description_complete`
- decisions: 3; tools: describe_views > read_region > describe_vessel
- first blocker: none found
  - model: Offsets table region may hold station offsets/waterline data; reading it before describing vessel and tracing sections.
  - model (x2): Title crop is mirrored 'BODY PLAN' with 'WL 14' and no dimension text; record vessel with spec depth and null undeclared dims before tracing sections.
- no draft; requests 3; list cost $0.0045

## shipd-1-00683-L2
- end: status `paused`, reason `phase1_description_complete`
- decisions: 4; tools: describe_views > read_region x2 > describe_vessel
- first blocker: none found
  - model: Title crop was blank; the lower strip likely holds the offsets table with station/waterline dimensions needed before describe_vessel.
  - model (x2): Title block and offsets strip are blank; record stations and declared depth, mark other principal dims as not on sheet before tracing sections.
- no draft; requests 4; list cost $0.0062

## dtmb5415-3v-L0
- end: status `paused`, reason `phase1_description_complete`
- decisions: 2; tools: describe_views > describe_vessel
- first blocker: none found
  - model: Survey shows profile (top-left), half-breadth plan (bottom-left) and body plan (right) with title block; one same-scale family with shared 19 px/m setup.
  - model (x2): Read the drawing and record the result.
- no draft; requests 2; list cost $0.0037

## shipd-1-00679-3v-L0
- end: status `paused`, reason `phase1_description_complete`
- decisions: 3; tools: describe_views > read_region > describe_vessel
- first blocker: none found
  - model: Title crop already legible; confirm exact dimension text before describe_vessel.
  - model (x2): Read the drawing and record the result.
- no draft; requests 3; list cost $0.0055

## Across cases
- termination: phase1_description_complete x6
- first blockers: none x6
- tool totals: describe_views x6, describe_vessel x6, read_region x5
- requests 17; list cost $0.0329
- dominant failure: 0/6 valid drafts; 6/6 failed; most common end `phase1_description_complete` (6/6); most common first blocker `none` (6/6)
- **early stop:** first 6 cases fail the same way (`phase1_description_complete`): stop the round and fix this first
