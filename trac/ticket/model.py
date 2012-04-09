# -*- coding: utf-8 -*-
#
# Copyright (C) 2003-2009 Edgewall Software
# Copyright (C) 2003-2006 Jonas Borgström <jonas@edgewall.com>
# Copyright (C) 2005 Christopher Lenz <cmlenz@gmx.de>
# Copyright (C) 2006 Christian Boos <cboos@neuf.fr>
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
# Author: Jonas Borgström <jonas@edgewall.com>
#         Christopher Lenz <cmlenz@gmx.de>

import re
from datetime import datetime

from trac.attachment import Attachment
from trac.core import TracError
from trac.resource import Resource, ResourceNotFound
from trac.ticket.api import TicketSystem, convert_field_value, convert_type_value, \
                            prepare_field_value
from trac.util import embedded_numbers, partition
from trac.util.datefmt import from_utimestamp, to_utimestamp, utc, utcmax
from trac.util.translation import _

from trac.project.model import Project
from trac.project.api import ProjectManagement

__all__ = ['Ticket', 'Type', 'Status', 'Resolution', 'Priority', 'Severity',
           'Component', 'Milestone', 'Version', 'group_milestones']


def _fixup_cc_list(cc_value):
    """Fix up cc list separators and remove duplicates."""
    cclist = []
    for cc in re.split(r'[;,\s]+', cc_value or ''):
        if cc and cc not in cclist:
            cclist.append(cc)
    return ', '.join(cclist)




