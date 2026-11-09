"""Gunnerus whole-vessel detail: the hull side and the drawn shape of the parts above the hull.

Plan: docs/plans/2026-11-09-whole-vessel-scope.md, section 3.8 (development case).
"""
from __future__ import annotations

from pathlib import Path

LINES_FILE = 'polarkonsult/Lines Plan Rev0.dxf'


def hull_sections(sources: Path) -> list[dict]:
    """The lines-plan station sections that the hull loft uses (read only, no CAD).

    The stations are not cut at the deck: above the deck they are the drawn shell of the
    bulwark and the forecastle, which the parts above the hull must follow.
    """
    from benchmarks.gunnerus import make_gunnerus_configs, vector_path

    config, _ = make_gunnerus_configs.vector_config(sources / LINES_FILE)
    return vector_path.read_sections(config, sources / LINES_FILE)['sections']


MIDSHIP_FILE = 'polarkonsult/Midship Section Rev0.dxf'
BREADTH_M = 9.60  # title block
# Standard deck camber when no section drawing gives one: B/50 at the centreline.
STANDARD_CAMBER_FRACTION = 1 / 50
DECK_PARTS = ('aft_deck', 'main_deck')
# Windows are looked for in the profile this far past a tier's roof ends (raked fronts).
WINDOW_SEARCH_MARGIN_M = 3.0
# The GA wheelhouse plan draws cut forward corners (about a fifth of the breadth); that plan view
# is not calibrated, so the wheelhouse outline is a box and its forward corners get this radius.
WHEELHOUSE_FWD_CORNER_RADIUS_M = 1.2


def labelled(value, source: str, basis: str) -> dict:
    return {'value': value, 'source': source, 'basis': basis}


def deck_camber(sources: Path) -> dict:
    """Camber read from the midship-section deck lines, else the standard B/50 (guessed)."""
    from vessel_reconstruction.ga_reader import section_deck_camber

    path = sources / MIDSHIP_FILE
    read = section_deck_camber(path) if path.is_file() else None
    if read is not None:
        shape = 'straight level lines: no camber' if read['camber_m'] == 0 else 'median rise'
        return labelled(read['camber_m'], 'traced', f'midship section: {read["sections"]} labelled 1-DECK '
                        f'moulded lines, rise {read["rises_m"]} m ({shape})')
    camber = round(BREADTH_M * STANDARD_CAMBER_FRACTION, 3)
    return labelled(camber, 'guessed', 'no deck line read in a section drawing; standard camber B/50')


def _value(inputs, reference):
    record = inputs['measurements'].get(reference) or inputs['guesses'].get(reference) or {}
    return record.get('value')


def deckhouse_detail(inputs: dict, sources: Path) -> dict:
    """End contours, windows and plan corners of each deckhouse from the GA profile."""
    from benchmarks.gunnerus.whole_vessel import END_WALL_LAYERS, GA_FILE, VIEWS
    from vessel_reconstruction import ga_reader
    from vessel_reconstruction.ga_reader import View
    from vessel_reconstruction.ship_measure import read_dxf

    entities = read_dxf(sources / GA_FILE)
    profile = VIEWS['profile']
    walls = View(profile.name, profile.kind, profile.bounds, profile.origin, layers=END_WALL_LAYERS)
    details = {}
    for component in inputs['program']['components']:
        if component['op'] != 'deckhouse':
            continue
        args = component['args']
        outline, height = _value(inputs, args['outline']), _value(inputs, args['height'])
        if outline is None or height is None:
            continue
        low, high = height
        xs = [point[0] for point in outline]
        part = {}
        for side, x in (('aft', min(xs)), ('fwd', max(xs))):
            contour = ga_reader.end_contour(entities, walls, x, high, low)
            if contour is None:
                part[f'end_{side}'] = labelled(None, 'guessed', f'no end line drawn in the profile at the roof '
                                               f'end x {x:.2f} m; vertical wall assumed')
                continue
            rest = '' if contour['reached_base'] else '; continued vertically below the drawn line'
            part[f'end_{side}'] = labelled(contour['points'], 'traced',
                                           f'profile end line from the roof end x {x:.2f} m down to the base '
                                           f'({len(contour["entity_ids"])} entities){rest}')
        windows = ga_reader.profile_windows(entities, profile, [min(xs) - WINDOW_SEARCH_MARGIN_M,
                                                                max(xs) + WINDOW_SEARCH_MARGIN_M], [low, high])
        if windows:
            part['windows'] = labelled([w['x_m'] + w['z_m'] for w in windows], 'traced',
                                       f'{len(windows)} closed window outlines in the profile; each is cut into both '
                                       'side walls where it lies on them (not across a raked end)')
            part['window_recess_m'] = labelled(0.05, 'guessed', 'recess depth not drawn; 0.05 m')
        if component['id'] == 'wheelhouse' and inputs['guesses'].get(args['outline']):
            part['corner_radius_m'] = labelled({'aft': 0.0, 'fwd': WHEELHOUSE_FWD_CORNER_RADIUS_M}, 'guessed',
                                               'outline is a guessed box; forward corners rounded as the '
                                               'uncalibrated plan of this tier draws them cut')
        details[component['id']] = part
    return details


def add_detail(inputs: dict, sources: Path) -> dict:
    """Add ``inputs['detail']``: the hull side and the labelled detail values of each part."""
    from vessel_reconstruction.superstructure import HullSide

    sections = hull_sections(sources)
    hull = HullSide.from_sections(sections)
    camber = deck_camber(sources)
    parts = {part: {'camber_m': camber} for part in DECK_PARTS}
    parts.update(deckhouse_detail(inputs, sources))
    inputs['detail'] = {
        'hull_side': labelled(hull.to_dict(), 'traced',
                              f'lines plan: {len(sections)} station sections, not cut at the deck; above a '
                              'drawn top the flare of the top rows continues for at most 1.5 m'),
        'parts': parts}
    return inputs['detail']
