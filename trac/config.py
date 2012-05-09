# -*- coding: utf-8 -*-
#
# Copyright (C) 2005-2009 Edgewall Software
# Copyright (C) 2005-2007 Christopher Lenz <cmlenz@gmx.de>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://trac.edgewall.org/wiki/TracLicense.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://trac.edgewall.org/log/.

from ConfigParser import ConfigParser
from copy import deepcopy
import os.path
import threading

from trac.admin import AdminCommandError, IAdminCommandProvider
from trac.core import *
from trac.util import AtomicFile, as_bool
from trac.util.compat import any
from trac.util.text import printout, to_unicode, CRLF
from trac.util.translation import _, N_

__all__ = ['Configuration', 'Option', 'BoolOption', 'IntOption', 'FloatOption',
           'ListOption', 'ChoiceOption', 'PathOption', 'ExtensionOption',
           'SyllabusExtensionPoint', 'OrderedExtensionsOption', 'ConfigurationError',
           'ComponentDisabled']

# Retained for backward-compatibility, use as_bool() instead
_TRUE_VALUES = ('yes', 'true', 'enabled', 'on', 'aye', '1', 1, True)

_use_default = object()

def _to_utf8(basestr):
    return to_unicode(basestr).encode('utf-8')


class ConfigurationError(TracError):
    """Exception raised when a value in the configuration file is not valid."""
    title = N_('Configuration Error')


class ComponentDisabled(Exception):
    """Exception to indicate that component is disabled by config"""


