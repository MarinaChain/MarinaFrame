"""Loss-aware conversion of independent module fragments to tagged evidence."""
from copy import deepcopy

from ..design_record import quantity, restore_result

META = dict(method='explicit design-loop input', method_version='1', sources=['input:design-loop'])

# Unit inference is confined to the established SI field conventions. Module
# quantities take precedence. Coefficients remain dimensionless inputs.
FIELD_UNITS = {'x_m': 'm', 'z_m': 'm', 'half_breadths_m': 'm', 'parallel_body_m': 'm',
    'component_cg_m': 'm', 'component_relative_bands': '1', 'distance_nm': 'nm',
    'water_density_kg_m3': 'kg/m3', 'kinematic_viscosity_m2_s': 'm2/s',
    'density_t_per_m3': 't/m3', 'displacement_t': 't', 'lcb_percent_lwl_forward': '%',
    'operating_sfoc': 'g/kWh', 'main_engine_mass_t': 't', 'sfoc_rating_rpm': 'rpm', 'rpm': 'rpm'}


def field_unit(name, fallback):
    if name in FIELD_UNITS:
        return FIELD_UNITS[name]
    for suffix, unit in (('_m3', 'm3'), ('_m2', 'm2'), ('_m', 'm'), ('_kw', 'kW'),
                         ('_n', 'N'), ('_kn', 'kn'), ('_ms', 'm/s'), ('_g_kwh', 'g/kWh'), ('_t', 't')):
        if name.endswith(suffix):
            return unit
    return fallback


def canonical_quantity(fragment):
    result = {key: deepcopy(fragment[key]) for key in
              ('value', 'unit', 'method', 'method_version', 'sources', 'status')}
    uncertainty = fragment.get('uncertainty')
    reason = fragment.get('uncertainty_reason')
    if uncertainty and uncertainty.get('kind') == 'absolute_band':
        value = fragment['value']
        uncertainty = dict(kind='absolute', lower=value - uncertainty['lower'],
                           upper=uncertainty['upper'] - value, basis=uncertainty['basis'])
    elif uncertainty and 'absolute_band' in uncertainty:
        band = uncertainty['absolute_band']
        uncertainty = dict(kind='absolute', lower=band, upper=band, basis=uncertainty['basis'])
    elif uncertainty and 'reason' in uncertainty:
        reason, uncertainty = uncertainty['reason'], None
    result.update(uncertainty=uncertainty, uncertainty_reason=None if uncertainty else reason)
    if result['uncertainty'] is None and not result['uncertainty_reason']:
        raise ValueError('Quantity has no uncertainty or reason')
    return result


def fragment_evidence(value, *, unit='1', metadata=None):
    """Keep module metadata, including vector quantities and explicit missing data."""
    metadata = metadata or META
    if isinstance(value, dict) and {'value', 'unit', 'method', 'method_version', 'sources', 'status'} <= value.keys():
        raw = value['value']
        if raw is None:
            # A missing quantity cannot fit the scalar schema. Keep its full
            # metadata as evidence rather than invent a zero or lose its unit.
            return {'kind': 'object', 'value': {key: fragment_evidence(child) for key, child in value.items()}}
        if isinstance(raw, list):
            return {'kind': 'list', 'value': [fragment_evidence({**value, 'value': child}) for child in raw]}
        if isinstance(raw, dict):
            inherited = {key: value[key] for key in ('method', 'method_version', 'sources')}
            return fragment_evidence(raw, unit=value['unit'], metadata=inherited)
        return {'kind': 'quantity', 'value': canonical_quantity(value)}
    if value is None:
        return {'kind': 'missing', 'value': None}
    if isinstance(value, bool):
        return {'kind': 'flag', 'value': value}
    if isinstance(value, str):
        return {'kind': 'text', 'value': value}
    if isinstance(value, (int, float)):
        return {'kind': 'quantity', 'value': quantity(value, unit, **metadata)}
    if isinstance(value, (list, tuple)):
        return {'kind': 'list', 'value': [fragment_evidence(child, unit=unit, metadata=metadata) for child in value]}
    if isinstance(value, dict):
        fields = {}
        table_units = {'vertices': ('rpm', 'kW'), 'sfoc_by_load': ('1', 'g/kWh'), 'fuel_t': ('1', 't')}
        for key, child in value.items():
            if key in table_units:
                rows = []
                for row in child:
                    if len(row) != 2:
                        raise ValueError(f'{key} requires two-column rows')
                    rows.append({'kind': 'list', 'value': [fragment_evidence(cell, unit=cell_unit, metadata=metadata)
                        for cell, cell_unit in zip(row, table_units[key])]})
                fields[key] = {'kind': 'list', 'value': rows}
            else:
                fields[key] = fragment_evidence(child, unit=field_unit(key, unit), metadata=metadata)
        return {'kind': 'object', 'value': fields}
    raise ValueError(f'Unsupported fragment type: {type(value).__name__}')


def read_evidence(data, section, name):
    return restore_result(data['results'][section][name])
