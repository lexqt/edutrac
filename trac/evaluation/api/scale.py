

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
    if not scale:
        return unicode(value)
    if isinstance(value, basestring):
        return value

    def is_scale(cls):
        return isinstance(scale, cls)

    if is_scale(UnityScale):
        # convert to percents
        scale = PercentScale(integer=False)
        value = scale.get(value * 100)

    if is_scale(PercentScale):
        if scale.type is float:
            value = ('%.2f'%value).rstrip('0').rstrip('.')
        return u'{0}%'.format(value)

    return unicode(value)
