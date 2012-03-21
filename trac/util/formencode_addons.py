import formencode



class EqualSet(formencode.FancyValidator):

    equal_to_set = set()

    messages = {
        'not_equal': 'Set is not equal to: %(set_)s',
    }

    def validate_python(self, value, state):
        if set(value) != self.equal_to_set:
            raise formencode.Invalid(self.message('not_equal', state, set_=self.equal_to_set), value, state)


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
