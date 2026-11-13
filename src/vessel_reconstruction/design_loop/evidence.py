"""Loss-aware conversion of independent module fragments to tagged evidence."""
from copy import deepcopy

from ..design_record import quantity, restore_result

META = dict(method='explicit design-loop input', method_version='1', sources=['input:design-loop'])


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
        if isinstance(raw, (list, dict)):
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
        return {'kind': 'object', 'value': {key: fragment_evidence(child, unit=unit, metadata=metadata) for key, child in value.items()}}
    raise ValueError(f'Unsupported fragment type: {type(value).__name__}')


def read_evidence(data, section, name):
    return restore_result(data['results'][section][name])
