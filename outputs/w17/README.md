# W17 / W17b compact results

No drawings, truth arrays or credentials are included here.

- `baseline.json`: 24-case W17 baseline at a5fd140.
- `after-stopped.json`: four W17 after-change attempts stopped deliberately by the PM. Do not restart.
- `w17b-round1.json`: four DTMB cases, 1 draft / 0 gate-correct, 83 requests, USD 0.12763727 list cost.
- `w17b-round2.json`: four DTMB cases, 3 drafts / 0 gate-correct, 80 requests, USD 0.11823454 list cost.
- `w17b-dev24.json`: one permitted full development batch completed: 10 drafts, 2 gate-correct, 8 labelled wrong drafts, 14 no_progress, zero silent wrong; 560 requests, USD 0.75805702 list cost.

Wrong exports in both rounds are labelled unverified drafts. Silent wrong builds: zero. Frozen gate: RMS <=2% maximum truth half-breadth and in-range volume error <=5%. Raw runs and frozen runtimes: main checkout `work/w17/`. See `docs/LLM_INVESTIGATOR.md` for causes, test results and the next blocker.
