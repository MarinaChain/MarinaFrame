"""PDF review report of a draft build.

Page 1 is the summary: vessel, revision, particulars, hydrostatics, the source
label and ink fit of every section, open guesses and warnings. Long section
lists continue on the next pages. Then one page per station overlay image
(built cuts drawn on the source drawing). Every page carries the draft footer.

The PDF is drawn with matplotlib (a locked dependency; see ``fonts.py``), with
no creation date in the metadata, so the same inputs give the same bytes.
Wording follows docs/design/2026-11-08-d-review-workflow.md section 5:
measurements, not adjectives; nothing implies approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import textwrap

import numpy as np
from PIL import Image

from .hydrostatics import Hydrostatics
from .source import DraftBuild
from ..booklet_check import BookletCheck

FOOTER = "Draft — not for construction; engineering sign-off happens outside MarinaFrame"
# A4 portrait, inches.
PAGE_SIZE_IN = (8.27, 11.69)
LEFT, RIGHT, TOP, BOTTOM = 0.07, 0.93, 0.95, 0.06
LINE_HEIGHT = 0.0145  # Figure fraction per text line at BODY_SIZE.
BODY_SIZE, HEADING_SIZE, TITLE_SIZE = 7.5, 10, 14
WRAP_COLUMNS = 132
# Most warnings and guesses listed on the summary page; the rest are counted.
MAX_LISTED_ITEMS = 12
# Longest side of an overlay image placed on a page, in pixels.
MAX_IMAGE_SIDE_PX = 1800
MONO = "DejaVu Sans Mono"

# Plain words for the internal source labels (review workflow section 5).
LABEL_TEXT = {"traced": "From ink", "repaired": "From ink, repaired", "interpolated": "Filled between stations",
              "ai_inferred": "AI drawn (no ink)", "ai_corrected": "AI changed the ink", "human_edited": "Edited",
              "omitted": "Not modelled"}


@dataclass
class ReportFacts:
    """Every value the report prints, gathered before drawing."""

    build: DraftBuild
    hydrostatics: Hydrostatics | None
    hydrostatics_error: str | None
    generated_by: str
    capacity_rows: list[dict] | None = None  # capacity plan (tanks.capacity_plan), when tanks are given
    accuracy_facts: dict | None = None  # run facts for the accuracy summary (accuracy_summary.facts_from_build)
    booklet_check: BookletCheck | None = None


def label_text(label: str) -> str:
    return LABEL_TEXT.get(label, label)


class PageWriter:
    """Writes lines top to bottom on A4 figures and starts a new page when one is full."""

    def __init__(self, pdf, title: str):
        self.pdf, self.title, self.figure, self.y = pdf, title, None, TOP
        self.page_number = 0

    def new_page(self):
        from matplotlib.figure import Figure

        self.finish_page()
        self.figure = Figure(figsize=PAGE_SIZE_IN)
        self.page_number += 1
        self.y = TOP
        return self.figure

    def finish_page(self):
        if self.figure is None:
            return
        footer = f"{FOOTER}    |    {self.title}    |    page {self.page_number}"
        self.figure.text(0.5, BOTTOM - 0.03, footer, ha="center", va="bottom", fontsize=6.5, color="#7a2e12")
        self.pdf.savefig(self.figure)
        self.figure = None

    def room(self, lines: int = 1) -> None:
        if self.figure is None or self.y - lines * LINE_HEIGHT < BOTTOM:
            self.new_page()

    def line(self, text: str, *, size=BODY_SIZE, weight="normal", family=None, colour="#1D2430", gap=1.0):
        self.room()
        self.figure.text(LEFT, self.y, text, fontsize=size, weight=weight, family=family, color=colour,
                         va="top", ha="left")
        self.y -= LINE_HEIGHT * gap * size / BODY_SIZE

    def heading(self, text: str):
        self.room(3)
        self.y -= LINE_HEIGHT * 0.5
        self.line(text, size=HEADING_SIZE, weight="bold", gap=1.1)

    def wrapped(self, text: str, indent: str = ""):
        for index, part in enumerate(textwrap.wrap(text, WRAP_COLUMNS - len(indent)) or [""]):
            self.line((indent if index == 0 else " " * len(indent)) + part)

    def table(self, header: list[str], rows: list[list[str]], widths: list[int]):
        def format_row(cells):
            return "  ".join(str(c)[:w].ljust(w) for c, w in zip(cells, widths))

        self.line(format_row(header), family=MONO, weight="bold")
        for row in rows:
            if self.figure is None or self.y - LINE_HEIGHT < BOTTOM:
                self.new_page()
                self.line(format_row(header), family=MONO, weight="bold")
            self.line(format_row(row), family=MONO)


def fmt(value, digits: int = 2, unit: str = "") -> str:
    if value is None:
        return "not computed"
    return f"{value:,.{digits}f}{(' ' + unit) if unit else ''}"


def section_rows(build: DraftBuild) -> list[list[str]]:
    scores = {row["section_id"]: row for row in (build.scoreboard or {}).get("scoreboard", [])}
    half_beam = (build.result.get("metrics") or {}).get("beam_m", 0) / 2
    open_ids = {g["section_id"] for g in build.guesses if g.get("status") == "open"}
    rows = []
    for section in build.sections:
        fit = (scores.get(section["id"]) or {}).get("ink_fit")
        if fit:
            max_m, rms_m = fmt(fit["max_m"], 3), fmt(fit["rms_m"], 3)
            percent = fmt(100 * fit["rms_m"] / half_beam, 1) if half_beam > 0 else "-"
            near = fmt(100 * fit.get("near_fraction", 0), 0)
        else:
            max_m = rms_m = percent = near = "not checked"
        label = str(section.get("source_label", "unlabelled"))
        rows.append([section["id"], f"{float(section['x_m']):.3f}", label_text(label), max_m, rms_m, percent, near,
                     "open" if section["id"] in open_ids else ""])
    return rows


def write_summary(writer: PageWriter, facts: ReportFacts) -> None:
    build, result = facts.build, facts.build.result
    metrics = result.get("metrics") or {}
    writer.new_page()
    writer.line("MarinaFrame draft review report", size=TITLE_SIZE, weight="bold", gap=1.6)
    writer.wrapped(f"Vessel {build.vessel}    Revision {build.revision_id}    Run {result.get('run_id', '-')}    "
                f"Build {build.build_dir.name}")
    review = (result.get("review") or {}).get("state", "unreviewed")
    writer.wrapped(f"Status: {result.get('status', '-')} ({(result.get('draft') or {}).get('status', 'not a draft')}); "
                f"review state: {review}. Not approved for construction.")
    writer.wrapped(f"Generated by {facts.generated_by}. Units: metres; x along the length as drawn, z up from "
                "the baseline (z = 0), y to starboard from the centreline.")
    writer.wrapped("This report traces where the geometry came from. It is not a class document; the naval "
                "architect re-runs hydrostatics and stability in approved software.")

    writer.heading("Particulars (built model)")
    writer.wrapped(f"Length {fmt(metrics.get('length_m'))} m    Beam {fmt(metrics.get('beam_m'))} m    "
                f"Depth {fmt(metrics.get('depth_m'))} m    Envelope volume {fmt(metrics.get('volume_m3'), 1)} m3    "
                f"Sections {len(build.sections)}    CAD valid {metrics.get('cad_valid', '-')}")

    writer.heading("Hydrostatics at the design draft")
    h = facts.hydrostatics
    if h is None:
        writer.wrapped(f"Not computed: {facts.hydrostatics_error}")
    else:
        writer.wrapped(f"Waterline z = {fmt(h.draft_m, 3)} m ({h.draft_basis}). Method: {h.method}.")
        writer.wrapped(f"Volume {fmt(h.volume_m3, 1)} m3   Displacement {fmt(h.displacement_t, 1)} t at "
                    f"{h.density_t_per_m3:g} t/m3   LCB {fmt(h.lcb_m)} m   KB {fmt(h.kb_m)} m   "
                    f"Awp {fmt(h.waterplane_area_m2, 1)} m2   LCF {fmt(h.lcf_m)} m")
        writer.wrapped(f"BMt {fmt(h.bmt_m)} m   BMl {fmt(h.bml_m, 1)} m   Lwl {fmt(h.waterline_length_m)} m   "
                    f"B {fmt(h.largest_breadth_below_waterline_m)} m   Wetted surface "
                    f"{fmt(h.wetted_surface_m2, 1, 'm2')}")
        writer.wrapped(f"Cb {fmt(h.cb, 3)}   Cp {fmt(h.cp, 3)}   Cm {fmt(h.cm, 3)}   Cwp {fmt(h.cwp, 3)}   "
                    f"({h.coefficient_basis})")
        for warning in h.warnings:
            writer.wrapped(f"Note: {warning}")

    writer.heading("Sections: source and ink fit")
    writer.wrapped("Ink fit: distance from the built cut to the nearest dark pixel in the section's region of "
                   "the drawing (metres; % of half beam is RMS / (B/2); near = cut points within 2 px of ink). "
                   "'not checked' means no overlay was rendered for this build.")
    writer.table(["Section", "x m", "Source", "Ink max m", "Ink RMS m", "% B/2", "Near %", "Guess"],
                 section_rows(build), [8, 8, 24, 11, 11, 7, 7, 6])

    open_guesses = [g for g in build.guesses if g.get("status") == "open"]
    writer.heading(f"Open guesses ({len(open_guesses)})")
    if not open_guesses:
        writer.wrapped("None.")
    for guess in open_guesses[:MAX_LISTED_ITEMS]:
        writer.wrapped(f"{guess.get('section_id')} at x = {guess.get('x_m')} m, {guess.get('kind')}: "
                       f"{guess.get('reason', '')}", indent="- ")
    if len(open_guesses) > MAX_LISTED_ITEMS:
        writer.wrapped(f"... and {len(open_guesses) - MAX_LISTED_ITEMS} more (see the run record).")

    warnings = [g for g in result.get("gaps", []) if g.get("severity") in ("warning", "error")]
    writer.heading(f"Warnings ({len(warnings)})")
    if not warnings:
        writer.wrapped("None recorded by the build.")
    for gap in warnings[:MAX_LISTED_ITEMS]:
        writer.wrapped(f"{gap.get('section_id') or '-'}: {gap.get('message', gap.get('kind', ''))}", indent="- ")
    if len(warnings) > MAX_LISTED_ITEMS:
        writer.wrapped(f"... and {len(warnings) - MAX_LISTED_ITEMS} more (see result.json gaps).")
    if not build.overlay_images:
        writer.heading("Station overlays")
        writer.wrapped("No station overlay was rendered for this build.")


def write_accuracy_section(writer: PageWriter, facts: dict) -> None:
    """Accuracy and limits: one line per output, then the measured bands behind the lines."""
    from ..accuracy_bands import bands_for
    from ..accuracy_summary import DRAFT_NOTE, SCOPE_NOTE, summarise

    summaries = summarise(facts)
    writer.heading("Accuracy and limits")
    writer.wrapped(SCOPE_NOTE)
    for summary in summaries.values():
        writer.wrapped(summary.line, indent="- ")
    listed = [b for s in summaries.values() if s.present for b in bands_for(s.output)]
    if listed:
        writer.line("")
        writer.line("Measured bands (development: the code was tuned on the case; holdout: read once, protocol fixed first)")
        writer.table(["Band", "Set", "N", "Source"],
                     [[b.id, b.dataset, b.n, f"{b.source} s.{b.section}"] for b in listed], [26, 12, 32, 62])
        for item in listed:
            writer.wrapped(f"{item.id}: {item.caveat}", indent="- ")
    writer.wrapped(DRAFT_NOTE)


def write_capacity_plan(writer: PageWriter, rows: list[dict]) -> None:
    writer.heading("Capacity plan (draft tank model)")
    writer.wrapped("Moulded volumes of the built tank solids; weight at 98 % fill; centre of gravity at 100 %. "
                   "Source of each volume: From ink (traced) or guessed. Sounding tables are in the CSV files.")
    table_rows = []
    for row in rows:
        volume_source = (row.get("source_labels") or {}).get("volume") or ""
        table_rows.append([row["id"], row["content"], row["frames"], fmt(row["volume_100_m3"], 2),
                           fmt(row["volume_98_m3"], 2), fmt(row["weight_98_t"], 2), fmt(row["lcg_m"], 2),
                           fmt(row["tcg_m"], 2), fmt(row["vcg_m"], 2),
                           label_text(volume_source) if row["built"] else "not built"])
    writer.table(["Tank", "Content", "Frames", "V100 m3", "V98 m3", "W98 t", "LCG m", "TCG m", "VCG m", "Volume"],
                 table_rows, [22, 13, 7, 8, 8, 8, 7, 7, 7, 12])


def write_booklet_section(writer: PageWriter, check: BookletCheck) -> None:
    """A short summary; the package CSV retains every draft and quantity."""
    from ..accuracy_summary import booklet_summary_line

    booklet = check.booklet
    writer.heading("Booklet check")
    writer.wrapped("The booklet comparison is secondary evidence only. Integrated quantities "
                   "(displacement, LCB, KMT) can agree while the local hull shape is wrong. "
                   "The primary accuracy number remains the section-shape error at withheld stations. "
                   "A booklet match does not replace that shape check or supply a missing shape-error measurement.")
    writer.wrapped(f"{booklet.title}. {booklet_summary_line(check.summary)}. Counts are quantity cells, not drafts.")
    writer.wrapped(f"Density {booklet.density:g} t/m3; trim {booklet.trim}, trim {booklet.trim_m:g} m, "
                   f"heel {booklet.heel_deg:g} deg. {len(booklet.rows)} printed draft rows. "
                   "Starting tolerances: docs/BOOKLET_CHECK.md; this is not engineering approval.")
    writer.wrapped(f"Booklet datum in model metres: x origin {booklet.x_origin_m:g}, direction "
                   f"{booklet.x_direction:g}; z origin {booklet.z_origin_m:g}. KMT is above the built keel. "
                   f"MCT basis {booklet.mct_basis}, trim length {booklet.trim_length_m} m.")
    methods = list(dict.fromkeys(c.method for c in check.comparisons if c.method))
    for method in methods:
        writer.wrapped(f"Method: {method}.")
    from ..booklet_check import QUANTITIES

    rows = []
    for key, quantity in QUANTITIES.items():
        cells = [c for c in check.comparisons if c.quantity == key]
        errors = [abs(c.error) for c in cells if c.error is not None]
        rows.append([key, quantity.unit, str(sum(c.label == "within tolerance" for c in cells)),
                     str(sum(c.label == "outside tolerance" for c in cells)),
                     str(sum(c.label == "not comparable" for c in cells)), fmt(max(errors), 4) if errors else "-"])
    writer.table(["Quantity", "Unit", "Within", "Outside", "Not comparable", "Max abs error"],
                 rows, [16, 10, 7, 7, 15, 16])
    for reason in dict.fromkeys(c.reason for c in check.comparisons if c.reason):
        writer.wrapped(f"Not comparable: {reason}.")
    for warning in check.warnings:
        writer.wrapped(f"Note: {warning}")
    writer.wrapped("See the booklet_check CSV for every printed value, computed value, error, tolerance and label.")


def write_overlay_pages(writer: PageWriter, build: DraftBuild) -> None:
    for path in build.overlay_images:
        figure = writer.new_page()
        writer.line(f"Station overlay: {path.name}", size=HEADING_SIZE, weight="bold", gap=1.4)
        writer.line("Built station cuts (coloured) drawn on the source drawing, at each section's calibration.")
        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((MAX_IMAGE_SIDE_PX, MAX_IMAGE_SIDE_PX))
            pixels = np.asarray(image)
        axes = figure.add_axes([LEFT, BOTTOM + 0.01, RIGHT - LEFT, writer.y - BOTTOM - 0.02])
        axes.imshow(pixels, interpolation="lanczos")
        axes.set_axis_off()


def write_report(facts: ReportFacts, path: Path) -> Path:
    from matplotlib import rc_context
    from matplotlib.backends.backend_pdf import PdfPages

    title = f"{facts.build.vessel} {facts.build.revision_id} DRAFT"
    metadata = {"Title": f"MarinaFrame draft review report: {title}", "Subject": FOOTER,
                "Creator": facts.generated_by, "CreationDate": None}
    # TrueType (type 42) fonts keep the text selectable and searchable in PDF readers.
    with rc_context({"pdf.fonttype": 42}), PdfPages(path, metadata=metadata) as pdf:
        writer = PageWriter(pdf, title)
        write_summary(writer, facts)
        if facts.booklet_check is not None:
            write_booklet_section(writer, facts.booklet_check)
        if facts.accuracy_facts is not None:
            write_accuracy_section(writer, facts.accuracy_facts)
        if facts.capacity_rows:
            write_capacity_plan(writer, facts.capacity_rows)
        write_overlay_pages(writer, facts.build)
        writer.finish_page()
    return path
