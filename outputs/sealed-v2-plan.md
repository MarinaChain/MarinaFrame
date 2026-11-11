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

Steps 1–4 complete. Generator frozen at `ad2e2b6`; generated 288 drawings and 36 complete truth tables. Selected clusters: 122, 88, 31, 176, 120, 221, 217, 182, 212. Manifest hash: `856a37fad69439cd9fc83a75382699d5988323c0aa68ed9b1eaf66fcfdef81d3`. Read samples checked all four levels. No pipeline/scorer or reader-output inspection. Original frozen manifests unchanged. First quick run passed (617 Python tests, Rust checks, secret scan). Step 5 checks complete: final quick checks passed (617 Python tests; Rust fmt/clippy/tests; secret scan). `cargo clean` removed 2.8 GiB; 39 GiB remain. Ready for manifest/documentation commit and final report under 250 words.
