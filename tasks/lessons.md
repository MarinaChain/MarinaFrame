# Project lessons

### Repartitioned holdouts are hull-disjoint, not family-disjoint
- **Date:** 2026-11-08
- **Trigger:** All original Ship-D clusters were already represented; a new seed cannot establish independence from those broad families.
- **Rule:** Name the approved replacement split “hull-disjoint (v2)” in manifests, README and scorer output. State that clusters can share broad families with frozen splits. Exclude every new cluster containing any previously rendered hull. Keep the truth sealed; run no reader or scorer during generation or development. Score only at frozen checkpoints.
- **Why:** New partition labels do not prove new hull families.
