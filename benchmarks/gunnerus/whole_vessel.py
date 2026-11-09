"""Gunnerus whole-vessel step 1 (development case): GA -> decks, deckhouses, bulwarks.

Plan: docs/plans/2026-11-09-whole-vessel-scope.md, section 3. No model call:
the reader is deterministic, and code fills gaps with labelled guesses.

The component description below holds selectors that a person read from the
GA profile (level hints and the plan view of each component). Selectors are not
geometry: ``ga_reader`` snaps each one to drawn ink. The next version gets the
description from the model (source ``ai_inferred``).

Usage (outputs are drawing derivatives: keep them in a git-ignored folder)::

    PYTHONPATH=src python -m benchmarks.gunnerus.whole_vessel \\
        --sources work/sources/gunnerus --out work/whole-vessel/run-001
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from vessel_reconstruction import ga_reader
from vessel_reconstruction.ga_reader import View
from vessel_reconstruction.ship_measure import read_dxf, source_hash

GA_FILE = 'polarkonsult/GA Gunnerus Rev1.dxf'
# Frame 0 and baseline in the GA profile; plan centrelines from the deck-edge pairs
# (S0CO5 lines at +-4.8 m). Host calibration, reviewed by a person (as in W13).
FRAME0_X = 4973.089172
STRUCTURE_LAYERS = ['S0CO1', 'S0CO3', 'S0CO5', 'S0DA1']
VIEWS = {
    'profile': View('profile', 'profile', [3000, 46000, 41500, 64000], [FRAME0_X, 47493.95],
                    layers=STRUCTURE_LAYERS),
    'plan_1deck': View('plan_1deck', 'plan', [3000, 22419.4, 41500, 33019.4], [FRAME0_X, 27719.4],
                       layers=STRUCTURE_LAYERS),
    'plan_adeck': View('plan_adeck', 'plan', [3000, 33677.9, 41500, 44277.9], [FRAME0_X, 38977.9],
                       layers=STRUCTURE_LAYERS),
    # Heavy outline layers only: tier-2 walls without the room partitions.
    'plan_adeck_walls': View('plan_adeck_walls', 'plan', [3000, 33677.9, 41500, 44277.9], [FRAME0_X, 38977.9],
                             layers=['S0CO3', 'S0CO5']),
}
# Inner footprints remove the line that touches the outside (the deck edge) once.
TIER2_PEEL = 1
# Level selectors: (printed label or None, z hint m, x hint m). The label wins when present.
LEVELS = {
    'aft_deck': (None, 4.11, 5.0),
    'main_deck': ('1-DECK', 4.29, 20.0),
    'a_deck': ('A-DECK', 6.69, 20.0),
    'aft_bulwark_top': (None, 5.11, 5.0),
    'tier2_roof': (None, 9.09, 20.0),
    'wheelhouse_roof': (None, 11.49, 17.0),
    'fwd_rail_top': (None, 7.71, 31.0),
}
# Gap fills (source "guessed"). The GA does not give plate or bulwark thickness.
DECK_PLATE_M = 0.010
BULWARK_THICKNESS_M = 0.050
# A tier above another is assumed this much narrower on each side when its plan is missing.
TIER_INSET_M = 1.0
# Printed labels sit just above their line; a label selects the nearest level below it.
LABEL_SEARCH_M = 0.3
# A deckhouse end wall is a heavy transverse line on the plan of the deck it stands on, at least
# this fraction of the moulded breadth long (shorter lines are lockers, stairs and recesses).
END_WALL_LAYERS = ['S0CO3']
END_WALL_MIN_FRACTION = 0.4
BREADTH_M = 9.60  # title block


def label_heights(path: Path, view: View) -> dict:
    import ezdxf

    heights = {}
    for entity in ezdxf.readfile(path).modelspace().query('TEXT MTEXT'):
        text = entity.dxf.text if entity.dxftype() == 'TEXT' else entity.plain_text()
        point = [[entity.dxf.insert.x, entity.dxf.insert.y]]
        if view.contains(point) and re.fullmatch(r'[A-Z0-9]-DECK', text.strip()):
            heights[text.strip()] = float(view.to_ship(point)[0][1])
    return heights


def read_levels(levels, labels) -> dict:
    """Snap every selector. Return {name: {'z', 'extent', 'entity_ids', 'source', 'basis'}}."""
    result = {}
    for name, (label, z_hint, x_hint) in LEVELS.items():
        found, basis = None, f'hint z={z_hint} m'
        if label and label in labels:
            below = [level for level in levels if labels[label] - LABEL_SEARCH_M <= level.z_m <= labels[label]]
            below = [level for level in below if any(a - 0.4 <= x_hint <= b + 0.4 for a, b in level.intervals)]
            if below:
                # The deck is the longest drawn line under its label (inner lines are shorter).
                found = max(below, key=lambda level: sum(b - a for a, b in level.intervals))
                basis = f'printed label {label}'
        if found is None:
            found = ga_reader.snap_level(levels, z_hint, x_hint)
        if found is None:
            result[name] = {'z': z_hint, 'extent': None, 'entity_ids': [], 'source': 'guessed',
                            'basis': f'no drawn level near {basis}; hint used'}
        else:
            result[name] = {'z': found.z_m, 'extent': found.extent_near(x_hint), 'x_range': found.x_range,
                            'entity_ids': found.entity_ids, 'source': 'traced', 'basis': basis}
    return result


def interval_record(region, low, high, sha) -> dict:
    """Two traced levels make a measured height interval; otherwise None."""
    if low['source'] != 'traced' or high['source'] != 'traced' or not low['z'] < high['z']:
        return None
    return {'status': 'measured', 'kind': 'interval', 'view': 'profile', 'region': region,
            'method': 'profile_levels', 'source_sha256': sha, 'value': [low['z'], high['z']],
            'entity_ids': low['entity_ids'] + high['entity_ids']}


def outline_record(region, view, outline, evidence, sha) -> dict:
    return {'status': 'measured', 'kind': 'outline', 'view': 'plan', 'region': region,
            'method': 'enclosed_region', 'source_sha256': sha, 'value': outline,
            'entity_ids': [evidence], 'plan_view': view}


class VectorReader:
    """Drawing evidence from the GA DXF: levels, printed labels, footprints and end walls."""

    def __init__(self, sources: Path):
        path = sources / GA_FILE
        self.source_file, self.sha = GA_FILE, source_hash(path)
        self.entities = read_dxf(path)
        self.levels = ga_reader.profile_levels(self.entities, VIEWS['profile'])
        self.labels = label_heights(path, VIEWS['profile'])
        self.plans = {name: ga_reader.PlanRaster(self.entities, view)
                      for name, view in VIEWS.items() if view.kind == 'plan'}

    def footprint(self, view, x_range, mode, peel):
        return self.plans[view].footprint(x_range, mode, peel)

    def evidence(self, view) -> str:
        return f'{view}:{len(self.plans[view].entity_ids)} entities'

    def end_walls(self, deck_view, x_range, min_length_m):
        view = VIEWS[deck_view]
        wall_view = View(view.name, view.kind, view.bounds, view.origin, layers=END_WALL_LAYERS)
        return ga_reader.transverse_walls(self.entities, wall_view, x_range, min_length_m)


def build_inputs(sources: Path, reader=None) -> dict:
    """Program, measurements and guesses for the step 1 components.

    ``reader`` gives the drawing evidence (default: the GA DXF). The raster path
    (``whole_vessel_raster.RasterReader``) gives the same evidence from the PDF image.
    """
    reader = reader or VectorReader(sources)
    sha = reader.sha
    lv = read_levels(reader.levels, reader.labels)
    measurements, guesses, components = {}, {}, []

    def extent(name, fallback):
        return lv[name]['extent'] or fallback

    def outline(region, view, x_range, mode, fallback, basis, peel=1):
        polygon = reader.footprint(view, x_range, mode, peel) if view else None
        if polygon:
            measurements[f'{region}_outline'] = outline_record(region, view, polygon, reader.evidence(view), sha)
        else:
            guesses[f'{region}_outline'] = {'kind': 'outline', 'value': fallback, 'source': 'guessed',
                                            'basis': basis}
        return polygon or fallback

    def height(region, low, high):
        record = interval_record(region, lv[low], lv[high], sha)
        if record:
            measurements[f'{region}_height'] = record
        else:
            guesses[f'{region}_height'] = {'kind': 'interval', 'value': [lv[low]['z'], lv[high]['z']],
                                           'source': 'guessed',
                                           'basis': f'{low}: {lv[low]["basis"]}; {high}: {lv[high]["basis"]}'}

    def deck_height(region, level):
        z = lv[level]['z']
        guesses[f'{region}_height'] = {'kind': 'interval', 'value': [round(z - DECK_PLATE_M, 4), z],
                                       'source': 'guessed', 'entity_ids': lv[level]['entity_ids'],
                                       'basis': f'top {lv[level]["source"]} ({lv[level]["basis"]}); '
                                                f'plate thickness guessed {DECK_PLATE_M} m'}

    def thickness(region):
        guesses[f'{region}_thickness'] = {'kind': 'length', 'value': BULWARK_THICKNESS_M, 'source': 'guessed',
                                          'basis': 'GA gives no bulwark thickness'}

    def add(cid, op, view, args):
        components.append({'id': cid, 'op': op, 'source': {'view': 'plan', 'region': cid,
                                                           'method': 'enclosed_region'}, 'args': args})

    aft_walls = {}

    def walls_aft_end(region, deck_view, roof_range):
        """Move the aft end of a tier from its roof end to its aftmost end wall, when one is drawn."""
        walls = reader.end_walls(deck_view, roof_range, END_WALL_MIN_FRACTION * BREADTH_M)
        walls = [wall for wall in walls if wall['x_m'] < roof_range[1]]
        aft_walls[region] = {'roof_range': roof_range, 'walls': walls[:3]}
        if not walls:
            return roof_range
        return [max(roof_range[0], walls[0]['x_m']), roof_range[1]]

    # Hull-width box used only when a plan view gives nothing (B = 9.60 m in the title block).
    half_beam = BREADTH_M / 2
    aft = extent('aft_deck', [-1.0, 14.5])
    main = extent('main_deck', [14.5, 32.7])
    # A roof covers the whole drawn level, across breaks (the A-deck line has a 0.8 m break).
    # The tier starts at its aft end wall on the deck below, not at the roof end (overhang).
    tier1 = walls_aft_end('house_t1', 'plan_1deck', lv['a_deck'].get('x_range') or [12.3, 34.6])
    tier2 = walls_aft_end('house_t2', 'plan_adeck', extent('tier2_roof', [14.5, 24.1]))
    # The open aft deck ends where the first tier starts (raster levels can merge nearby lines).
    aft = [aft[0], min(aft[1], tier1[0])]
    wheel = extent('wheelhouse_roof', [13.6, 21.3])
    rail = extent('fwd_rail_top', [27.5, 35.2])

    aft_outline = outline('aft_deck', 'plan_1deck', aft, 'outer', ga_reader.box_outline(aft, half_beam),
                          'beam box over the aft deck extent')
    add('aft_deck', 'deck', 'plan_1deck', {'outline': 'aft_deck_outline', 'height': 'aft_deck_height'})
    deck_height('aft_deck', 'aft_deck')

    outline('main_deck', 'plan_1deck', main, 'outer', ga_reader.box_outline(main, half_beam),
            'beam box over the 1-deck extent')
    add('main_deck', 'deck', 'plan_1deck', {'outline': 'main_deck_outline', 'height': 'main_deck_height'})
    deck_height('main_deck', 'main_deck')

    t1_outline = outline('house_t1', 'plan_adeck', tier1, 'outer', ga_reader.box_outline(tier1, half_beam),
                         'beam box over the A-deck extent')
    add('house_t1', 'deckhouse', 'plan_adeck', {'outline': 'house_t1_outline', 'height': 'house_t1_height'})
    height('house_t1', 'main_deck', 'a_deck')

    # The aft bulwark stands on the aft deck edge: it uses the deck outline.
    if 'aft_deck_outline' in measurements:
        measurements['aft_bulwark_outline'] = {**measurements['aft_deck_outline'], 'region': 'aft_bulwark'}
    else:
        guesses['aft_bulwark_outline'] = {**guesses['aft_deck_outline']}
    add('aft_bulwark', 'bulwark', 'plan_1deck', {'outline': 'aft_bulwark_outline', 'height': 'aft_bulwark_height',
                                                 'thickness': 'aft_bulwark_thickness'})
    height('aft_bulwark', 'aft_deck', 'aft_bulwark_top')
    thickness('aft_bulwark')

    t1_half = ga_reader.y_extent(t1_outline)
    t2_box = ga_reader.box_outline(tier2, max(t1_half - TIER_INSET_M, 0.5))
    t2_outline = outline('house_t2', 'plan_adeck_walls', tier2, 'inner', t2_box,
                         f'tier-1 breadth less {TIER_INSET_M} m each side over the tier-2 roof extent',
                         peel=TIER2_PEEL)
    add('house_t2', 'deckhouse', 'plan_adeck_walls', {'outline': 'house_t2_outline', 'height': 'house_t2_height'})
    height('house_t2', 'a_deck', 'tier2_roof')

    # The GA wheelhouse plan has its own origin that is not calibrated: guess its breadth.
    outline('wheelhouse', None, wheel, 'outer', ga_reader.box_outline(wheel, ga_reader.y_extent(t2_outline)),
            'tier-2 breadth over the wheelhouse roof extent; wheelhouse plan view not calibrated')
    add('wheelhouse', 'deckhouse', None, {'outline': 'wheelhouse_outline', 'height': 'wheelhouse_height'})
    height('wheelhouse', 'tier2_roof', 'wheelhouse_roof')

    outline('fwd_rail', 'plan_adeck', rail, 'outer', ga_reader.box_outline(rail, half_beam),
            'beam box over the forward rail extent')
    add('fwd_rail', 'bulwark', 'plan_adeck', {'outline': 'fwd_rail_outline', 'height': 'fwd_rail_height',
                                              'thickness': 'fwd_rail_thickness'})
    height('fwd_rail', 'a_deck', 'fwd_rail_top')
    thickness('fwd_rail')

    program = {'schema': 'ship-cad/v1', 'components': components}
    return {'program': program, 'measurements': measurements, 'guesses': guesses, 'levels': lv,
            'source': {'file': reader.source_file, 'sha256': sha}, 'tier_end_walls': aft_walls,
            'all_profile_levels': [{'z': level.z_m, 'intervals': level.intervals} for level in reader.levels]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--in-process', action='store_true',
                        help='Run the trusted executor in this process (development only; no OS sandbox).')
    parser.add_argument('--no-appendages', action='store_true',
                        help='Leave out the appendages (thrusters, skeg) of whole_vessel_appendages.py.')
    parser.add_argument('--no-detail', action='store_true',
                        help='Straight extruded parts (no hull side, camber, end contours or windows).')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    inputs = build_inputs(args.sources)
    if not args.no_appendages:
        from benchmarks.gunnerus.whole_vessel_appendages import add_appendages
        add_appendages(inputs, args.sources, GA_FILE)
    if not args.no_detail:
        from benchmarks.gunnerus.whole_vessel_detail import add_detail
        add_detail(inputs, args.sources)
    (out / 'inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
    if args.in_process:
        from vessel_reconstruction.ship_cad import execute
        result = execute(inputs['program'], inputs['measurements'], out / 'task' / 'work' / 'output',
                         guesses=inputs['guesses'], detail=inputs.get('detail'))
        execution = {'exit_code': 0, 'result': result, 'sandbox': 'none (development, --in-process)'}
    else:
        from vessel_reconstruction.ship_cad_worker import run
        execution = run(inputs['program'], inputs['measurements'], out / 'task', guesses=inputs['guesses'],
                        detail=inputs.get('detail'))
    (out / 'execution.json').write_text(json.dumps(execution, indent=2, default=str) + '\n')
    for component in (execution.get('result') or {}).get('components', []):
        print(component['id'], component['status'], component.get('built'), component.get('source_labels'),
              round(component.get('volume_m3', 0.0), 2))


if __name__ == '__main__':
    main()