class Configuration(object):
    """Thin layer over `ConfigParser` from the Python standard library.

    In addition to providing some convenience methods, the class remembers
    the last modification time of the configuration file, and reparses it
    when the file has changed.
    """

    _lock = threading.Lock()
    _instances = {}

    def __new__(cls, filename, *args, **kwargs):
        with cls._lock:
            is_new = filename not in cls._instances
            if is_new:
                cls._instances[filename] = super(Configuration, cls).__new__(cls, filename, *args, **kwargs)
            conf = cls._instances[filename]
        if not is_new:
            conf.parse_if_needed() # TODO: is it necessary to check?
        return conf

    def __init__(self, filename):
        self.filename = filename
        self.parser = ConfigParser()
        self._old_sections = {}
        self.parents = []
        self._lastmtime = 0
        self._sections = {}
        self.parse_if_needed(force=True)

    def __contains__(self, name):
        """Return whether the configuration contains a section of the given
        name.
        """
        return name in self.sections()

    def __getitem__(self, name):
        """Return the configuration section with the specified name."""
        if name not in self._sections:
            self._sections[name] = Section(self, name)
        return self._sections[name]

    def __repr__(self):
        return '<%s %r>' % (self.__class__.__name__, self.filename)

    def get(self, section, key, default=''):
        """Return the value of the specified option.
        
        Valid default input is a string. Returns a string.
        """
        return self[section].get(key, default)

    def getbool(self, section, key, default=''):
        """Return the specified option as boolean value.
        
        If the value of the option is one of "yes", "true", "enabled", "on",
        or "1", this method wll return `True`, otherwise `False`.
        
        Valid default input is a string or a bool. Returns a bool.
        
        (since Trac 0.9.3, "enabled" added in 0.11)
        """
        return self[section].getbool(key, default)

    def getint(self, section, key, default=''):
        """Return the value of the specified option as integer.
        
        If the specified option can not be converted to an integer, a
        `ConfigurationError` exception is raised.
        
        Valid default input is a string or an int. Returns an int.
        
        (since Trac 0.10)
        """
        return self[section].getint(key, default)

    def getfloat(self, section, key, default=''):
        """Return the value of the specified option as float.
        
        If the specified option can not be converted to a float, a
        `ConfigurationError` exception is raised.
        
        Valid default input is a string, float or int. Returns a float.
        
        (since Trac 0.12)
        """
        return self[section].getfloat(key, default)

    def getlist(self, section, key, default='', sep=',', keep_empty=False):
        """Return a list of values that have been specified as a single
        comma-separated option.
        
        A different separator can be specified using the `sep` parameter. If
        the `keep_empty` parameter is set to `True`, empty elements are
        included in the list.
        
        Valid default input is a string or a list. Returns a string.
        
        (since Trac 0.10)
        """
        return self[section].getlist(key, default, sep, keep_empty)

    def getpath(self, section, key, default=''):
        """Return a configuration value as an absolute path.
        
        Relative paths are resolved relative to the location of this
        configuration file.
        
        Valid default input is a string. Returns a normalized path.

        (enabled since Trac 0.11.5)
        """
        return self[section].getpath(key, default)

    def set(self, section, key, value):
        """Change a configuration value.
        
        These changes are not persistent unless saved with `save()`.
        """
        self[section].set(key, value)

    def defaults(self, compmgr=None, only_switcher=False):
        """Returns a dictionary of the default configuration values
        (''since 0.10'').
        
        If `compmgr` is specified, return only options declared in components
        that are enabled in the given `ComponentManager`.
        If `only_switcher` is True, return only options with switchers.
        """
        defaults = {}
        for (section, key), option in Option.get_registry(compmgr).items():
            if only_switcher and not option.switcher:
                continue
            defaults.setdefault(section, {})[key] = option.default
        return defaults

    def options(self, section, compmgr=None, inherit=True):
        """Return a list of `(name, value)` tuples for every option in the
        specified section.
        
        This includes options that have default values that haven't been
        overridden. If `compmgr` is specified, only return default option
        values for components that are enabled in the given `ComponentManager`.
        If `inherit` is True, include options inherited from parents.
        """
        return self[section].options(compmgr, inherit=inherit)

    def remove(self, section, key):
        """Remove the specified option."""
        self[section].remove(key)

    def sections(self, compmgr=None, defaults=True, inherit=True):
        """Return a list of section names.
        
        If `compmgr` is specified, only the section names corresponding to
        options declared in components that are enabled in the given
        `ComponentManager` are returned.
        If `inherit` is True, include sections inherited from parents.
        """
        sections = set([to_unicode(s) for s in self.parser.sections()])
        if inherit:
            for parent in self.parents:
                sections.update(parent.sections(compmgr, defaults=False))
        if defaults:
            sections.update(self.defaults(compmgr))
        return sorted(sections)

    def has_option(self, section, option, defaults=True):
        """Returns True if option exists in section in either the project
        trac.ini or one of the parents, or is available through the Option
        registry.
        
        (since Trac 0.11)
        """
        section_str = _to_utf8(section)
        if self.parser.has_section(section_str):
            if _to_utf8(option) in self.parser.options(section_str):
                return True
        for parent in self.parents:
            if parent.has_option(section, option, defaults=False):
                return True
        return defaults and (section, option) in Option.registry

    def save(self):
        """Write the configuration options to the primary file."""
        if not self.filename:
            return

        # Only save options that differ from the defaults
        sections = []
        for section in self.sections():
            section_str = _to_utf8(section)
            options = []
            for option in self[section]:
                default_str = None
                for parent in self.parents:
                    if parent.has_option(section, option, defaults=False):
                        default_str = _to_utf8(parent.get(section, option))
                        break
                option_str = _to_utf8(option)
                current_str = False
                if self.parser.has_option(section_str, option_str):
                    current_str = self.parser.get(section_str, option_str)
                if current_str is not False and current_str != default_str:
                    options.append((option_str, current_str))
            if options:
                sections.append((section_str, sorted(options)))

        # At this point, all the strings in `sections` are UTF-8 encoded `str`
        try:
            fileobj = AtomicFile(self.filename, 'w')
            try:
                fileobj.write('# -*- coding: utf-8 -*-\n\n')
                for section, options in sections:
                    fileobj.write('[%s]\n' % section)
                    for key_str, val_str in options:
                        if to_unicode(key_str) in self[section].overridden:
                            fileobj.write('# %s = <inherited>\n' % key_str)
                        else:
                            val_str = val_str.replace(CRLF, '\n') \
                                             .replace('\n', '\n ')
                            fileobj.write('%s = %s\n' % (key_str, val_str))
                    fileobj.write('\n')
            finally:
                fileobj.close()
            self._old_sections = deepcopy(self.parser._sections)
        except Exception:
            # Revert all changes to avoid inconsistencies
            self.parser._sections = deepcopy(self._old_sections)
            raise

    def parse_if_needed(self, force=False):
        if not self.filename or not os.path.isfile(self.filename):
            return False

        changed = False
        modtime = os.path.getmtime(self.filename)
        if force or modtime > self._lastmtime:
            self._sections = {}
            self.parser._sections = {}
            if not self.parser.read(self.filename):
                raise TracError(_("Error reading '%(file)s', make sure it is "
                                  "readable.", file=self.filename))
            self._lastmtime = modtime
            self._old_sections = deepcopy(self.parser._sections)
            changed = True
        
        if changed:
            self.parents = []
            if self.parser.has_option('inherit', 'file'):
                for filename in self.parser.get('inherit', 'file').split(','):
                    filename = to_unicode(filename.strip())
                    if not os.path.isabs(filename):
                        filename = os.path.join(os.path.dirname(self.filename),
                                                filename)
                    self.parents.append(Configuration(filename))
        else:
            for parent in self.parents:
                changed |= parent.parse_if_needed(force=force)
        
        if changed:
            self._cache = {}
        return changed

    def touch(self):
        if self.filename and os.path.isfile(self.filename) \
           and os.access(self.filename, os.W_OK):
            os.utime(self.filename, None)

    def set_defaults(self, compmgr=None, only_switcher=False):
        """Retrieve all default values and store them explicitly in the
        configuration, so that they can be saved to file.
        
        Values already set in the configuration are not overridden.
        """
        for section, default_options in self.defaults(compmgr, only_switcher).items():
            for name, value in default_options.items():
                if not self.parser.has_option(_to_utf8(section),
                                              _to_utf8(name)):
                    if any(parent[section].contains(name, defaults=False)
                           for parent in self.parents):
                        value = None
                    self.set(section, name, value)


