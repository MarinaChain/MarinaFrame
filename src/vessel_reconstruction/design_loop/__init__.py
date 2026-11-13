"""Record-driven preliminary concept design; no accuracy or compliance claim."""
from copy import deepcopy
from dataclasses import asdict

import numpy as np

from ..design_record import DesignRecord, quantity
from .evidence import canonical_quantity, fragment_evidence, read_evidence
from .graph import Step, run_graph

VERSION = '1.0.0'


def _q(value, unit, sources, method='explicit design-loop assumption'):
    return quantity(value, unit, method=method, method_version=VERSION, sources=sources)


def _component(name, kind, quantities, notes=()):
    return dict(id=name, kind=kind, quantities=quantities, labels={}, files=[], notes=list(notes))


def create_record(config):
    """Put all inputs in the record before any calculation; no implicit fleet."""
    from ..concept_dimensions import Requirements
    sources = config['sources']
    if not sources or any(not isinstance(s, str) or not s.strip() for s in sources):
        raise ValueError('Nonempty sources are required')
    req = Requirements(**config['requirements'])
    fragment = req.to_record_fragment()
    quantities = {key: canonical_quantity(value) for key, value in fragment.items()
                  if isinstance(value, dict) and value['value'] is not None
                  and not key.startswith('service_speed')}
    speed = None
    if req.service_speed_kn is not None:
        speed = dict(kn=_q(req.service_speed_kn, 'kn', sources, 'public requirement or explicit input'),
                     m_s=_q(req.service_speed_kn * 1852 / 3600, 'm/s', sources, 'kn to SI'))
    for value in quantities.values():
        value['sources'] = list(sources)
    results = {name: {} for name in ('hull_variation', 'hydrostatics', 'resistance', 'power', 'fuel', 'capacities', 'stability')}
    results['stability']['inputs'] = fragment_evidence(config)
    record = dict(schema_version='1.1.0', design_id=config['design_id'], name=config['name'], status='draft',
        engineering_approved=False, data_scope=dict(kind='public', customer_id=None, permitted_uses=['development']),
        requirements=dict(quantities=quantities, service_speed=speed, cargo_types=list(req.cargo_types),
            class_notation=req.class_notation, flag=req.flag, constraints=[]), main_dimensions={},
        hull=dict(parameters={}, surfaces=[], coordinate_system='m; x aft cap to forward cap; y signed; z retained baseline',
            notes=['Parent support may be trimmed. No full-vessel fidelity, fairness or compliance claim.']),
        compartments=[], tanks=[], weights=[], loading_conditions=[], midship_section_inputs=[], appendages=[],
        results=results, lineage=dict(parent_design_id='caller-supplied-parent', variation_parameters={}), designer_decisions=[])
    return DesignRecord.from_dict(record)


def _config(data):
    config = read_evidence(data, 'stability', 'inputs')
    # Quantity values are canonical floating-point numbers. Restore discrete
    # input contracts only after checking integrality; never truncate counts.
    for name in ('cargo_rows', 'cargo_columns', 'slop_columns'):
        value = config['arrangement'][name]
        if isinstance(value, bool) or not float(value).is_integer():
            raise ValueError('Tank counts must be integers')
        config['arrangement'][name] = int(value)
    year = config['efficiency']['year']
    if isinstance(year, bool) or not float(year).is_integer():
        raise ValueError('CII year must be an integer')
    config['efficiency']['year'] = int(year)
    return config


def _sections(data):
    from ..hull_variation import HullSections
    return HullSections(**data)


def _section_dict(hull):
    return {key: value.tolist() if hasattr(value, 'tolist') else value for key, value in vars(hull).items()}


