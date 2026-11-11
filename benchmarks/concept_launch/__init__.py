"""Concept preview: a made-up 24 m survey launch, built in 3D first, with drawings made from it.

This package works backwards. ``model.py`` defines the vessel (a faired hull from an analytic
offset function, decks, deckhouse, wheelhouse, tanks, bulkheads, web frames and appendages) and
builds it in CadQuery. ``sheets.py`` draws a general arrangement, a lines plan and a tank
arrangement from that model and records the exact pixel region of every part, tank and section.
``run_folder.py`` writes the result as a desktop-app run folder, so the app (and the static web
demo) can show the model and the drawings side by side.

Honesty (hard rule): the vessel and its drawings are made up for a demo. Every sheet, the run
name and the run metadata say so (``CONCEPT_LABEL``), the run records this generator as its
maker, and ``engineering_approved`` is always false. Nothing here was read by MarinaFrame's
drawing readers.

Usage::

    PYTHONPATH=src:. python -m benchmarks.concept_launch --out work/web-demo-runs/concept-survey-launch
"""

CONCEPT_LABEL = ("Concept preview - example vessel and drawings made for this demo. Shows how "
                 "MarinaFrame presents a finished model; not a reading of real drawings.")
SHEET_LABEL = "CONCEPT PREVIEW - EXAMPLE DRAWINGS GENERATED FOR THIS DEMO, NOT A REAL VESSEL"
GENERATOR = "benchmarks/concept_launch (synthetic concept-preview generator)"