class Ticket(object):

    # Fields that must not be modified directly by the user
    protected_fields = ('resolution', 'status', 'time', 'changetime', 'project_id')

    @staticmethod
    def id_is_valid(num):
        return 0 < int(num) <= 1L << 31

    # 0.11 compatibility
    time_created = property(lambda self: self.values.get('time'))
    time_changed = property(lambda self: self.values.get('changetime'))

    def __init__(self, env, tkt_id=None, db=None, version=None, pid=None):
        self.env = env
        if tkt_id is not None:
            tkt_id = int(tkt_id)

        self.values = {}
        self._init_pid(tkt_id, pid)

        self.resource = Resource('ticket', tkt_id, version, pid=self.pid)
        self.resource.need_pid = False

        self.fields = TicketSystem(self.env).get_ticket_fields(self.pid)
        if tkt_id is not None:
            self._fetch_ticket(tkt_id, db)
        else:
            self._init_defaults(db)
            self.id = None
        self._old = {}

    def _init_pid(self, tkt_id=None, pid=None):
        assert pid is not None or tkt_id is not None, 'Insufficient data to init ticket pid'
        if pid is not None:
            pid = int(pid)
            Project.check_exists(self.env, pid)
        elif tkt_id is not None:
            if self.id_is_valid(tkt_id):
                db = self._get_db(None)

                cursor = db.cursor()
                cursor.execute('SELECT project_id FROM ticket WHERE id=%s',
                               (tkt_id,))
            if not cursor.rowcount:
                raise ResourceNotFound(_('Ticket %(id)s does not exist.', 
                                         id=tkt_id), _('Invalid ticket number'))
            pid = cursor.fetchone()[0]
        self.values['project_id'] = unicode(pid)

    def _get_db(self, db):
        return db or self.env.get_read_db()

    @property
    def pid(self):
        if 'project_id' in self.values:
            return int(self.values['project_id'])

    @pid.setter
    def _set_pid(self, pid):
        if pid == self.pid:
            return
        self.values['project_id'] = unicode(pid)

    exists = property(lambda self: self.id is not None)

    def _init_defaults(self, db=None):
        for name, field in self.fields.iteritems():
            default = None
            if field['name'] in self.protected_fields:
                # Ignore for new - only change through workflow etc
                pass
            elif not field.get('custom'):
                default = self.env.config.get('ticket',
                                              'default_' + field['name'])
            else:
                default = field.get('value')
                options = field.get('options')
                if default and options and default not in options:
                    try:
                        default = options[int(default)]
                    except (ValueError, IndexError):
                        self.env.log.warning('Invalid default value "%s" '
                                             'for custom field "%s"'
                                             % (default, field['name']))
            if default:
                default = convert_type_value(field['type'], default)
                self.values.setdefault(field['name'], default)

    def _fetch_ticket(self, tkt_id, db=None):
        row = None
        if self.id_is_valid(tkt_id):
            db = self._get_db(db)

            # Fetch the standard ticket fields
            std_fields = [n for n, f in self.fields.iteritems()
                          if not f.get('custom') and not f.get('virtual')]
            cursor = db.cursor()
            cursor.execute("SELECT %s FROM ticket WHERE id=%%s"
                           % ','.join(std_fields), (tkt_id,))
            row = cursor.fetchone()
        if not row:
            raise ResourceNotFound(_('Ticket %(id)s does not exist.', 
                                     id=tkt_id), _('Invalid ticket number'))

        self.id = tkt_id
        for i, field in enumerate(std_fields):
            value = row[i]
            self.values[field] = convert_field_value(self.fields[field], value)

        # Fetch custom fields if available
        custom_fields = [n for n, f in self.fields.iteritems() if f.get('custom') and not f.get('virtual')]
        cursor.execute("SELECT name,value FROM ticket_custom WHERE ticket=%s",
                       (tkt_id,))
        for name, value in cursor:
            if name in custom_fields:
                self.values[name] = convert_field_value(self.fields[name], value)

    def __getitem__(self, name):
        return self.values.get(name)

    def __setitem__(self, name, value):
        """Log ticket modifications so the table ticket_change can be updated
        """
        field = self.fields.get(name)
        value = convert_field_value(field, value)
        if name in self.values and self.values[name] == value:
            return
        if name not in self._old: # Changed field
            self._old[name] = self.values.get(name)
        elif self._old[name] == value: # Change of field reverted
            del self._old[name]
        if value:
            if isinstance(value, list):
                raise TracError(_("Multi-values fields not supported yet"))
            if field:
                type_ = field.get('type')
                if type_ != 'textarea' and isinstance(value, basestring):
                    value = value.strip()
        self.values[name] = value

    def get_value_or_default(self, name):
        """Return the value of a field or the default value if it is undefined
        """
        try:
            value = self.values[name]
            if value is not None:
                return value
            field = self.fields.get(name)
            if field:
                return field.get('value')
        except KeyError:
            pass

    def populate(self, values):
        """Populate the ticket with 'suitable' values from a dictionary"""
        for name in [name for name in values.keys() if name in self.fields]:
            value = values.get(name)
            self[name] = value

        # We have to do an extra trick to catch unchecked checkboxes
        for name in [name for name in values.keys() if name[9:] in self.fields
                     and name.startswith('checkbox_')]:
            if name[9:] not in values:
                self[name[9:]] = False

    def insert(self, when=None, db=None):
        """Add ticket to database.

        The `db` argument is deprecated in favor of `with_transaction()`.
        """
        assert not self.exists, 'Cannot insert an existing ticket'

        if 'cc' in self.values:
            self['cc'] = _fixup_cc_list(self.values['cc'])

        # Add a timestamp
        if when is None:
            when = datetime.now(utc)
        self.values['time'] = self.values['changetime'] = when

        # The owner field defaults to the component owner
        if self.values.get('component') and not self.values.get('owner'):
            try:
                component = Component(self.env, self['component'], db=db)
                if component.owner:
                    self['owner'] = component.owner
            except ResourceNotFound:
                # No such component exists
                pass

        # Perform type conversions
        values = dict(self.values)
        std_fields = []
        custom_fields = []
        for name, f in self.fields.iteritems():
            if f.get('virtual'):
                continue
            if name in values:
                custom = f.get('custom')
                val = values[name]

                values[name] = prepare_field_value(val, f)

                if custom:
                    custom_fields.append(name)
                else:
                    std_fields.append(name)

        # Insert ticket record
        tkt_id = [None]
        @self.env.with_transaction(db)
        def do_insert(db):
            cursor = db.cursor()
            cursor.execute("INSERT INTO ticket (%s) VALUES (%s)"
                           % (','.join(std_fields),
                              ','.join(['%s'] * len(std_fields))),
                           [values[name] for name in std_fields])
            tkt_id[0] = db.get_last_id(cursor, 'ticket')

            # Insert custom fields
            if custom_fields:
                cursor.executemany("""
                INSERT INTO ticket_custom (ticket,name,value) VALUES (%s,%s,%s)
                """, [(tkt_id[0], name, values[name]) for name in custom_fields])

        self.id = tkt_id[0]
        self.resource = self.resource(id=tkt_id[0])
        self._old = {}

        sid = ProjectManagement(self.env).get_project_syllabus(self.pid)
        for listener in TicketSystem(self.env).change_listeners(sid):
            listener.ticket_created(self)

        return self.id

    def save_changes(self, author=None, comment=None, when=None, db=None, cnum=''):
        """
        Store ticket changes in the database. The ticket must already exist in
        the database.  Returns False if there were no changes to save, True
        otherwise.

        The `db` argument is deprecated in favor of `with_transaction()`.
        """
        assert self.exists, 'Cannot update a new ticket'

        if 'cc' in self.values:
            self['cc'] = _fixup_cc_list(self.values['cc'])

        if not self._old and not comment:
            return False # Not modified

        if when is None:
            when = datetime.now(utc)
        when_ts = to_utimestamp(when)

        if 'component' in self.values:
            # If the component is changed on a 'new' ticket
            # then owner field is updated accordingly. (#623).
            if self.values.get('status') == 'new' \
                    and 'component' in self._old \
                    and 'owner' not in self._old:
                try:
                    old_comp = Component(self.env, self._old['component'])
                    old_owner = old_comp.owner or ''
                    current_owner = self.values.get('owner') or ''
                    if old_owner == current_owner:
                        new_comp = Component(self.env, self['component'])
                        if new_comp.owner:
                            self['owner'] = new_comp.owner
                except TracError:
                    # If the old component has been removed from the database
                    # we just leave the owner as is.
                    pass

        @self.env.with_transaction(db)
        def do_save(db):
            cursor = db.cursor()

            # find cnum if it isn't provided
            comment_num = cnum
            if not comment_num:
                num = 0
                cursor.execute("""
                    SELECT DISTINCT tc1.time,COALESCE(tc2.oldvalue,'')
                    FROM ticket_change AS tc1
                    LEFT OUTER JOIN ticket_change AS tc2
                    ON tc2.ticket=%s AND tc2.time=tc1.time
                       AND tc2.field='comment'
                    WHERE tc1.ticket=%s ORDER BY tc1.time DESC
                    """, (self.id, self.id))
                for ts, old in cursor:
                    # Use oldvalue if available, else count edits
                    try:
                        num += int(old.rsplit('.', 1)[-1])
                        break
                    except ValueError:
                        num += 1
                comment_num = str(num + 1)

            # store fields
            custom_fields = [n for n, f in self.fields.iteritems() if f.get('custom')]

            for name in self._old.keys():
                val = self[name]
                oldval = self._old[name]
                custom = name in custom_fields
                type_ = self.fields[name]['type']
                val = prepare_field_value(val, self.fields[name])
                oldval = prepare_field_value(oldval, self.fields[name])
                if name in custom_fields:
                    cursor.execute("""
                        SELECT 1 FROM ticket_custom 
                        WHERE ticket=%s and name=%s
                        """, (self.id, name))
                    if cursor.fetchone():
                        cursor.execute("""
                            UPDATE ticket_custom SET value=%s
                            WHERE ticket=%s AND name=%s
                            """, (val, self.id, name))
                    else:
                        cursor.execute("""
                            INSERT INTO ticket_custom (ticket,name,value)
                            VALUES(%s,%s,%s)
                            """, (self.id, name, val))
                else:
                    cursor.execute("UPDATE ticket SET %s=%%s WHERE id=%%s" 
                                   % name, (val, self.id))
                cursor.execute("""
                    INSERT INTO ticket_change
                        (ticket,time,author,field,oldvalue,newvalue)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """, (self.id, when_ts, author, name, oldval, val))

            # always save comment, even if empty 
            # (numbering support for timeline)
            cursor.execute("""
                INSERT INTO ticket_change
                    (ticket,time,author,field,oldvalue,newvalue)
                VALUES (%s,%s,%s,'comment',%s,%s)
                """, (self.id, when_ts, author, comment_num, comment))

            cursor.execute("UPDATE ticket SET changetime=%s WHERE id=%s",
                           (when_ts, self.id))

        old_values = self._old
        self._old = {}
        self.values['changetime'] = when

        sid = ProjectManagement(self.env).get_project_syllabus(self.pid)
        for listener in TicketSystem(self.env).change_listeners(sid):
            listener.ticket_changed(self, comment, author, old_values)
        return True

    def get_from_changelog(self, field, old=None, new=None, limit=1):
        '''Return last change (author, old, new) for specified field
        or list with max length `limit` (for limit > 1) in backward history order
        or None if there are no results.
        `old` and `new` filter changelog results and can be either
        single value (string) or multiple (iterable).
        '''
        conn = self.env.get_sa_connection()
        tab = self.env.get_sa_metadata().tables['ticket_change']
        q = tab.select().with_only_columns([tab.c.author, tab.c.oldvalue, tab.c.newvalue]).\
            where(tab.c.field==field).order_by(tab.c.time.desc()).limit(limit)
        for val, col in ((old, tab.c.oldvalue), (new, tab.c.newvalue)):
            if val is not None:
                if isinstance(val, basestring):
                    expr = col == val
                else:
                    expr = col.in_(tuple(val))
                q = q.where(expr)
        res = conn.execute(q)
        f = self.fields.get(field)
        if f:
            conv = lambda v: convert_type_value(f['type'], v)
        else:
            conv = lambda v: v
        rows = [( r[0], conv(r[1]), conv(r[2]) ) for r in res.fetchall()]
        if limit == 1:
            return rows and rows[0]
        return rows

    def get_changelog(self, when=None, db=None):
        """Return the changelog as a list of tuples of the form
        (time, author, field, oldvalue, newvalue, permanent).

        While the other tuple elements are quite self-explanatory,
        the `permanent` flag is used to distinguish collateral changes
        that are not yet immutable (like attachments, currently).
        """
        db = self._get_db(db)
        cursor = db.cursor()
        sid = str(self.id)
        when_ts = to_utimestamp(when)
        if when_ts:
            cursor.execute("""
                SELECT time,author,field,oldvalue,newvalue, 1 AS permanent
                FROM ticket_change WHERE ticket=%s AND time=%s 
                  UNION 
                SELECT time,author,'attachment',null,filename, 0 AS permanent
                FROM attachment WHERE type='ticket' AND id=%s AND time=%s 
                  UNION 
                SELECT time,author,'comment',null,description, 0 AS permanent
                FROM attachment WHERE type='ticket' AND id=%s AND time=%s
                ORDER BY time,permanent,author
                """, (self.id, when_ts, sid, when_ts, sid, when_ts))
        else:
            cursor.execute("""
                SELECT time,author,field,oldvalue,newvalue, 1 AS permanent
                FROM ticket_change WHERE ticket=%s 
                  UNION 
                SELECT time,author,'attachment',null,filename, 0 AS permanent
                FROM attachment WHERE type='ticket' AND id=%s 
                  UNION 
                SELECT time,author,'comment',null,description, 0 AS permanent
                FROM attachment WHERE type='ticket' AND id=%s 
                ORDER BY time,permanent,author
                """, (self.id, sid, sid))
        log = []
        for t, author, field, oldvalue, newvalue, permanent in cursor:
            f = self.fields.get(field)
            if f:
                conv = lambda v: convert_type_value(f['type'], v)
            else:
                conv = lambda v: v
            old, new = map(conv, (oldvalue, newvalue))
            log.append((from_utimestamp(t), author, field,
                        old, new, permanent))
        return log

    def delete(self, db=None):
        """Delete the ticket.

        The `db` argument is deprecated in favor of `with_transaction()`.
        """
        @self.env.with_transaction(db)
        def do_delete(db):
            Attachment.delete_all(self.env, self.resource, db=db)
            cursor = db.cursor()
            cursor.execute("DELETE FROM ticket WHERE id=%s", (self.id,))
            cursor.execute("DELETE FROM ticket_change WHERE ticket=%s",
                           (self.id,))
            cursor.execute("DELETE FROM ticket_custom WHERE ticket=%s",
                           (self.id,))

        sid = ProjectManagement(self.env).get_project_syllabus(self.pid)
        for listener in TicketSystem(self.env).change_listeners(sid):
            listener.ticket_deleted(self)

    def get_change(self, cnum, db=None):
        """Return a ticket change by its number."""
        db = self._get_db(db)
        cursor = db.cursor()
        row = self._find_change(cnum, db)
        if row:
            ts, author, comment = row
            cursor.execute("""
                SELECT field,author,oldvalue,newvalue 
                FROM ticket_change WHERE ticket=%s AND time=%s
                """, (self.id, ts))
            fields = {}
            change = {'date': from_utimestamp(ts),
                      'author': author, 'fields': fields}
            for field, author, old, new in cursor:
                f = self.fields.get(field)
                if f:
                    conv = lambda v: convert_type_value(f['type'], v)
                else:
                    conv = lambda v: v
                old, new = map(conv, (old, new))
                fields[field] = {'author': author, 'old': old, 'new': new}
            return change

    def delete_change(self, cnum):
        """Delete a ticket change."""
        @self.env.with_transaction()
        def do_delete(db):
            cursor = db.cursor()
            row = self._find_change(cnum, db)
            if not row:
                return
            ts = row[0]

            custom_fields = set(n for n, f in self.fields.iteritems()
                                if f.get('custom'))

            # Find modified fields and their previous value
            cursor.execute("""
                SELECT field, oldvalue, newvalue FROM ticket_change
                WHERE ticket=%s AND time=%s
                """, (self.id, ts))
            fields = [(field, old, new) for field, old, new in cursor
                      if field != 'comment' and not field.startswith('_')]
            for field, oldvalue, newvalue in fields:
                # Find the next change
                cursor.execute("""
                    SELECT time FROM ticket_change
                    WHERE ticket=%s AND time>%s AND field=%s
                    LIMIT 1
                    """, (self.id, ts, field))
                for next_ts, in cursor:
                    # Modify the old value of the next change if it is equal
                    # to the new value of the deleted change
                    cursor.execute("""
                        UPDATE ticket_change SET oldvalue=%s
                        WHERE ticket=%s AND time=%s AND field=%s
                              AND oldvalue=%s
                        """, (oldvalue, self.id, next_ts, field, newvalue))
                    break
                else:
                    # No next change, edit ticket field
                    if field in custom_fields:
                        cursor.execute("""
                            UPDATE ticket_custom SET value=%s
                            WHERE ticket=%s AND name=%s
                            """, (oldvalue, self.id, field))
                    else:
                        cursor.execute("""
                            UPDATE ticket SET %s=%%s WHERE id=%%s
                            """ % field, (oldvalue, self.id))

            # Delete the change
            cursor.execute("""
                DELETE FROM ticket_change WHERE ticket=%s AND time=%s
                """, (self.id, ts))

            # Fix the last modification time
            # Work around MySQL ERROR 1093 with the same table for the update
            # target and the subquery FROM clause
            cursor.execute("""
                UPDATE ticket SET changetime=(
                    SELECT time FROM ticket_change WHERE ticket=%s
                    UNION
                    SELECT time FROM (
                        SELECT time FROM ticket WHERE id=%s LIMIT 1) AS t
                    ORDER BY time DESC LIMIT 1)
                WHERE id=%s
                """, (self.id, self.id, self.id))

        self._fetch_ticket(self.id)

    def modify_comment(self, cdate, author, comment, when=None):
        """Modify a ticket comment specified by its date, while keeping a
        history of edits.
        """
        ts = to_utimestamp(cdate)
        if when is None:
            when = datetime.now(utc)
        when_ts = to_utimestamp(when)

        @self.env.with_transaction()
        def do_modify(db):
            cursor = db.cursor()
            # Find the current value of the comment
            cursor.execute("""
                SELECT newvalue FROM ticket_change 
                WHERE ticket=%s AND time=%s AND field='comment'
                """, (self.id, ts))
            old_comment = False
            for old_comment, in cursor:
                break
            if comment == (old_comment or ''):
                return

            # Comment history is stored in fields named "_comment%d"
            # Find the next edit number
            cursor.execute("""
                SELECT field FROM ticket_change 
                WHERE ticket=%%s AND time=%%s AND field %s
                """ % db.like(), (self.id, ts,
                                  db.like_escape('_comment') + '%'))
            fields = list(cursor)
            rev = fields and max(int(field[8:]) for field, in fields) + 1 or 0
            cursor.execute("""
                INSERT INTO ticket_change
                    (ticket,time,author,field,oldvalue,newvalue) 
                VALUES (%s,%s,%s,%s,%s,%s)
                """, (self.id, ts, author, '_comment%d' % rev,
                      old_comment or '', str(when_ts)))
            if old_comment is False:
                # There was no comment field, add one, find the original author
                # in one of the other changed fields
                cursor.execute("""
                    SELECT author FROM ticket_change 
                    WHERE ticket=%%s AND time=%%s AND NOT field %s
                    LIMIT 1
                    """ % db.like(), (self.id, ts, db.like_escape('_') + '%'))
                old_author = None
                for old_author, in cursor:
                    break
                cursor.execute("""
                    INSERT INTO ticket_change 
                        (ticket,time,author,field,oldvalue,newvalue) 
                    VALUES (%s,%s,%s,'comment','',%s)
                    """, (self.id, ts, old_author, comment))
            else:
                cursor.execute("""
                    UPDATE ticket_change SET newvalue=%s 
                    WHERE ticket=%s AND time=%s AND 
                    field='comment'
                    """, (comment, self.id, ts))

            # Update last changed time
            cursor.execute("UPDATE ticket SET changetime=%s WHERE id=%s",
                           (when_ts, self.id))

        self.values['changetime'] = when

    def get_comment_history(self, cnum, db=None):
        db = self._get_db(db)
        history = []
        cursor = db.cursor()
        row = self._find_change(cnum, db)
        if row:
            ts0, author0, last_comment = row
            # Get all fields of the form "_comment%d"
            cursor.execute("""
                SELECT field,author,oldvalue,newvalue 
                FROM ticket_change 
                WHERE ticket=%%s AND time=%%s AND field %s
                """ % db.like(), (self.id, ts0,
                                  db.like_escape('_comment') + '%'))
            rows = sorted((int(field[8:]), author, old, new)
                          for field, author, old, new in cursor)
            for rev, author, comment, ts in rows:
                history.append((rev, from_utimestamp(long(ts0)), author0,
                                comment))
                ts0, author0 = ts, author
            history.sort()
            rev = history and (history[-1][0] + 1) or 0
            history.append((rev, from_utimestamp(long(ts0)), author0,
                            last_comment))
        return history

    def _find_change(self, cnum, db):
        """Find a comment by its number."""
        scnum = str(cnum)
        cursor = db.cursor()
        cursor.execute("""
            SELECT time,author,newvalue FROM ticket_change 
            WHERE ticket=%%s AND field='comment' 
                AND (oldvalue=%%s OR oldvalue %s)
            """ % db.like(), (self.id, scnum,
                              '%' + db.like_escape('.' + scnum)))
        for row in cursor:
            return row

        # Fallback when comment number is not available in oldvalue
        num = 0
        cursor.execute("""
            SELECT DISTINCT tc1.time,COALESCE(tc2.oldvalue,''),
                            tc2.author,COALESCE(tc2.newvalue,'')
            FROM ticket_change AS tc1 
            LEFT OUTER JOIN ticket_change AS tc2
            ON tc2.ticket=%s AND tc2.time=tc1.time AND tc2.field='comment'
            WHERE tc1.ticket=%s ORDER BY tc1.time
            """, (self.id, self.id))
        for ts, old, author, comment in cursor:
            # Use oldvalue if available, else count edits
            try:
                num = int(old.rsplit('.', 1)[-1])
            except ValueError:
                num += 1
            if num == cnum:
                break
        else:
            return

        # Find author if NULL
        if author is None:
            cursor.execute("""
                SELECT author FROM ticket_change 
                WHERE ticket=%%s AND time=%%s AND NOT field %s 
                LIMIT 1
                """ % db.like(), (self.id, ts, db.like_escape('_') + '%'))
            for author, in cursor:
                break
        return (ts, author, comment)