class Section(object):
    """Proxy for a specific configuration section.
    
    Objects of this class should not be instantiated directly.
    """
    __slots__ = ['config', 'name', 'overridden', '_cache']

    def __init__(self, config, name):
        self.config = config
        self.name = name
        self.overridden = {}
        self._cache = {}

    def contains(self, key, defaults=True):
        if self.config.parser.has_option(_to_utf8(self.name), _to_utf8(key)):
            return True
        for parent in self.config.parents:
            if parent[self.name].contains(key, defaults=False):
                return True
        return defaults and Option.registry.has_key((self.name, key))
    
    __contains__ = contains

    def iterate(self, compmgr=None, defaults=True, inherit=True):
        """Iterate over the options in this section.
        
        If `compmgr` is specified, only return default option values for
        components that are enabled in the given `ComponentManager`.
        If `inherit` is True, iterate through parents too.
        """
        options = set()
        name_str = _to_utf8(self.name)
        if self.config.parser.has_section(name_str):
            for option_str in self.config.parser.options(name_str):
                option = to_unicode(option_str)
                options.add(option.lower())
                yield option
        if inherit:
            for parent in self.config.parents:
                for option in parent[self.name].iterate(defaults=False):
                    loption = option.lower()
                    if loption not in options:
                        options.add(loption)
                        yield option
        if defaults:
            for section, option in Option.get_registry(compmgr).keys():
                if section == self.name and option.lower() not in options:
                    yield option

    __iter__ = iterate
    
    def __repr__(self):
        return '<Section [%s]>' % (self.name)

    def get(self, key, default=''):
        """Return the value of the specified option.
        
        Valid default input is a string. Returns a string.
        """
        cached = self._cache.get(key, _use_default)
        if cached is not _use_default:
            return cached
        name_str = _to_utf8(self.name)
        key_str = _to_utf8(key)
        if self.config.parser.has_option(name_str, key_str):
            value = self.config.parser.get(name_str, key_str)
        else:
            for parent in self.config.parents:
                value = parent[self.name].get(key, _use_default)
                if value is not _use_default:
                    break
            else:
                if default is not _use_default:
                    option = Option.registry.get((self.name, key))
                    value = option and option.default or _use_default
                else:
                    value = _use_default
        if value is _use_default:
            return default
        if not value:
            value = u''
        elif isinstance(value, basestring):
            value = to_unicode(value)
        self._cache[key] = value
        return value

    def getbool(self, key, default=''):
        """Return the value of the specified option as boolean.
        
        This method returns `True` if the option value is one of "yes", "true",
        "enabled", "on", or non-zero numbers, ignoring case. Otherwise `False`
        is returned.

        Valid default input is a string or a bool. Returns a bool.
        """
        return as_bool(self.get(key, default))

    def getint(self, key, default=''):
        """Return the value of the specified option as integer.
        
        If the specified option can not be converted to an integer, a
        `ConfigurationError` exception is raised.
        
        Valid default input is a string or an int. Returns an int.
        """
        value = self.get(key, default)
        if not value:
            return 0
        try:
            return int(value)
        except ValueError:
            raise ConfigurationError(
                    _('[%(section)s] %(entry)s: expected integer, got %(value)s',
                      section=self.name, entry=key, value=repr(value)))

    def getfloat(self, key, default=''):
        """Return the value of the specified option as float.
        
        If the specified option can not be converted to a float, a
        `ConfigurationError` exception is raised.
        
        Valid default input is a string, float or int. Returns a float.
        """
        value = self.get(key, default)
        if not value:
            return 0.0
        try:
            return float(value)
        except ValueError:
            raise ConfigurationError(
                    _('[%(section)s] %(entry)s: expected float, got %(value)s',
                      section=self.name, entry=key, value=repr(value)))

    def getlist(self, key, default='', sep=',', keep_empty=True):
        """Return a list of values that have been specified as a single
        comma-separated option.
        
        A different separator can be specified using the `sep` parameter. If
        the `keep_empty` parameter is set to `False`, empty elements are omitted
        from the list.
        
        Valid default input is a string or a list. Returns a list.
        """
        value = self.get(key, default)
        if not value:
            return []
        if isinstance(value, basestring):
            items = [item.strip() for item in value.split(sep)]
        else:
            items = list(value)
        if not keep_empty:
            items = filter(None, items)
        return items

    def getpath(self, key, default=''):
        """Return the value of the specified option as a path, relative to
        the location of this configuration file.

        Valid default input is a string. Returns a normalized path.
        """
        path = self.get(key, default)
        if not path:
            return default
        if not os.path.isabs(path):
            path = os.path.join(os.path.dirname(self.config.filename), path)
        return os.path.normcase(os.path.realpath(path))

    def options(self, compmgr=None, inherit=True):
        """Return `(key, value)` tuples for every option in the section.
        
        This includes options that have default values that haven't been
        overridden. If `compmgr` is specified, only return default option
        values for components that are enabled in the given `ComponentManager`.
        If `inherit` is True, include options inherited from parents.
        """
        for key in self.iterate(compmgr, inherit=inherit):
            yield key, self.get(key)

    def set(self, key, value):
        """Change a configuration value.
        
        These changes are not persistent unless saved with `save()`.
        """
        self._cache.pop(key, None)
        name_str = _to_utf8(self.name)
        key_str = _to_utf8(key)
        if not self.config.parser.has_section(name_str):
            self.config.parser.add_section(name_str)
        if value is None:
            self.overridden[key] = True
            value_str = ''
        else:
            value_str = _to_utf8(value)
        return self.config.parser.set(name_str, key_str, value_str)

    def remove(self, key):
        """Delete a key from this section.

        Like for `set()`, the changes won't persist until `save()` gets called.
        """
        name_str = _to_utf8(self.name)
        if self.config.parser.has_section(name_str):
            self._cache.pop(key, None)
            self.config.parser.remove_option(_to_utf8(self.name), _to_utf8(key))


