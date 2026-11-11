"""GA to estimated 3D arrangement (stretch demo; docs/plans/2026-11-11-ga-arrangement-demo.md).

From one general-arrangement (GA) image, with no lines plan:

1. ``reader.py`` asks Claude (Claude Code CLI on the subscription) to read positions on the GA.
   Code draws a pixel grid labelled in sheet pixels on every image, so the model names grid
   positions; it never sees or returns ship metres.
2. ``vessel_reconstruction.ga_arrangement`` checks the reading (scale fit, gates), snaps levels
   and bulkheads to drawn ink, converts pixels to ship metres and builds the estimated hull
   table in the prior-form family of ``form_fit``.
3. ``model.py`` builds the hull and the compartments in CadQuery; ``run_folder.py`` writes a
   desktop-app run folder that the web demo exporter also reads.

Honesty (hard rule): every page of the run carries ``ESTIMATE_LABEL``; engineering_approved is
always false; ships are named by case ID only. Images, readings and per-ship values stay under
work/ (git-ignored).

Usage::

    PYTHONPATH=src:. python -m benchmarks.ga_arrangement --case GA-121 \\
        --image work/ga-internal-23/inputs/GA-121_GA.png --out work/ga-arrangement-demo
"""

ESTIMATE_LABEL = ("Estimated 3D arrangement from a single GA drawing. The hull shape is estimated "
                  "(no lines plan); compartments are read from the GA. Not a CAD model; not for construction.")
GENERATOR = "benchmarks/ga_arrangement (GA reading, estimated hull and compartments)"
POLICY = "ga_estimate"
