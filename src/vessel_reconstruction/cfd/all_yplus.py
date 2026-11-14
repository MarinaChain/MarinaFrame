"""Frozen DB3 wall treatment and fixed-before-run force stopping rule."""
import math
import re


def all_yplus_field(text, field):
    values = {
        'nut': 'type nutUSpaldingWallFunction; value uniform 0;',
        'k': 'type kqRWallFunction; value uniform 0.00016443135;',
        'omega': 'type omegaWallFunction; blending binomial; n 2; value uniform 0.06061985822110283;',
    }
    if field not in values:
        raise ValueError('Expected nut, k or omega')
    updated, count = re.subn(r'\bhull\s*\{[^{}]*\}', 'hull { '+values[field]+' }', text)
    if count != 1:
        raise ValueError('Expected exactly one hull boundary dictionary')
    return updated


def convergence_stop(forces):
    """Decide only at100-step boundaries; no favourable sliding windows."""
    if any(not math.isfinite(v) for v in forces):
        raise ValueError('Finite forces required')
    count = len(forces)
    if count < 500 or count % 100:
        return {'stop': False, 'drifts': []}
    means = [sum(forces[i:i+100])/100 for i in range(count-400, count, 100)]
    drifts = [abs(b-a)/abs(a) if a else math.inf for a,b in zip(means,means[1:])]
    return {'stop': all(v < .001 for v in drifts) or count >= 2000,
            'converged': all(v < .001 for v in drifts), 'drifts': drifts}