class ConfigurationSwitcher(object):

    def __init__(self, env):
        self._switch_lock = threading.Lock()
        self.env = env
        self.common_config = env.config

    def common(self):
        return self.common_config

    def syllabus(self, id):
        return self.switch(syllabus=id)

    def project(self, id):
        return self.switch(project=id)

    # TODO: Add something like filename provider for syllabus and project
    # config files. Having env object, we could get this info even from DB
    # (but not in __init__ - DB is not inited at that moment).
    # Also such provider should dynamically link project, syllabuses and
    # common config without hardcoding [inherit] section.
    def switch(self, syllabus=None, project=None):
        if project is not None:
            key = 'project'
            id = project
        elif syllabus is not None:
            key = 'syllabus'
            id = syllabus
        else:
            raise AttributeError
        with self._switch_lock:
            if id not in self.env.conf_switcher_cache[key]:
                c = self.common()
                filename = os.path.join(os.path.dirname(c.filename), key, 'id{0}.ini'.format(id))
                self.env.conf_switcher_cache[key][id] = Configuration(filename)
            return self.env.conf_switcher_cache[key][id]

class AccessorSwitcher(object):

    def __init__(self, env, accessor_func, section, option, default):
        self.env = env
        self.accessor_func = accessor_func
        self.section = section
        self.option = option
        self.default = default

    def common(self):
        section = self.env.config[self.section]
        return self._get(section)

    def syllabus(self, id):
        section = self.env.configs.syllabus(id)[self.section]
        return self._get(section)

    def project(self, id):
        section = self.env.configs.project(id)[self.section]
        return self._get(section)

    def _get(self, section):
        return self.accessor_func(section, self.option, self.default)