def simplify_whitespace(name):
    """Strip spaces and remove duplicate spaces within names"""
    if name:
        return ' '.join(name.split())
    return name
        

class AbstractEnum(object):
    type = None
    ticket_col = None

    def __init__(self, env, name=None, db=None, pid=None, syllabus_id=None):
        if not self.ticket_col:
            self.ticket_col = self.type
        self.env = env
        if name and (pid is not None or syllabus_id is not None):
            if pid is not None:
                pid = int(pid)
                syllabus_id = None
            if syllabus_id is not None:
                syllabus_id = int(syllabus_id)
                pid = None
            id_, table, column = self._prepare_syll_proj_values(pid, syllabus_id)
            if not db:
                db = self.env.get_read_db()
            cursor = db.cursor()
            cursor.execute("SELECT value FROM {table} WHERE {column}=%s AND type=%s AND name=%s".\
                           format(table=table, column=column),
                           (id_, self.type, name))
            row = cursor.fetchone()
            if not row:
                raise ResourceNotFound(_('%(type)s %(name)s does not exist for %(column)s=%(id_)s.',
                                         type=self.type, name=name, column=column, id_=id_))
            self.value = self._old_value = row[0]
            self.name = self._old_name = name
            self.pid = pid
            self.syllabus_id = syllabus_id
        else:
            self.value = self._old_value = None
            self.name = self._old_name = None
            self.pid = None
            self.syllabus_id = None

    exists = property(lambda self: self._old_value is not None)

    def delete(self, db=None):
        """Delete the enum value.

        The `db` argument is deprecated in favor of `with_transaction()`.
        """
        assert self.exists, 'Cannot delete non-existent %s' % self.type

        @self.env.with_transaction(db)
        def do_delete(db):
            id_, table, column = self._prepare_syll_proj_values(self.pid, self.syllabus_id)
            cursor = db.cursor()
            self.env.log.info('Deleting %s %s for %s=%s' % (self.type, self.name, column, id_))
            cursor.execute("DELETE FROM {table} WHERE {column}=%s AND type=%s AND value=%s".\
                           format(table=table, column=column),
                           (id_, self.type, self._old_value))
            # Re-order any enums that have higher value than deleted
            # (close gap)
            for enum in list(self.select(self.env, db, pid=self.pid, syllabus_id=self.syllabus_id)):
                try:
                    if int(enum.value) > int(self._old_value):
                        enum.value = unicode(int(enum.value) - 1)
                        enum.update()
                except ValueError:
                    pass # Ignore cast error for this non-essential operation
            TicketSystem(self.env).reset_ticket_fields(pid=self.pid, syllabus_id=self.syllabus_id)
        self.value = self._old_value = None
        self.name = self._old_name = None
        self.pid = None
        self.syllabus_id = None

    def insert(self, db=None):
        """Add a new enum value.

        The `db` argument is deprecated in favor of `with_transaction()`.
        """
        assert not self.exists, 'Cannot insert existing %s' % self.type
        self.name = simplify_whitespace(self.name)
        if not self.name:
            raise TracError(_('Invalid %(type)s name.', type=self.type))

        @self.env.with_transaction(db)
        def do_insert(db):
            id_, table, column = self._prepare_syll_proj_values(self.pid, self.syllabus_id)
            cursor = db.cursor()
            self.env.log.debug("Creating new %s '%s' for %s=%s" % (self.type, self.name, column, id_))
            if not self.value:
                cursor.execute("""
                    SELECT COALESCE(MAX(%s),0) FROM {table} WHERE {column}=%%s AND type=%%s
                    """.format(table=table, column=column) % db.cast('value', 'int'),
                    (id_, self.type))
                self.value = int(float(cursor.fetchone()[0])) + 1
            cursor.execute("INSERT INTO {table} ({column},type,name,value) "
                           "VALUES (%s,%s,%s,%s)".format(table=table, column=column),
                           (id_, self.type, self.name, self.value))
            TicketSystem(self.env).reset_ticket_fields(pid=self.pid, syllabus_id=self.syllabus_id)

        self._old_name = self.name
        self._old_value = self.value

    def update(self, db=None):
        """Update the enum value.

        The `db` argument is deprecated in favor of `with_transaction()`.
        """
        assert self.exists, 'Cannot update non-existent %s' % self.type
        self.name = simplify_whitespace(self.name)
        if not self.name:
            raise TracError(_('Invalid %(type)s name.', type=self.type))

        @self.env.with_transaction(db)
        def do_update(db):
            id_, table, column = self._prepare_syll_proj_values(self.pid, self.syllabus_id)
            cursor = db.cursor()
            self.env.log.info('Updating %s "%s" for %s=%s' % (self.type, self.name, column, id_))
            cursor.execute("""
                UPDATE {table} SET name=%s,value=%s 
                WHERE {column}=%s AND type=%s AND name=%s
                """.format(table=table, column=column),
                (self.name, self.value, id_, self.type, self._old_name))
            if self.name != self._old_name:
                # Update tickets
                q = "UPDATE ticket SET {tcol}=%s WHERE project_id {op} %s AND {tcol}=%s"
                if self.pid is not None:
                    arg = self.pid
                    op = '='
                else:
                    arg = tuple(ProjectManagement(self.env).get_syllabus_projects(self.syllabus_id))
                    op = 'IN'
                q = q.format(tcol=self.ticket_col, op=op)
                cursor.execute(q, (self.name, arg, self._old_name))
            TicketSystem(self.env).reset_ticket_fields(pid=self.pid, syllabus_id=self.syllabus_id)

        self._old_name = self.name
        self._old_value = self.value

    @classmethod
    def select(cls, env, db=None, pid=None, syllabus_id=None):
        if not db:
            db = env.get_read_db()
        id_, table, column = cls._prepare_syll_proj_values(pid, syllabus_id)
        query = """
            SELECT name,value FROM {table} WHERE {column}=%s AND type=%s 
            ORDER BY
            """ + db.cast('value', 'int')
        query = query.format(table=table, column=column)
        cursor = db.cursor()
        cursor.execute(query, (id_, cls.type))
        for name, value in cursor:
            obj = cls(env)
            obj.pid = pid
            obj.syllabus_id = syllabus_id
            obj.name = obj._old_name = name
            obj.value = obj._old_value = value
            yield obj

    @classmethod
    def get_min_max(cls, env, db=None, pid=None, syllabus_id=None):
        id_, table, column = cls._prepare_syll_proj_values(pid, syllabus_id)
        query = """
            SELECT MIN(int_val) min_value, MAX(int_val) max_value
            FROM (SELECT CAST(value AS int) int_val
            FROM {table}
            WHERE {column}=%s AND type=%s) AS vals
            """
        query = query.format(table=table, column=column)
        if not db:
            db = env.get_read_db()
        cursor = db.cursor()
        cursor.execute(query, (id_, cls.type))
        row = cursor.fetchone()
        return row

    @classmethod
    def _prepare_syll_proj_values(cls, pid=None, syllabus_id=None):
        if pid is not None:
            id_ = pid
