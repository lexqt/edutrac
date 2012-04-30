import formencode
from formencode import validators
from trac.util.translation import _

class State(object):
    '''Simple class for validator state object
    with trac translation support'''

    def __new__(cls, state, set_gettext=True):
        if state is None:
            state = super(State, cls).__new__(cls)
        if set_gettext:
            state._ = _
        return state

class EqualSet(formencode.FancyValidator):

    equal_to_set = set()

    messages = {
        'not_equal': 'Set is not equal to: %(set_)s',
    }

    def validate_python(self, value, state):
        if set(value) != self.equal_to_set:
            raise formencode.Invalid(self.message('not_equal', state, set_=self.equal_to_set), value, state)

# Validator to handle 0 and 1 integer values as boolean
class BoolInt(validators.Bool):

    def _to_python(self, value, state):
        try:
            return bool(int(value))
        except ValueError:
            return False

    def _from_python(self, value, state):
        return int(bool(value))

# monkey patch (TODO: fix i18n support) - fix OneOf validator error message
# use %(value)s instead of %(value)r to handle unicode normally
validators.OneOf._messages['notIn'] = _('Value must be one of: %(items)s (not %(value)s)')


def make_plain_errors_list(errs, labels={}):
    if errs is None:
        return []
    if isinstance(errs, basestring):
        return [errs]
    def process_list(errs):
        errs_list = []
        for err in errs:
            errs_list.extend(make_plain_errors_list(err, labels))
        return errs_list
    def process_dict(errs):
        errs_list = []
        for k, v in errs.iteritems():
            if isinstance(v, basestring):
                if k in labels:
                    k = labels[k]
                errs_list.append(u'"{0}": {1}'.format(k, v))
            else:
                errs_list.extend(make_plain_errors_list(v, labels))
        return errs_list
    if isinstance(errs, list):
        return process_list(errs)
    if isinstance(errs, dict):
        return process_dict(errs)
