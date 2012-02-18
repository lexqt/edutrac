# -*- coding: utf-8 -*-
#
# Copyright (C)2005-2009 Edgewall Software
# Copyright (C) 2005 Christopher Lenz <cmlenz@gmx.de>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://trac.edgewall.org/wiki/TracLicense.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://trac.edgewall.org/log/.
#
# Author: Christopher Lenz <cmlenz@gmx.de>


class Table(object):
    """Declare a table in a database schema."""

    def __init__(self, name, key=()):
        self.name = name
        self.columns = []
        self.indices = []
        self.key = key
        self.constraints = []
        self.foreignkeys = []
        if isinstance(key, basestring):
            self.key = [key]

    def __getitem__(self, objs):
        self.columns = [o for o in objs if isinstance(o, Column)]
        self.constraints = [o for o in objs if isinstance(o, Constraint)]
        self.foreignkeys = [o for o in objs if isinstance(o, ForeignKey)]
        self.indices = [o for o in objs if isinstance(o, Index)]
        return self


class Column(object):
    """Declare a table column in a database schema."""

    def __init__(self, name, type='text', size=None, key_size=None,
                 auto_increment=False, null=None, unique=False, default=None):
        self.name = name
        self.type = type
        self.size = size
        self.key_size = key_size
        self.auto_increment = auto_increment
        self.null = null
        self.unique = unique
        self.default = default


class Index(object):
    """Declare an index for a database schema."""

    def __init__(self, columns, unique=False):
        self.columns = columns
        self.unique = unique


class Constraint(object):
    """Declare a table constraint for a database schema."""

    def __init__(self, expr=None, name=None):
        self.name = name
        self.expr = expr


class ForeignKey(Constraint):
    """Declare a foreign key table constraint for a database schema."""

    def __init__(self, columns, ref_table, ref_columns=(), on_delete=None):
        self.columns     = columns
        self.ref_table   = ref_table
        self.ref_columns = ref_columns
        self.on_delete   = on_delete
        if isinstance(columns, basestring):
            self.columns = [columns]
        if isinstance(ref_columns, basestring):
            self.ref_columns = [ref_columns]
        super(ForeignKey, self).__init__()