#            attr_name = 'pid'
            table = 'enum'
            column = 'project_id'
        elif syllabus_id is not None:
            id_ = syllabus_id
#            attr_name = 'syllabus_id'
            table = 'enum_syllabus'
            column = 'syllabus_id'
        else:
            raise NotImplementedError('Global enum values are not implemented')
        return id_, table, column



class SyllabusEnum(AbstractEnum):

    def __init__(self, env, name=None, db=None, pid=None, syllabus_id=None):
        if name and syllabus_id is None:
            syllabus_id = self._get_syllabus(env, pid)
        super(SyllabusEnum, self).__init__(env, name, syllabus_id=syllabus_id, db=db)

    @classmethod
    def _get_syllabus(cls, env, pid):
        if pid is not None:
            return ProjectManagement(env).get_project_syllabus(pid, fail_on_none=True)
        else:
            raise TracError('Can not create SyllabusEnum instance without syllabus or project id')

    @classmethod
    def _prepare_syll_proj_values(cls, pid=None, syllabus_id=None):
        assert syllabus_id is not None
        return syllabus_id, 'enum_syllabus', 'syllabus_id'

    @classmethod
    def select(cls, env, db=None, pid=None, syllabus_id=None):
        if syllabus_id is None:
            syllabus_id = cls._get_syllabus(env, pid)
        return super(SyllabusEnum, cls).select(env, syllabus_id=syllabus_id, db=db)

    @classmethod
    def get_min_max(cls, env, db=None, pid=None, syllabus_id=None):
        if syllabus_id is None:
            syllabus_id = cls._get_syllabus(env, pid)
        return super(SyllabusEnum, cls).get_min_max(env, syllabus_id=syllabus_id, db=db)