def _concept(record):
    from ..concept_dimensions import FleetModel, FleetShip, Requirements
    data = record.to_dict()
    config = _config(data)
    rows = [FleetShip(**row) for row in config['fleet']]
    requirements = data['requirements']
    values = {name: requirements['quantities'][key]['value'] for name, key in
        (('dwt_t', 'dwt'), ('cargo_volume_m3', 'cargo_volume'), ('range_m', 'range'),
         ('max_draft_m', 'max_draft'), ('max_beam_m', 'max_beam')) if key in requirements['quantities']}
    if requirements['service_speed'] is not None:
        values['service_speed_kn'] = requirements['service_speed']['kn']['value']
    values.update({key: requirements[key] for key in ('cargo_types', 'class_notation', 'flag')})
    proposal = FleetModel.fit(rows).propose(Requirements(**values))
    fragment = proposal.to_record_fragment()
    data['main_dimensions'] = {key: canonical_quantity(value) for key, value in fragment['main_dimensions'].items()}
    data['results']['capacities']['concept'] = fragment_evidence(fragment)
    return DesignRecord.from_dict(data)


def _hull(record):
    from ..hull_variation import vary_sections, section_properties, build_candidate
    data = record.to_dict()
    config = _config(data)
    parent = _sections(config['parent'])
    dimensions = {key: value['value'] for key, value in data['main_dimensions'].items()}
    _, lcb = section_properties(parent)
    hull = vary_sections(parent, length_m=dimensions['lpp'], breadth_m=dimensions['beam'],
        draft_m=dimensions['draft'], cb=dimensions['cb'], lcb_fraction=lcb / parent.length_m)
    if dimensions['depth'] <= hull.draft_m or parent.z_m[-1] <= parent.draft_m:
        raise ValueError('Parent needs supported freeboard and chosen depth above draft')
    # Match the freeboard height independently without extending the sampled
    # domain. Underwater Lackenby geometry and its targets are unchanged.
    above = hull.z_m > hull.draft_m
    hull.z_m[above] = hull.draft_m + (hull.z_m[above] - hull.draft_m) * (
        (dimensions['depth'] - hull.draft_m) / (hull.z_m[-1] - hull.draft_m))
    if hull.section_z_m is not None:
        above = hull.section_z_m > hull.draft_m
        hull.section_z_m[above] = hull.draft_m + (hull.section_z_m[above] - hull.draft_m) * (
            (dimensions['depth'] - hull.draft_m) / (parent.z_m[-1] * hull.draft_m / parent.draft_m - hull.draft_m))
    if hull.regions is not None:
        original_depth = parent.z_m[-1] * hull.draft_m / parent.draft_m
        for station in hull.regions:
            for region in station:
                for row in region['rows_m']:
                    if row[0] > hull.draft_m:
                        row[0] = hull.draft_m + (row[0] - hull.draft_m) * (
                            (dimensions['depth'] - hull.draft_m) / (original_depth - hull.draft_m))
    candidate = build_candidate(hull)
    data['hull']['parameters'] = deepcopy(data['main_dimensions'])
    data['results']['hull_variation']['sections'] = fragment_evidence(_section_dict(hull))
    data['results']['hull_variation']['report'] = fragment_evidence(candidate.report)
    data['results']['hydrostatics']['hull'] = fragment_evidence(candidate.report['hydrostatics'])
    return DesignRecord.from_dict(data)


def _arrangement(record):
    from ..arrangement_generator import ArrangementInput, generate_arrangement
    from ..hull_variation import build_candidate
    data = record.to_dict()
    config = _config(data)
    hull = _sections(read_evidence(data, 'hull_variation', 'sections'))
    dim = {key: value['value'] for key, value in data['main_dimensions'].items()}
    inputs = ArrangementInput(length_m=hull.length_m, breadth_m=hull.breadth_m, depth_m=dim['depth'],
        deadweight_t=data['requirements']['quantities']['dwt']['value'], rule_length_m=hull.length_m,
        solas_length_m=hull.length_m, sources=tuple(config['sources']), **config['arrangement'])
    result = generate_arrangement(build_candidate(hull).solid, inputs, hull_units='mm')
    fragment = result.to_record_fragment()
    components = []
    for compartment in result.compartments:
        q = lambda value, unit: _q(value, unit, list(inputs.sources), 'closed hull planar partition')
        quantities = dict(volume=q(compartment.volume_m3, 'm3'), capacity_98=q(compartment.capacity_98_m3, 'm3'))
        quantities.update({f'centre_{axis}': q(value, 'm') for axis, value in zip('xyz', compartment.centre_m)})
        components.append(_component(compartment.name, compartment.kind, quantities, fragment['limits']))
    data['compartments'] = components
    data['tanks'] = [deepcopy(item) for item in components if item['kind'] in ('cargo', 'slop', 'ballast', 'fuel')]
    data['results']['capacities']['arrangement'] = fragment_evidence(fragment)
    return DesignRecord.from_dict(data)


