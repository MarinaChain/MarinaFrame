# Round digest (4 cases)

## dtmb5415-L0
- end: status `draft_not_verified`, reason `cancelled_after_worker_receipt`
- decisions: 211; tools: inspect_source > select_contours > build_draft > render_candidate > propose_section x32 > build_draft > render_candidate > propose_section x20 > build_draft > render_candidate > propose_section x26 > build_draft > ... (+19 more runs)
- first blocker (event 100, model_output_rejected:None): `investigation_argument_bounds` - investigation_argument_bounds
  - model: Selection of authored lines needs station assignment; build the draft first to inspect CAD, then assign s01/s09.
  - model (x2): Draft is valid; render the oblique view to inspect the actual CAD before deciding on further section revisions.
- valid draft + STEP; requests 210; list cost $0.5300

## dtmb5415-L1
- end: status `draft_not_verified`, reason `repeated_refused_model_output`
- decisions: 86; tools: inspect_source > enumerate_strokes > trace_corridor > propose_section > enumerate_strokes > propose_section > enumerate_strokes > assign_station > propose_section x10 > enumerate_strokes > propose_section x7 > build_draft > ... (+11 more runs)
- first blocker (event 18, worker_result:trace_corridor): `insufficient_ink_support` - The ink in the corridor is broken or fragmented; no continuous line is supported.
  - model: s04 authored section is set and inspected; stop re-proposing. Build the draft now to inspect actual CAD, then fill s06-s09.
  - model (x2): Refine s04 to match ink: finer V entry, fuller topsides.
- valid draft + STEP; requests 91; list cost $0.2620

## dtmb5415-L2
- end: status `no_progress`, reason `repeated_refused_model_output`
- decisions: 11; tools: inspect_source > enumerate_strokes > assign_station > enumerate_strokes > assign_station > enumerate_strokes > assign_station > enumerate_strokes > assign_station > enumerate_strokes > assign_station
- first blocker (event 51, model_output_rejected:None): `notes_limit` - notes_limit
  - model: Enumerating s05's panel to pick its hull curve from tagged strokes.
  - model (x2): Tag 5 is the hull curve; tag 1 continues it to the keel. Tags 2-4 are grid lines. Assigning tag 5 to s05.
- no draft; requests 10; list cost $0.0246

## dtmb5415-L3
- end: status `draft_not_verified`, reason `open_guesses_block_review`
- decisions: 23; tools: inspect_source > enumerate_strokes > trace_corridor > assign_station > propose_section > enumerate_strokes > assign_station > enumerate_strokes > assign_station > enumerate_strokes > assign_station > build_draft > ... (+6 more runs)
- first blocker (event 18, worker_result:trace_corridor): `insufficient_ink_support` - The ink in the corridor is broken or fragmented; no continuous line is supported.
  - model: s06 corrected to the visible grey hull curve; rebuilding the draft incorporates the correction so I can render and inspect the improved hull.
  - model (x2): The draft is valid and complete; remaining warnings are benign centreline clamps and the authored sections are my best inference. Submitting for human review rather than continuing to churn.
- valid draft + STEP; requests 24; list cost $0.0358

## Across cases
- termination: repeated_refused_model_output x2, cancelled_after_worker_receipt x1, open_guesses_block_review x1
- first blockers: worker_result:insufficient_ink_support x2, model_output_rejected:investigation_argument_bounds x1, model_output_rejected:notes_limit x1
- tool totals: propose_section x269, build_draft x17, enumerate_strokes x13, render_candidate x10, assign_station x10, inspect_source x8, trace_corridor x2, select_contours x1
- requests 335; list cost $0.8524
- dominant failure: 4/4 failed; most common end `repeated_refused_model_output` (2/4); most common first blocker `worker_result:insufficient_ink_support` (2/4)