# Not used now
class ProjectEnum(AbstractEnum):

    def __init__(self, env, name=None, db=None, pid=None, syllabus_id=None):
        if name and pid is None:
            raise TracError('Can not create ProjectEnum instance without project id')
        super(ProjectEnum, self).__init__(env, name, pid=pid, db=db)



class Type(SyllabusEnum):
    type = 'ticket_type'
    ticket_col = 'type'


class Status(object):
    def __init__(self, env, name=None, pid=None, syllabus_id=None):
        self.env = env
        self.name = name
        self.pid = pid
        self.syllabus_id = syllabus_id

    @classmethod
    def select(cls, env, db=None, pid=None, syllabus_id=None):
        for state in TicketSystem(env).get_all_status(pid=pid, syllabus_id=syllabus_id):
            status = cls(env, state, pid, syllabus_id)
            yield status


class Resolution(SyllabusEnum):
    type = 'resolution'


class Priority(SyllabusEnum):
    type = 'priority'


class Severity(SyllabusEnum):
    type = 'severity'


class Component(object):
    def __init__(self, env, name=None, db=None, pid=None):
        self.env = env
        if pid is not None and name:
            pid = int(pid)
            if not db:
                db = self.env.get_read_db()
            cursor = db.cursor()
            cursor.execute("""
                SELECT owner,description FROM component WHERE project_id=%s AND name=%s
                """, (pid, name))
            row = cursor.fetchone()
            if not row:
                raise ResourceNotFound(_('Component %(name)s does not exist in project #%(pid)s.',
                                         name=name, pid=pid))
            self.pid = pid
            self.name = self._old_name = name
            self.owner = row[0] or None
            self.description = row[1] or ''
        else:
            self.pid = None
            self.name = self._old_name = None
            self.owner = None
            self.description = None

    exists = property(lambda self: self._old_name is not None)

    def delete(self, db=None):
        """Delete the component.

        The `db` argument is deprecated in favor of `with_transaction()`.
        """
        assert self.exists, 'Cannot delete non-existent component'

        @self.env.with_transaction(db)
        def do_delete(db):
            cursor = db.cursor()
            self.env.log.info('Deleting component %s in project #%s' % (self.name, self.pid))
            cursor.execute("DELETE FROM component WHERE project_id=%s AND name=%s",
                           (self.pid, self.name))
            TicketSystem(self.env).reset_ticket_fields(self.pid)
            self.name = self._old_name = None
            self.pid = None

    def insert(self, db=None):
        """Insert a new component.

        The `db` argument is deprecated in favor of `with_transaction()`.
        """
        assert not self.exists, 'Cannot insert existing component'
        self.name = simplify_whitespace(self.name)
        if not self.name:
            raise TracError(_('Invalid component name.'))

        @self.env.with_transaction(db)
        def do_insert(db):
            cursor = db.cursor()
            self.env.log.debug("Creating new component '%s' in project #%s" % (self.name, self.pid))
            cursor.execute("""
                INSERT INTO component (project_id,name,owner,description)
                VALUES (%s,%s,%s,%s)
                """, (self.pid, self.name, self.owner, self.description))
            self._old_name = self.name
            TicketSystem(self.env).reset_ticket_fields(self.pid)

    def update(self, db=None):
        """Update the component.

        The `db` argument is deprecated in favor of `with_transaction()`.
        """
        assert self.exists, 'Cannot update non-existent component'
        self.name = simplify_whitespace(self.name)
        if not self.name:
            raise TracError(_('Invalid component name.'))

        @self.env.with_transaction(db)
        def do_update(db):
            cursor = db.cursor()
            self.env.log.info('Updating component "%s" in project #%s' % (self.name, self.pid))
            cursor.execute("""
                UPDATE component SET name=%s,owner=%s, description=%s
                WHERE project_id=%s AND name=%s
                """, (self.name, self.owner, self.description, self.pid, self._old_name))
            if self.name != self._old_name:
                # Update tickets
                cursor.execute("""
                    UPDATE ticket SET component=%s WHERE project_id=%s AND component=%s
                    """, (self.name, self.pid, self._old_name))
                self._old_name = self.name
            TicketSystem(self.env).reset_ticket_fields(self.pid)

    @classmethod
    def select(cls, env, db=None, pid=None, **kwargs):
        if not db:
            db = env.get_read_db()
        cursor = db.cursor()
        cursor.execute("""
            SELECT name,owner,description FROM component
            WHERE project_id=%s
            ORDER BY name
            """, (pid,))
        for name, owner, description in cursor:
            component = cls(env)
            component.pid = pid
            component.name = component._old_name = name
            component.owner = owner or None
            component.description = description or ''
            yield component


