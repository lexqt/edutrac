from trac.util.translation import _
from trac.evaluation.api.error import EvalModelError

def get_enum_equivalents(model, type_, values):
    '''Transform `values` list of `type_` enum items
    to the list of enum numeric equivalents using
    specified evaluation `model`.
    '''
    return map(lambda v: model.get_enum_value(type_, v), values)

def revert_enum(model, type_, value):
    '''Revert numeric equivalent of `type_` enum item
    back to original enum value.
    If there is no exact match, round `value` to the closest
    having equivalent.'''
    m = model.ENUM_MAP
    if type_ not in m:
        raise EvalModelError(_('There is no mapping for %(type_)s values',
                               type_=type_))
    m  = m[type_]
    mr = {v: k for (k, v) in m.iteritems() if k != '*'}
    if value in mr:
        return mr[value]
    vals = sorted(mr.keys())
    if not vals:
        raise EvalModelError(_('No equivalent for enum value found'))
    p = vals[0]
    n = vals[-1]
    for v in vals:
        if v < value:
            p = v
        else:
            break  # first not less
    for v in reversed(vals):
        if v > value:
            n = v
        else:
            break  # first not greater
    if abs(value-p) < abs(value-n):
        return mr[p]
    else:
        return mr[n]

