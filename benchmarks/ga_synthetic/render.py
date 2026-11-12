"""Three orthographic projections of the same metre-space boxes, not fitted solids."""
from benchmarks.concept_launch.sheets import Sheet, View
from benchmarks.factory.render_lines import _text


def draw_arrangement(case):
    sheet = Sheet('ga', f"{case['case_id']}.png", 'Synthetic commercial GA', 1)
    dims = case['dimensions']
    length, beam, depth = (dims[k] for k in ('lbp_m', 'breadth_m', 'depth_m'))
    scale = 3440 / length
    views = [('PROFILE', View('profile', 260, 880, scale), 'z'),
             ('UPPER DECK PLAN', View('upper_deck', 260, 1400, scale), 'y'),
             ('TANK TOP PLAN', View('tank_top', 260, 2200, scale), 'y')]
    sheet.rect([40, 40, 3920, 2760])
    sheet.text((100, 90), f"{case['case_id']}   {case['ship_type'].replace('_', ' ').upper()}", 32)
    sheet.text((100, 145), 'SYNTHETIC BOX ARRANGEMENT - NOT FOR CONSTRUCTION - engineering_approved=false', 24)
    spacing = case['frames']['spacings'][0]['spacing_mm']
    sheet.text((100, 195), f'FRAME 0 AT AP. FRAME SPACING {spacing} mm. x FWD; y PORT; z ABOVE BASE LINE.', 24)
    sheet.text((100, 245), f"LBP {length:.2f} m   B {beam:.2f} m   D {depth:.2f} m", 24)
    for title, view, axis in views:
        sheet.text((260, view.origin_row - (depth + 9 if axis == 'z' else beam / 2 + 4) * scale), title, 26)
        low, high = (0, depth) if axis == 'z' else (-beam / 2, beam / 2)
        sheet.rect(view.box(0, length, low, high), width=3)
        if axis == 'y':
            sheet.line([view.px(0, 0), view.px(length, 0)], width=1, dash=(12, 6))
        for space in case['spaces']:
            kind, box = space['kind'], space['box_m']
            if view.name == 'upper_deck' and kind not in ('cargo_hatch', 'cargo_crane', 'accommodation_deck', 'cargo_tank'):
                continue
            if view.name == 'upper_deck' and kind == 'accommodation_deck' and space['label'] != 'DECK 1':
                continue
            if view.name == 'tank_top' and kind not in ('cargo_hold', 'cargo_tank', 'ballast_tank', 'engine_room'):
                continue
            # Port and starboard share a profile projection; print the pair once.
            if axis == 'z' and (space['label'].endswith(' P')):
                continue
            x0, x1 = box['x']
            b0, b1 = box[axis]
            sheet.rect(view.box(x0, x1, b0, b1), width=1.5)
            label = space['label']
            if axis == 'z' and label.endswith(' S'):
                label = label[:-2] + ' P/S'
            if kind == 'cargo_crane':
                # Narrow posts need a leader, rather than text through adjacent holds.
                point = view.px((x0 + x1) / 2, b1)
                sheet.line([point, (point[0], point[1] - 22)], width=1)
                sheet.text((point[0], point[1] - 32), label, 16, anchor='mm')
            else:
                sheet.text(view.px((x0 + x1) / 2, (b0 + b1) / 2), label, 16, anchor='mm')
        tick_row = view.origin_row - low * scale + 26
        for entry in case['frame_table']:
            frame, x = entry['frame'], entry['x_m']
            col = view.px(x, 0)[0]
            sheet.line([(col, tick_row), (col, tick_row + (14 if frame % 10 == 0 else 6))], width=1)
            if frame % 10 == 0:
                # Reuse the lines-sheet renderer's supersampled text implementation.
                _text(sheet.draw, (col - 8, tick_row + 18), str(frame), 16)
        chain_row = tick_row + 85
        boundaries = sorted({0, length} | {s['box_m']['x'][i] for s in case['spaces']
                                         if s['kind'] in ('cargo_hold', 'cargo_tank', 'engine_room') for i in (0, 1)})
        for x0, x1 in zip(boundaries, boundaries[1:]):
            c0, c1 = view.px(x0, 0)[0], view.px(x1, 0)[0]
            sheet.line([(c0, chain_row), (c1, chain_row)], width=1)
            for col in (c0, c1):
                sheet.line([(col, chain_row - 8), (col, chain_row + 8)], width=1)
            sheet.text(((c0 + c1) / 2, chain_row + 18), f'{x1 - x0:.2f}', 16, anchor='mm')
    sheet.text((100, 2610), 'DIMENSION CHAINS IN METRES. W.B. = WATER BALLAST; DB = DOUBLE BOTTOM; C.O.T. = CARGO OIL TANK.', 22)
    sheet.text((100, 2660), 'E/R = ENGINE ROOM. CR. = CARGO CRANE. P = PORT. S = STARBOARD. BOX FACES ARE THE SCORING TARGET.', 22)
    return sheet.finish()