class Milestone(object):
    def __init__(self, env, pid=None, name=None, db=None):
        self.env = env
        pid = int(pid) if pid is not None else pid
        if pid is not None and name:
            self._fetch(pid, name, db)
        else:
            self.pid = pid
            self.name = None
            self.due = self.completed = None
            self.description = ''
            self.weight = None
            self._to_old()

    @property
    def resource(self):
        res = Resource('milestone', pid=self.pid, id=self.name) ### .version !!!
        res.need_pid = True
        return res

    def _fetch(self, pid, name, db=None):
        if not db:
            db = self.env.get_read_db()
        cursor = db.cursor()
        cursor.execute("""
            SELECT project_id,name,due,completed,description,weight
            FROM milestone WHERE project_id=%s AND name=%s
            """, (pid, name))
        row = cursor.fetchone()
        if not row:
            raise ResourceNotFound(_('Milestone %(name)s does not exist in project #%(pid)s.',
                                   name=name, pid=pid), _('Invalid milestone name'))
        self._from_database(row)

    exists = property(lambda self: self._old['pid'] is not None and self._old['name'] is not None)
    is_completed = property(lambda self: self.completed is not None)
    is_late = property(lambda self: self.due and
                                    self.due < datetime.now(utc))

    def _from_database(self, row):
        pid, name, due, completed, description, weight = row
        self.pid = pid
        self.name = name
        self.due = due and from_utimestamp(due) or None
        self.completed = completed and from_utimestamp(completed) or None
        self.description = description or ''
        self.weight = weight
        self._to_old()

    def _to_old(self):
        self._old = {'pid': self.pid, 'name': self.name, 'due': self.due,
                     'completed': self.completed,
                     'description': self.description,
                     'weight': self.weight}

    def has_tickets(self):
        '''Return True if there are tickets associated with this milestone.'''
        db = self.env.get_read_db()
        cursor = db.cursor()
        cursor.execute("SELECT 1 FROM ticket WHERE project_id=%s AND milestone=%s LIMIT 1",
                           (self.pid, self.name))
        return bool(cursor.rowcount)

    def retarget_tickets(self, retarget_to, author=None, comment=None):
        if retarget_to:
            # check if retarget milestone exists
            retarget_milestone = Milestone(self.env, self.pid, retarget_to)

        @self.env.with_transaction()
        def do_retarget(db):
            cursor = db.cursor()
            # Retarget/reset tickets associated with this milestone
            now = datetime.now(utc)
            cursor.execute("SELECT id FROM ticket WHERE project_id=%s AND milestone=%s",
                           (self.pid, self.name))
            tkt_ids = [int(row[0]) for row in cursor]
            for tkt_id in tkt_ids:
                ticket = Ticket(self.env, tkt_id, db)
                ticket['milestone'] = retarget_to
                comment_ = comment or 'Retarget from milestone %s' % self.name
                ticket.save_changes(author, comment_, now)
            self.env.log.info('Tickets associated with milestone %s retargeted to %s' % (self.name, retarget_to))

    def delete(self, retarget_to=None, author=None, db=None):
        """Delete the milestone.

        The `db` argument is deprecated in favor of `with_transaction()`.
        """
        assert self.pid is not None

        @self.env.with_transaction()
        def do_delete(db):
            self.retarget_tickets(retarget_to, author, comment=_('Milestone %(name)s deleted', name=self.name))

            cursor = db.cursor()
            self.env.log.info('Deleting milestone %s in project #%s' % (self.name, self.pid))
            cursor.execute("DELETE FROM milestone WHERE project_id=%s AND name=%s", (self.pid, self.name))
            self._old['name'] = None
            TicketSystem(self.env).reset_ticket_fields(self.pid)

        for listener in TicketSystem(self.env).milestone_change_listeners:
            listener.milestone_deleted(self)

    def insert(self, db=None):
        """Insert a new milestone.

        The `db` argument is deprecated in favor of `with_transaction()`.
        """
        self.name = simplify_whitespace(self.name)
        if not self.name:
            raise TracError(_('Invalid milestone name.'))
        Project.check_exists(self.env, self.pid)

        @self.env.with_transaction(db)
        def do_insert(db):
            cursor = db.cursor()
            self.env.log.debug("Creating new milestone '%s' in project #%s" % (self.name, self.pid))
            cursor.execute("""
                INSERT INTO milestone (project_id,name,due,completed,description,weight) 
                VALUES (%s,%s,%s,%s,%s,%s)
                """, (self.pid, self.name, to_utimestamp(self.due),
                      to_utimestamp(self.completed), self.description, self.weight))
            self._to_old()
            TicketSystem(self.env).reset_ticket_fields(self.pid)

        for listener in TicketSystem(self.env).milestone_change_listeners:
            listener.milestone_created(self)

    def update(self, db=None):
        """Update the milestone.

        The `db` argument is deprecated in favor of `with_transaction()`.
        """
        self.name = simplify_whitespace(self.name)
        if not self.name:
            raise TracError(_('Invalid milestone name.'))
        Project.check_exists(self.env, self.pid)

        @self.env.with_transaction(db)
        def do_update(db):
            cursor = db.cursor()
            old_name = self._old['name']
            self.env.log.info('Updating milestone "%s"' % self.name)
            cursor.execute("""
                UPDATE milestone
                SET name=%s,due=%s,completed=%s,description=%s,weight=%s WHERE project_id=%s AND name=%s
                """, (self.name, to_utimestamp(self.due),
                      to_utimestamp(self.completed),
                      self.description, self.weight, self.pid, old_name))

            if self.name != old_name:
                # Update milestone field in tickets
                self.env.log.info('Updating milestone field of all tickets '
                                  'associated with milestone "%s"' % self.name)
                cursor.execute("""
                    UPDATE ticket SET milestone=%s WHERE project_id=%s AND milestone=%s
                    """, (self.name, self.pid, old_name))
                TicketSystem(self.env).reset_ticket_fields(self.pid)

                # Reparent attachments
                Attachment.reparent_all(self.env, 'milestone', old_name, self.pid,
                                        'milestone', self.name, self.pid)

        old_values = dict((k, v) for k, v in self._old.iteritems()
                          if getattr(self, k) != v)
        self._to_old()
        for listener in TicketSystem(self.env).milestone_change_listeners:
            listener.milestone_changed(self, old_values)

    @classmethod
    def select(cls, env, pid, include_completed=True, db=None, **kwargs):
        if not db:
            db = env.get_read_db()
        sql = "SELECT project_id,name,due,completed,description,weight FROM milestone WHERE project_id=%s"
        if not include_completed:
            sql += " AND COALESCE(completed,0)=0 "
        cursor = db.cursor()
        cursor.execute(sql, (pid,))
        milestones = []
        for row in cursor:
            milestone = Milestone(env)
            milestone._from_database(row)
            milestones.append(milestone)
        def milestone_order(m):
            return (m.completed or utcmax,
                    m.due or utcmax,
                    embedded_numbers(m.name))
        return sorted(milestones, key=milestone_order)

    @classmethod
    def get_total_weight(cls, env, pid):
        db = env.get_read_db()
        q = 'SELECT SUM(weight) FROM milestone WHERE project_id=%s'
        cursor = db.cursor()
        cursor.execute(q, (pid,))
        row = cursor.fetchone()
        return row and row[0] or 0


