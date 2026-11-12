# Offline performance evaluator — input contract, draft

The PM's independent evaluator owns the blind measurements and selection. The
implementation lane uses only already exposed KCS/JBC measurements. Do not send
blind measurements back to the implementation lane before the frozen score.

## Command

After checking out the immutable tag recorded in the results report, from that
checkout with its dependencies installed:

```bash
PYTHONPATH=src /path/to/python -m vessel_reconstruction.performance_compare \
  --input /absolute/path/to/evaluator-owned-cases.json \
  --output /absolute/path/to/new-score.json \
  --markdown /absolute/path/to/new-score.md
```

The outputs must not exist. The tool performs no downloads, ship discovery,
fitting or automatic scale conversion. It records the input SHA-256, all case
inputs, component resistance values, method/range warnings, source labels and
signed errors. The evaluator records the git tag and commit beside the output.
`engineering_approved` is always false. Out-of-range estimates remain marked;
absence of a physical propeller root is not silently replaced by an efficiency.

## JSON version 1

Top level is `{"cases": [case, ...]}`. One case has these required fields:

- `schema_version`: 1.
- `ship`: evaluator-chosen label; no built-in ship lookup.
- `scale`: `model` or `ship`. All dimensions are **metres**, forces newtons,
  powers kW, density kg/m³, kinematic viscosity m²/s, speed m/s. Model scale
  disables the ship correlation allowance and is marked as a regression
  extrapolation. No Froude/Reynolds rescaling occurs automatically.
- `method`: `holtrop_mennen_1982` or `holtrop_1984`; no mixed coefficients.
- `particulars_source`: source file/page, geometry SHA and measurement basis.
- `hull`: fields of `HoltropHull` in `src/vessel_reconstruction/holtrop.py`.
  Required: `lwl_m`, `beam_m`, `draft_m`, `volume_m3`, `cm`, `cwp`,
  `lcb_percent_lwl_forward`. **LCB is percent LWL, positive forward of the
  mid-LWL reference used by the method**, not a 0–1 coordinate or percent Lpp.
  Set it from explicit fore/aft reference points. Optional bulb area/centroid,
  transom area, wetted area, appendages, stern and draft inputs must identify
  their geometric basis. Omitting bulb/transom terms means zero, not measured.
- `water`: `density_kg_m3`, `kinematic_viscosity_m2_s`.
- `measurements`: nonempty array. Each contains `speed_ms`, dimensionless `ct`
  (**not CT×1000**), `reference_surface_m2`, and nonempty `source` with
  file/table/cell. Reference surface is the experiment's coefficient denominator,
  not an estimated replacement area.

Optional fields:

- `notes`: explicit condition/geometry approximations; copied with inputs.
- `propeller`: `diameter_m`, integer `blade_count`, `pitch_diameter_ratio`,
  `expanded_area_ratio`, `shaft_efficiency`. This uses a Wageningen B-series
  surrogate, not an exact arbitrary propeller. Interaction uses Holtrop
  regressions. All physical roots in the supported advance range are returned;
  multiple roots require an independent operating-point decision.
- `sfoc_g_per_kwh`: explicit engine brake-specific fuel use. No default. Output
  fuel is constant-load main-engine tonnes/day, not auxiliary or voyage fuel.

A minimal synthetic case is provided by `synthetic_case()` in
`tests/test_performance_compare.py`. Do not use that case as ship evidence.

## Metrics and limits

`CT_est = R_est / (0.5 rho U² S_est)`.
`R_measured = CT_measured × 0.5 rho U² S_reference`.
`PE = R U / 1000` in kW.
Both errors are `100 × (estimate − measured) / measured`. They differ if the
estimated and published surface areas differ. Report each speed; never replace
per-speed errors with a single favourable point. Mean absolute errors are
additional summaries, not an acceptance threshold.

A published author example checks formula transcription, not prediction
accuracy. B-series base Reynolds convention and geometry limits are reported by
the propeller module. No low-Re correction, cavitation, sea margin, wind model,
engine map or class sign-off is implied. Report all warnings with the score.