def _weights(record):
    from ..weights_efficiency.weights import WeightInput, estimate_weights
    from ..hull_variation import section_properties
    data = record.to_dict()
    config = _config(data)
    dim = {key: value['value'] for key, value in data['main_dimensions'].items()}
    hull = _sections(read_evidence(data, 'hull_variation', 'sections'))
    level = .8 * dim['depth']
    if level > hull.z_m[-1]:
        raise ValueError('Parent support does not cover 0.8 depth')
    hull.draft_m = level
    cb, _ = section_properties(hull)
    hydro = read_evidence(data, 'hydrostatics', 'hull')
    assumptions = deepcopy(config['weights'])
    assumptions['component_cg_m'] = tuple(tuple(row) for row in assumptions['component_cg_m'])
    result = estimate_weights(WeightInput(length_m=dim['lpp'], beam_m=dim['beam'], depth_m=dim['depth'],
        draft_m=dim['draft'], cb_at_80_depth=cb, displacement_t=hydro['volume_m3'] * config['power']['water_density_kg_m3'] / 1000,
        sources=tuple(config['sources']), **assumptions))
    fragment = result.to_record_fragment()
    data['weights'] = [_component('preliminary-lightship', 'weight-estimate',
        {key: canonical_quantity(value) for key, value in fragment['quantities'].items()}, [result.scope,
        'Engine mass and MCR are explicit initial weight assumptions, not updated from later selection.'])]
    data['results']['stability']['weights'] = fragment_evidence(fragment)
    return DesignRecord.from_dict(data)


def _power(record):
    from ..holtrop import HoltropHull, holtrop_resistance
    from ..weights_efficiency.engine import brake_power_from_holtrop
    data = record.to_dict()
    config = _config(data)
    hydro = read_evidence(data, 'hydrostatics', 'hull')
    inputs = HoltropHull(lwl_m=hydro['waterline_length_m'], beam_m=hydro['waterline_beam_m'],
        draft_m=hydro['draft_m'], volume_m3=hydro['volume_m3'], cm=hydro['cm'], cwp=hydro['cwp'],
        lcb_percent_lwl_forward=100 * (hydro['lcb_m'] / hydro['waterline_length_m'] - .5),
        wetted_surface_m2=hydro['wetted_surface_m2'])
    assumptions = deepcopy(config['power'])
    density = assumptions.pop('water_density_kg_m3')
    viscosity = assumptions.pop('kinematic_viscosity_m2_s')
    speed = data['requirements']['service_speed']
    if speed is None:
        raise ValueError('service speed is required for power')
    resistance = holtrop_resistance(inputs, speed_ms=speed['m_s']['value'],
        water_density_kg_m3=density, kinematic_viscosity_m2_s=viscosity)
    power = brake_power_from_holtrop(resistance, sources=tuple(config['sources']), **assumptions)
    data['results']['resistance']['holtrop'] = fragment_evidence(dict(inputs=asdict(inputs), output=asdict(resistance)))
    data['results']['power']['propulsion'] = fragment_evidence(power.to_record_fragment())
    return DesignRecord.from_dict(data)


