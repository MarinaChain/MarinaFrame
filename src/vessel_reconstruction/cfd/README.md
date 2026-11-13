# Separate-program resistance prototype

This module does not contain or link solver code. It writes the OpenCFD
`simpleFoam` dialect. The generated case has not been exercised by OpenFOAM.
It is a **double-body, fixed-attitude prototype**, not a total-resistance model.
It cannot pass the public-hull physical gates yet.

## Input and reference frame

Supply closed, outward-oriented triangles in metres. Flow is positive x,
z is up. For a double body, reflect the submerged hull across its design
waterplane (z=0), reverse reflected face winding, weld coincident vertices,
and remove internal waterplane caps. The supplied mesh must already be closed.
The module rejects open or inconsistently oriented triangulations; it does not
repair CAD gaps or detect self-intersections. KCS/KVLCC2 CAD preparation is pending.

`length_m` and `wetted_area_m2` refer to the original real hull at model scale.
The default force multiplier is 0.5 for the reflected double body. This is not
port/starboard symmetry: do not apply a second factor of two. The two-domain
interaction, wall resolution and wave omission still need physical assessment.

## Local use

Use a new case directory under the main checkout's ignored `work/cfd/`.
Use an environment with the external runtime configured. The worker uses the
existing credential-free environment allowlist. Solver-specific environment
variables and shell initialization are not inherited. Where needed, use a
trusted, locally configured launcher as the executable. Never source customer
or model-produced shell code. No arbitrary shell command string is evaluated.

```python
from pathlib import Path
from vessel_reconstruction.cfd import CaseInput, SolverRun, write_case, read_forces

inputs = CaseInput(length_m=7.2786, speed_m_s=1.922,
                   wetted_area_m2=9.4379,
                   sources=('public geometry and scale citation required',))
case = Path('/absolute/main-checkout/work/cfd/unique-attempt')
# triangles must be a complete, reflected, oriented tessellation.
write_case(case, inputs, triangles)

# Run one step at a time; each step gets its own exclusive log and receipt.
# Rename solver.log/run-receipt.json to blockMesh.log/blockMesh-receipt.json
# after inspecting each completed step, then proceed with the next step.
run = SolverRun.start(['blockMesh'], case)
receipt = run.wait()
# Next: snappyHexMesh -overwrite, checkMesh, then simpleFoam.
# A nonzero exit code blocks the next step. Inspect checkMesh quality too.
# Reading the raw force file alone is not evidence of solver completion.
result = read_forces(case / 'postProcessing/resistance/0/forces.dat', inputs,
                     start_time=500, run_receipt=case / 'run-receipt.json')
fragment = result.to_record_fragment()
```

`start()` returns immediately; `progress()` reports the last solver time;
`cancel()` kills the serial process (its group on POSIX); `wait()` has no wall
limit. The runner is for trusted native code, not a security sandbox. It runs
one core only; remote transport and MPI are not implemented. A controller exit
can leave the solver running: keep the controlling job alive and cancel explicitly.

Logs and receipts must be preserved for every attempt. Cells are parsed when a
log prints `cells: N`; otherwise the receipt reports null, not a guessed value.
A `completed` receipt means process exit zero, not physical convergence. Apply
the frozen force-window and mesh gates separately. Allocation accounting is
wall seconds / 3600 for this serial runner, not measured CPU-hours.

## Remaining physical work

Native runtime installation; public CAD tessellation/provenance; full mesh
quality and wall-y+ assessment; free-surface and attitude solver setup; Tokyo
submission scatter extraction; KCS convergence and speed series; KVLCC2 error;
measured host sizing. `engineering_approved` always remains false.