class Option(object):
    """Descriptor for configuration options on `Configurable` subclasses."""

    registry = {}
    accessor = Section.get

    @staticmethod
    def get_registry(compmgr=None):
        """Return the option registry, as a `dict` mapping `(section, key)`
        tuples to `Option` objects.
        
        If `compmgr` is specified, only return options for components that are
        enabled in the given `ComponentManager`.
        """
        if compmgr is None:
            return Option.registry
        
        from trac.core import ComponentMeta
        components = {}
        for cls in ComponentMeta._components:
            for attr in cls.__dict__.itervalues():
                if isinstance(attr, Option):
                    components[attr] = cls
        
        return dict(each for each in Option.registry.items()
                    if each[1] not in components
                       or compmgr.is_enabled(components[each[1]]))
    
    def __init__(self, section, name, default=None, doc='', switcher=False):
        """Create the configuration option.
        
        @param section: the name of the configuration section this option
            belongs to
        @param name: the name of the option
        @param default: the default value for the option
        @param doc: documentation of the option
        """
        self.section = section
        self.name = name
        self.default = default
        self.registry[(self.section, self.name)] = self
        self.__doc__ = doc
        self.switcher = switcher

    def __get__(self, instance, owner):
        if instance is None:
            return self
        config = getattr(instance, 'config', None)
        if config and isinstance(config, Configuration):
            section = config[self.section]
            if not self.switcher:
                value = self.accessor(section, self.name, self.default)
            else:
                env = getattr(instance, 'env', None)
                value = AccessorSwitcher(env, self.accessor, self.section, self.name, self.default)
            return value
        return None

    def __set__(self, instance, value):
        raise AttributeError, 'can\'t set attribute'

    def __repr__(self):
        return '<%s [%s] "%s">' % (self.__class__.__name__, self.section,
                                   self.name)


class BoolOption(Option):
    """Descriptor for boolean configuration options."""
    accessor = Section.getbool


class IntOption(Option):
    """Descriptor for integer configuration options."""
    accessor = Section.getint


class FloatOption(Option):
    """Descriptor for float configuration options."""
    accessor = Section.getfloat


class ListOption(Option):
    """Descriptor for configuration options that contain multiple values
    separated by a specific character.
    """

    def __init__(self, section, name, default=None, sep=',', keep_empty=False,
                 doc='', **kwargs):
        Option.__init__(self, section, name, default, doc, **kwargs)
        self.sep = sep
        self.keep_empty = keep_empty

    def accessor(self, section, name, default):
        return section.getlist(name, default, self.sep, self.keep_empty)


class ChoiceOption(Option):
    """Descriptor for configuration options providing a choice among a list
    of items.
    
    The default value is the first choice in the list.
    """
    
    def __init__(self, section, name, choices, doc='', **kwargs):
        Option.__init__(self, section, name, _to_utf8(choices[0]), doc, **kwargs)
        self.choices = set(_to_utf8(choice).strip() for choice in choices)

    def accessor(self, section, name, default):
        value = section.get(name, default)
        if value not in self.choices:
            raise ConfigurationError(
                    _('[%(section)s] %(entry)s: expected one of '
                      '(%(choices)s), got %(value)s',
                      section=section.name, entry=name, value=repr(value),
                      choices=', '.join('"%s"' % c
                                        for c in sorted(self.choices))))
        return value
            
    
class PathOption(Option):
    """Descriptor for file system path configuration options."""
    accessor = Section.getpath


class SyllabusExtensionPoint(ExtensionPoint):

    _cache = {}

    def extensions(self, component):
        idx = self.interface
        # per-interface cache
        if idx not in self._cache:
            self._cache[idx] = {}
        stor = self._cache[idx]

        check = component.compmgr.is_component_enabled
        extensions = super(SyllabusExtensionPoint, self).extensions(component)

        def get_syllabus_extensions(syllabus=None):
            if syllabus is None:
                return extensions
            syllabus_id = int(syllabus)
            # per-syllabus cache
            if syllabus_id not in stor:
                exts = filter(lambda e: check(e.__class__, syllabus=syllabus_id), extensions)
                stor[syllabus_id] = exts
            return stor[syllabus_id]

        return get_syllabus_extensions

