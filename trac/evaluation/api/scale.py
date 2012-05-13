from trac.util.translation import _

import formencode
from formencode import validators
from trac.util.formencode_addons import BoolInt


__all__ = ['Scale', 'NominalScale', 'BooleanScale',
           'OrdinalScale', 'IntervalScale', 'RatioScale',
           'UnityScale', 'PercentScale']

class Scale(object):

    def __init__(self, type):
        self.type_ = type

    def get(self, value):
        if value is None:
            return self._get_none()
        value = self.type_(value)
        value = self._get(value)
        return value

    @property
    def type(self):
        return self.type_

    def _get(self, value):
        return value

    def _get_none(self):
        '''Return some value if original is None'''
        return self.type_()

class NominalScale(Scale):

    terms = None

    def __init__(self, terms, type=lambda x: x):
        self.terms = set(terms)
        super(NominalScale, self).__init__(type)

    def _get(self, value):
        if value not in self.terms:
            raise ValueError
        return value

    def _get_none(self):
        return None

class BooleanScale(NominalScale):

    def __init__(self):
        super(BooleanScale, self).__init__(set([True, False]), bool)

    def _get_none(self):
        return False

class OrdinalScale(NominalScale):

    order = None

    def __init__(self, order, type=lambda x: x):
        super(OrdinalScale, self).__init__(order.keys(), type)
        self.order = order


class IntervalScale(Scale):

    min = None
    max = None

    def __init__(self, type, min=None, max=None):
        super(IntervalScale, self).__init__(type)
        self.min = type(min) if min is not None else None
        self.max = type(max) if max is not None else None

    def _get(self, value):
        if self.min is not None and value < self.min:
            return self.min
        if self.max is not None and value > self.max:
            return self.max
        return value

    def _get_none(self):
        if self.min is not None:
            return self.min
        return super(IntervalScale, self)._get_none()

class RatioScale(IntervalScale):

    def __init__(self, type, max=None):
        super(RatioScale, self).__init__(type, min=0, max=max)

class UnityScale(RatioScale):

    def __init__(self):
        super(UnityScale, self).__init__(float, max=1.0)

class PercentScale(RatioScale):

    def __init__(self, integer=True):
        type_ = int if integer else float
        super(PercentScale, self).__init__(type_, max=100)


# Util functions

def prepare_rendered_value(scale, value):
    '''Prepare `value` with associated `scale` to be rendered.
    Return unicode string'''
    if not scale:
        return unicode(value)
    if isinstance(value, basestring):
        return value

    def is_scale(cls):
        return isinstance(scale, cls)

    # transform scale
    if is_scale(UnityScale):
        # convert to percents
        scale = PercentScale(integer=False)
        value = scale.get(value * 100)

    # convert to string
    if is_scale(PercentScale):
        if scale.type is float:
            value = ('%.2f'%value).rstrip('0').rstrip('.')
        return u'{0}%'.format(value)
    elif is_scale(BooleanScale):
        value = _('Yes') if value else _('No')
        return value

    return unicode(value)

def prepare_editable_var(scale):
    '''Prepare special info dict that may be used to render
    form element to edit variable with specified `scale`'''
    type_ = scale.type
    input_type = 'text'
    help_text  = ''
    info = {}
    def is_scale(cls):
        return isinstance(scale, cls)
    if type_ is bool:
        help_text = _('Yes / No')
        input_type = 'checkbox'
    elif is_scale(IntervalScale) and (
            scale.min is not None or scale.max is not None):
        min_ = scale.min if scale.min is not None else ''
        max_ = scale.max if scale.max is not None else ''
        help_text = u'{0}..{1}'.format(min_, max_)
    elif is_scale(NominalScale) and scale.terms:
        input_type = 'select'
        options = list(scale.terms)
        if is_scale(OrdinalScale):
            options.sort(key=lambda o: scale.order[o])
        info['input_options'] = options
    elif type_ is int:
        help_text = _('Integer number')
    elif type_ is float:
        help_text = _('Float number')
    info.update({
        'input_type': input_type,
        'help_text': help_text,
    })
    return info

def create_scale_validator(scale, params):
    '''Create FormEncode validator for single scaled variable.

    `scale`: variable scale
    `params`: default kw arguments for validator
    '''
    def is_scale(cls):
        return isinstance(scale, cls)
    kwargs = params.copy()
    type_ = scale.type

    if type_ is bool:
        v = BoolInt
    elif is_scale(NominalScale) and scale.terms:
        v = validators.OneOf
        kwargs['list'] = scale.terms
    elif type_ is int:
        v = validators.Int
    elif type_ is float:
        v = validators.Number
    else:
        v = validators.String

    if is_scale(IntervalScale):
        kwargs.update({
            'min': scale.min,
            'max': scale.max,
        })
    v = v(**kwargs)
    return v


class _ScaledVarGroupForm(formencode.Schema):

    allow_extra_fields = True
    filter_extra_fields = True

def create_group_validator(variables, each_params=None):
    '''Create FormEncode validator for group of scaled variables.

    `variables`: dict { <alias>: { 'scale': <Scale>, ... }, ... }
    `each_params`: default kw arguments for each variable validator
    '''
    fields = {}
    params = each_params or {}
    for name, var in variables.iteritems():
        fields[name] = create_scale_validator(var['scale'], params)

    validator = _ScaledVarGroupForm(**fields)
    return validator