def group_milestones(milestones, include_completed):
    """Group milestones into "open with due date", "open with no due date",
    and possibly "completed". Return a list of (label, milestones) tuples."""
    def category(m):
        return m.is_completed and 1 or m.due and 2 or 3
    open_due_milestones, open_not_due_milestones, \
        closed_milestones = partition([(m, category(m))
            for m in milestones], (2, 3, 1))
    groups = [
        (_('Open (by due date)'), open_due_milestones),
        (_('Open (no due date)'), open_not_due_milestones),
    ]
    if include_completed:
        groups.append((_('Closed'), closed_milestones))
    return groups


class Version(object):
    def __init__(self, env, name=None, db=None, pid=None):
        self.env = env
        if pid is not None and name:
            pid = int(pid)
            if not db:
                db = self.env.get_read_db()
            cursor = db.cursor()
            cursor.execute("""
                SELECT time,description FROM version WHERE project_id=%s AND name=%s
                """, (pid, name))
            row = cursor.fetchone()
            if not row:
                raise ResourceNotFound(_('Version %(name)s does not exist in project #%(pid)s.',
                                         name=name, pid=pid))
            self.pid = pid
            self.name = self._old_name = name
            self.time = row[0] and from_utimestamp(row[0]) or None
            self.description = row[1] or ''
        else:
            self.pid = None
            self.name = self._old_name = None
            self.time = None
            self.description = None

    exists = property(lambda self: self._old_name is not None)

    def delete(self, db=None):
        """Delete the version.

        The `db` argument is deprecated in favor of `with_transaction()`.
        """
        assert self.exists, 'Cannot delete non-existent version'

        @self.env.with_transaction(db)
        def do_delete(db):
            cursor = db.cursor()
            self.env.log.info('Deleting version %s in project #%s' % (self.name, self.pid))
            cursor.execute("DELETE FROM version WHERE project_id=%s AND name=%s",
                           (self.pid, self.name))
            TicketSystem(self.env).reset_ticket_fields(self.pid)
            self.name = self._old_name = None
            self.pid = None

    def insert(self, db=None):
        """Insert a new version.

        The `db` argument is deprecated in favor of `with_transaction()`.
        """
        assert not self.exists, 'Cannot insert existing version'
        self.name = simplify_whitespace(self.name)
        if not self.name:
            raise TracError(_('Invalid version name.'))

        @self.env.with_transaction(db)
        def do_insert(db):
            cursor = db.cursor()
            self.env.log.debug("Creating new version '%s' in project #%s" % (self.name, self.pid))
            cursor.execute("""
                INSERT INTO version (project_id,name,time,description) VALUES (%s,%s,%s,%s)
                """, (self.pid, self.name, to_utimestamp(self.time), self.description))
            self._old_name = self.name
            TicketSystem(self.env).reset_ticket_fields(self.pid)

    def update(self, db=None):
        """Update the version.

        The `db` argument is deprecated in favor of `with_transaction()`.
        """
        assert self.exists, 'Cannot update non-existent version'
        self.name = simplify_whitespace(self.name)
        if not self.name:
            raise TracError(_('Invalid version name.'))

        @self.env.with_transaction(db)
        def do_update(db):
            cursor = db.cursor()
            self.env.log.info('Updating version "%s" in project #%s' % (self.name, self.pid))
            cursor.execute("""
                UPDATE version SET name=%s,time=%s,description=%s
                WHERE project_id=%s AND name=%s
                """, (self.name, to_utimestamp(self.time),
                      self.description, self.pid, self._old_name))
            if self.name != self._old_name:
                # Update tickets
                cursor.execute("UPDATE ticket SET version=%s WHERE project_id=%s AND version=%s",
                               (self.name, self.pid, self._old_name))
                self._old_name = self.name
            TicketSystem(self.env).reset_ticket_fields(self.pid)

    @classmethod
    def select(cls, env, db=None, pid=None, **kwargs):
        if not db:
            db = env.get_read_db()
        cursor = db.cursor()
        cursor.execute("""
        SELECT name,time,description FROM version
        WHERE project_id=%s
        """, (pid,))
        versions = []
        for name, time, description in cursor:
            version = cls(env)
            version.pid = pid
            version.name = version._old_name = name
            version.time = time and from_utimestamp(time) or None
            version.description = description or ''
            versions.append(version)
        def version_order(v):
            return (v.time or utcmax, embedded_numbers(v.name))
        return sorted(versions, key=version_order, reverse=True)