class ExtensionOption(Option):

    def __init__(self, section, name, interface, default=None, doc='', syllabus_switcher=False):
        Option.__init__(self, section, name, default, doc, switcher=syllabus_switcher)
        EPClass = SyllabusExtensionPoint if syllabus_switcher else ExtensionPoint
        self.xtnpt = EPClass(interface)

    def __get__(self, instance, owner):
        if instance is None:
            return self
        value = Option.__get__(self, instance, owner)
        if self.switcher:
            def get_syllabus_component(syllabus_id):
                if syllabus_id is None:
                    v = value.common()
                else:
                    v = value.syllabus(syllabus_id)
                return self._get_component(instance, v, syllabus_id)
            return get_syllabus_component
        else:
            return self._get_component(instance, value)

    def _get_component(self, component, value, syllabus=None):
        exts = self.xtnpt.extensions(component)
        if syllabus is not None:
            exts = exts(syllabus)
        for impl in exts:
            if impl.__class__.__name__ == value:
                return impl
        raise AttributeError('Cannot find an implementation of the "%s" '
                             'interface named "%s".  Please update the option '
                             '%s.%s in configuration file.'
                             % (self.xtnpt.interface.__name__, value,
                                self.section, self.name))

class OrderedExtensionsOption(ListOption):
    """A comma separated, ordered, list of components implementing `interface`.
    Can be empty.

    If `include_missing` is true (the default) all components implementing the
    interface are returned, with those specified by the option ordered first.
    `always_first` is None or list of component names that will be prepended
    to the ordered list from config. So these components will always be first.
    """

    def __init__(self, section, name, interface, default=None,
                 include_missing=True, doc='', syllabus_switcher=False,
                 always_first=None):
        ListOption.__init__(self, section, name, default, doc=doc, switcher=syllabus_switcher)
        EPClass = SyllabusExtensionPoint if syllabus_switcher else ExtensionPoint
        self.xtnpt = EPClass(interface)
        self.include_missing = include_missing
        self.always_first = always_first

    def __get__(self, instance, owner):
        if instance is None:
            return self
        order = ListOption.__get__(self, instance, owner)
        if self.switcher:
            def get_syllabus_components(syllabus_id):
                if syllabus_id is None:
                    o = order.common()
                else:
                    o = order.syllabus(syllabus_id)
                return self._get_components(instance, o, syllabus_id)
            return get_syllabus_components
        else:
            return self._get_components(instance, order)

    def _get_components(self, component, order, syllabus=None):
        components = []
        if self.always_first:
            order = self.always_first + order
        exts = self.xtnpt.extensions(component)
        if syllabus is not None:
            exts = exts(syllabus)
        for impl in exts:
            if self.include_missing or impl.__class__.__name__ in order:
                components.append(impl)

        other_num = len(order)
        def key(comp):
            name = comp.__class__.__name__
            if name in order:
                return order.index(name)
            else:
                return other_num
        components.sort(key=key)

        return components


class ConfigurationAdmin(Component):
    """trac-admin command provider for trac.ini administration."""
    
    implements(IAdminCommandProvider)
    
    # IAdminCommandProvider methods
    
    def get_admin_commands(self):
        yield ('config get', '<section> <option>',
               'Get the value of the given option in "trac.ini"',
               self._complete_config, self._do_get)
        yield ('config remove', '<section> <option>',
               'Remove the specified option from "trac.ini"',
               self._complete_config, self._do_remove)
        yield ('config set', '<section> <option> <value>',
               'Set the value for the given option in "trac.ini"',
               self._complete_config, self._do_set)

    def _complete_config(self, args):
        if len(args) == 1:
            return self.config.sections()
        elif len(args) == 2:
            return [name for (name, value) in self.config[args[0]].options()]

    def _do_get(self, section, option):
        if not self.config.has_option(section, option):
            raise AdminCommandError(
                _("Option '%(option)s' doesn't exist in section '%(section)s'",
                  option=option, section=section))
        printout(self.config.get(section, option))

    def _do_set(self, section, option, value):
        self.config.set(section, option, value)
        self.config.save()
        if section == 'inherit' and option == 'file':
            self.config.parse_if_needed(force=True) # Full reload

    def _do_remove(self, section, option):
        if not self.config.has_option(section, option):
            raise AdminCommandError(
                _("Option '%(option)s' doesn't exist in section '%(section)s'",
                  option=option, section=section))
        self.config.remove(section, option)
        self.config.save()
        if section == 'inherit' and option == 'file':
            self.config.parse_if_needed(force=True) # Full reload