def _engine(record):
    from ..weights_efficiency.engine import EngineLayout, EngineRequest, select_engine
    data = record.to_dict()
    config = _config(data)
    settings = config['engine']
    power = read_evidence(data, 'power', 'propulsion')['quantities']['calm_brake_power_kw']
    for supplied in settings['layouts']:
        layout = EngineLayout(**{**supplied, 'sources': tuple(supplied['sources'])})
        margin = 1 - power * (1 + settings['sea_margin']) / layout.sfoc_rating_kw
        if not settings['minimum_engine_margin'] <= margin <= settings['maximum_engine_margin']:
            continue
        matches = select_engine(EngineRequest(power, settings['rpm'], settings['sea_margin'], margin,
            tuple(config['sources'])), (layout,))
        if matches:
            data['results']['power']['engine'] = fragment_evidence(dict(selection=matches[0].to_record_fragment(),
                layout=supplied, engine_margin=margin))
            return DesignRecord.from_dict(data)
    raise ValueError('No supplied engine rating/tuning table supports the requested power and margins')


def _efficiency(record):
    from ..weights_efficiency import DesignIndexInput, OperationalInput, design_index, operational_cii
    from ..weights_efficiency.engine import _interpolate_sfoc
    data = record.to_dict()
    config = _config(data)
    settings = config['efficiency']
    engine = read_evidence(data, 'power', 'engine')
    sfoc = _interpolate_sfoc(engine['layout']['sfoc_by_load'], .75)
    if sfoc is None:
        raise ValueError('Engine table does not cover index reference power')
    dwt = data['weights'][0]['quantities']['deadweight_t']['value']
    sources = tuple(settings['sources'])
    index = design_index(DesignIndexInput(deadweight_t=dwt,
        mcr_kw=engine['selection']['quantities']['smcr_kw'], reference_speed_kn=settings['reference_speed_kn'],
        main_sfoc_g_kwh=sfoc, auxiliary_sfoc_g_kwh=settings['auxiliary_sfoc_g_kwh'],
        main_fuel=settings['main_fuel'], auxiliary_fuel=settings['auxiliary_fuel'], sources=sources))
    cii = operational_cii(OperationalInput(dwt, settings['distance_nm'], tuple(tuple(row) for row in settings['fuel_t']),
        settings['year'], sources))
    data['results']['fuel']['eedi'] = fragment_evidence(index.to_record_fragment())
    data['results']['fuel']['cii'] = fragment_evidence(cii.to_record_fragment())
    return DesignRecord.from_dict(data)


def pipeline_steps():
    inputs = ('results', 'stability', 'inputs', 'value')
    config = lambda name: inputs + (name,)
    result = lambda section, name: ('results', section, name)
    return [
        Step('concept', VERSION, (('requirements',), config('fleet')), (('main_dimensions',), result('capacities', 'concept')), _concept),
        Step('hull', VERSION, (('main_dimensions',), config('parent'), config('parent_sources')),
            (('hull', 'parameters'), result('hull_variation', 'sections'), result('hull_variation', 'report'), result('hydrostatics', 'hull')), _hull, ('concept',)),
        Step('arrangement', VERSION, (result('hull_variation', 'sections'), ('main_dimensions', 'depth'),
            ('requirements', 'quantities', 'dwt'), config('arrangement'), config('sources')),
            (('compartments',), ('tanks',), result('capacities', 'arrangement')), _arrangement, ('hull',)),
        Step('weights', VERSION, (('main_dimensions',), result('hull_variation', 'sections'), result('hydrostatics', 'hull'),
            config('weights'), inputs + ('power', 'value', 'water_density_kg_m3'), config('sources')),
            (('weights',), result('stability', 'weights')), _weights, ('arrangement',)),
        Step('power', VERSION, (result('hydrostatics', 'hull'), ('requirements', 'service_speed'), config('power'), config('sources')),
            (result('resistance', 'holtrop'), result('power', 'propulsion')), _power, ('weights',)),
        Step('engine', VERSION, (result('power', 'propulsion'), config('engine'), config('sources')),
            (result('power', 'engine'),), _engine, ('power',)),
        Step('efficiency', VERSION, (result('power', 'engine'), ('weights',), config('efficiency')),
            (result('fuel', 'eedi'), result('fuel', 'cii')), _efficiency, ('engine',)),
    ]


def run_pipeline(record, cache_dir):
    """Run from one record to one record; cache only content-addressed patches."""
    return run_graph(record, pipeline_steps(), cache_dir)
