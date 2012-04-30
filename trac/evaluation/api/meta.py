
######################################
# Model vars and constants accessors #
######################################

class ModelVariableAccessor(object):

    def __init__(self, model):
        self.model = model

    def __getitem__(self, alias):
        return ModelVariableMetaclass.get_variable(self.model, alias)

    def __contains__(self, alias):
        return ModelVariableMetaclass.has_variable(self.model, alias)

    def all(self):
        return ModelVariableMetaclass.get_all_variables(self.model)


class ModelConstantAccessor(object):

    def __init__(self, model):
        self.model = model
        self._cache = {}
        for c in ModelConstantMetaclass.get_all_constants(model):
            self._cache[c.alias] = c

    def __getitem__(self, alias):
        return self._cache[alias].get()

    def __contains__(self, alias):
        return ModelConstantMetaclass.has_constant(self.model, alias)



########################################
# Model vars and constants metaclasses #
########################################

class ModelItemMetaclass(type):

    # Subclasses MUST define own _registry!
    _registry = None

    def __new__(mcs, name, bases, d):
        new_class = type.__new__(mcs, name, bases, d)
        alias = d.get('alias')
        model_cls = d.get('model_cls')
        if alias and model_cls:
            mcs._registry.setdefault(model_cls,{}).update({alias: new_class})
        return new_class

    @classmethod
    def get_all_items(cls, model):
        classes = (cls._registry.get(model.__class__) or {}).values()
        return [c(model) for c in classes]

    @classmethod
    def get_all_aliases(cls, model):
        return (cls._registry.get(model.__class__) or {}).keys()

    @classmethod
    def get_item(cls, model, alias):
        item_cls = cls._registry[model.__class__][alias]
        return item_cls(model)

    @classmethod
    def has_item(cls, model, alias):
        return alias in cls._registry.get(model.__class__)

class ModelVariableMetaclass(ModelItemMetaclass):

    # per-model "variable_alias: variable_class" registry
    _registry = {}

    def __new__(mcs, name, bases, d):
        conv_to_set = ('subject_support', 'cluster_support', 'time_groupby_support', 'subj_groupby_support')
        for k in conv_to_set:
            if k not in d:
                for base in bases:
                    if hasattr(base, k):
                        break
                else:
                    d[k] = set()
                continue
            val = d[k]
            if isinstance(val, (list, set, tuple, frozenset)):
                d[k] = set(val)
                continue
            # single value
            d[k] = set([val])
        return ModelItemMetaclass.__new__(mcs, name, bases, d)

    @classmethod
    def get_all_variables(cls, model):
        return cls.get_all_items(model)

    @classmethod
    def get_variable(cls, model, alias):
        return cls.get_item(model, alias)

    @classmethod
    def has_variable(cls, model, alias):
        return cls.has_item(model, alias)


class ModelConstantMetaclass(ModelItemMetaclass):

    # per-model "constant_alias: variable_class" registry
    _registry = {}

    @classmethod
    def get_all_constants(cls, model):
        return cls.get_all_items(model)

    @classmethod
    def get_constant(cls, model, alias):
        return cls.get_item(model, alias)

    @classmethod
    def has_constant(cls, model, alias):
        return cls.has_item(model, alias)


