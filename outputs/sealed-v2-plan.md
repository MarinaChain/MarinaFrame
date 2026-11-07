# Hull-disjoint (v2) generation plan

**Goal:** Freeze 288 unscored drawings: 36 Ship-D hulls, both layouts, four degradation levels.

**Approved boundary:** This is hull-disjoint (v2), not family-disjoint. New clusters can share broad families with the frozen splits. No named family remains unused.

## Steps and checks

1. Add a separate generation command and manifest directory. Standardise all 30,000 constrained-random Ship-D vectors; partition with k-means++, 256 clusters, seed 20261108. Exclude every cluster containing any previously rendered hull recorded in frozen case manifests. Also exclude recorded skipped hulls conservatively. Select nine remaining clusters in seeded order, four feasible hulls per cluster. Record full candidate order, skips, parameters, source and generator hashes.
2. Test selection/exclusion, paired layout balance, disk stop, frozen-file verification and future report naming with synthetic fixtures only.
3. Commit generator code before generation. Generate with the existing hull loader, truth builder and renderer into ignored `work/factory-sealed-v2/`. Check free space before each hull and each render; stop below 15 GB. Do not invoke runner or scorer.
4. Freeze `benchmarks/factory/manifests/sealed-v2/`: hulls, cases, selection and split manifest. Hash every drawing, spec, parameter and truth file, source and generator file. Verify hashes, spec contracts and truth completeness only. Open drawings at all levels using Read.
5. Add split README and benchmark documentation with counts, seed, manifest hash and frozen-checkpoint-only rule. Run `make test-quick` with the requested Python environment, then `cargo clean` if Rust was built. Commit manifests and documentation. Do not push.

## Resume point

Start at step 1. Existing frozen manifests must remain unchanged. No reader output or sealed score may be inspected. Final report: files changed, commits, counts, sizes, seed, manifest hash and checks (under 250 words).
