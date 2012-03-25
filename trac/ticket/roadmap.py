# -*- coding: utf-8 -*-
#
# Copyright (C) 2004-2009 Edgewall Software
# Copyright (C) 2004-2005 Christopher Lenz <cmlenz@gmx.de>
# Copyright (C) 2006-2007 Christian Boos <cboos@neuf.fr>
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

from StringIO import StringIO
from datetime import datetime, timedelta
import re

from genshi.builder import tag

from trac import __version__
from trac.attachment import AttachmentModule
from trac.config import ExtensionOption, BoolOption
from trac.core import *
from trac.mimeview import Context
from trac.perm import IPermissionRequestor
from trac.resource import *
from trac.search import ISearchSource, search_to_sql, shorten_result
from trac.util import as_bool
from trac.util.datefmt import parse_date, utc, to_utimestamp, \
                              get_datetime_format_hint, format_date, \
                              format_datetime, from_utimestamp
from trac.util.text import CRLF
from trac.util.translation import _, tag_
from trac.ticket import Milestone, Ticket, TicketSystem, group_milestones
from trac.ticket.query import QueryModule
from trac.timeline.api import ITimelineEventProvider
from trac.web import IRequestHandler, RequestDone
from trac.web.chrome import add_link, add_notice, add_script, add_stylesheet, \
                            add_warning, Chrome, INavigationContributor
from trac.wiki.api import IWikiSyntaxProvider
from trac.wiki.formatter import format_to

from trac.project.api import ProjectManagement

class ITicketGroupStatsProvider(Interface):
    def get_ticket_group_stats(ticket_ids, pid):
        """ Gather statistics on a group of tickets.

        This method returns a valid TicketGroupStats object.
        """

class TicketGroupStats(object):
    """Encapsulates statistics on a group of tickets."""

    def __init__(self, title, unit):
        """Creates a new TicketGroupStats object.
        
        `title` is the display name of this group of stats (e.g.
          'ticket status').
        `unit` is the units for these stats in plural form, e.g. _('hours')
        """
        self.title = title
        self.unit = unit
        self.count = 0
        self.qry_args = {}
        self.intervals = []
        self.done_percent = 0
        self.done_count = 0

    def add_interval(self, title, count, qry_args, css_class,
                     overall_completion=None, countsToProg=0):
        """Adds a division to this stats' group's progress bar.

        `title` is the display name (eg 'closed', 'spent effort') of this
        interval that will be displayed in front of the unit name.
        `count` is the number of units in the interval.
        `qry_args` is a dict of extra params that will yield the subset of
          tickets in this interval on a query.
        `css_class` is the css class that will be used to display the division.
        `overall_completion` can be set to true to make this interval count
          towards overall completion of this group of tickets.
          
        (Warning: `countsToProg` argument will be removed in 0.12, use
        `overall_completion` instead)
        """
        if overall_completion is None:
            overall_completion = countsToProg
        self.intervals.append({
            'title': title,
            'count': count,
            'qry_args': qry_args,
            'css_class': css_class,
            'percent': None,
            'countsToProg': overall_completion,
            'overall_completion': overall_completion,
        })
        self.count = self.count + count

    def refresh_calcs(self):
        if self.count < 1:
            return
        total_percent = 0
        self.done_percent = 0
        self.done_count = 0
        for interval in self.intervals:
            interval['percent'] = round(float(interval['count'] / 
                                        float(self.count) * 100))
            total_percent = total_percent + interval['percent']
            if interval['overall_completion']:
                self.done_percent += interval['percent']
                self.done_count += interval['count']

        # We want the percentages to add up to 100%. To do that, we fudge one
        # of the intervals. If we're <100%, we add to the smallest non-zero
        # interval. If we're >100%, we subtract from the largest interval.
        # The interval is adjusted by enough to make the intervals sum to 100%.
        if self.done_count and total_percent != 100:
            fudge_amt = 100 - total_percent
            fudge_int = [i for i in sorted(self.intervals,
                                           key=lambda k: k['percent'],
                                           reverse=(fudge_amt < 0))
                         if i['percent']][0]
            fudge_int['percent'] += fudge_amt
            self.done_percent += fudge_amt


class DefaultTicketGroupStatsProvider(Component):
    """Configurable ticket group statistics provider.

    Example configuration (which is also the default):
    {{{
    [milestone-groups]

    # Definition of a 'closed' group:
    
    closed = closed

    # The definition consists in a comma-separated list of accepted status.
    # Also, '*' means any status and could be used to associate all remaining
    # states to one catch-all group.

    # Qualifiers for the above group (the group must have been defined first):
    
    closed.order = 0                     # sequence number in the progress bar
    closed.query_args = group=resolution # optional extra param for the query
    closed.overall_completion = true     # count for overall completion

    # Definition of an 'active' group:

    active = *                           # one catch-all group is allowed
    active.order = 1
    active.css_class = open              # CSS class for this interval
    active.label = in progress           # Displayed name for the group,
                                         #  needed for non-ascii group names

    # The CSS class can be one of: new (yellow), open (no color) or
    # closed (green). New styles can easily be added using the following
    # selector:  `table.progress td.<class>`
    }}}
    """

    implements(ITicketGroupStatsProvider)

    default_milestone_groups =  [
        {'name': 'closed', 'status': 'closed',
         'query_args': 'group=resolution', 'overall_completion': 'true'},
        {'name': 'active', 'status': '*', 'css_class': 'open'}
        ]

    def _get_ticket_groups(self):
        """Returns a list of dict describing the ticket groups
        in the expected order of appearance in the milestone progress bars.
        """
        if 'milestone-groups' in self.config:
            groups = {}
            order = 0
            for groupname, value in self.config.options('milestone-groups'):
                qualifier = 'status'
                if '.' in groupname:
                    groupname, qualifier = groupname.split('.', 1)
                group = groups.setdefault(groupname, {'name': groupname,
                                                      'order': order})
                group[qualifier] = value
                order = max(order, int(group['order'])) + 1
            return [group for group in sorted(groups.values(),
                                              key=lambda g: int(g['order']))]
        else:
            return self.default_milestone_groups

    def get_ticket_group_stats(self, ticket_ids, pid):
        total_cnt = len(ticket_ids)
        all_statuses = set(TicketSystem(self.env).get_all_status(pid=pid))
        status_cnt = {}
        for s in all_statuses:
            status_cnt[s] = 0
        if total_cnt:
            db = self.env.get_db_cnx()
            cursor = db.cursor()
            str_ids = [str(x) for x in sorted(ticket_ids)]
            cursor.execute("SELECT status, count(status) FROM ticket "
                           "WHERE id IN (%s) GROUP BY status" %
                           ",".join(str_ids))
            for s, cnt in cursor:
                status_cnt[s] = cnt

        stat = TicketGroupStats(_('ticket status'), _('tickets'))
        remaining_statuses = set(all_statuses)
        groups =  self._get_ticket_groups()
        catch_all_group = None
        # we need to go through the groups twice, so that the catch up group
        # doesn't need to be the last one in the sequence
        for group in groups:
            status_str = group['status'].strip()
            if status_str == '*':
                if catch_all_group:
                    raise TracError(_(
                        "'%(group1)s' and '%(group2)s' milestone groups "
                        "both are declared to be \"catch-all\" groups. "
                        "Please check your configuration.",
                        group1=group['name'], group2=catch_all_group['name']))
                catch_all_group = group
            else:
                group_statuses = set([s.strip()
                                      for s in status_str.split(',')]) \
                                      & all_statuses
                if group_statuses - remaining_statuses:
                    raise TracError(_(
                        "'%(groupname)s' milestone group reused status "
                        "'%(status)s' already taken by other groups. "
                        "Please check your configuration.",
                        groupname=group['name'],
                        status=', '.join(group_statuses - remaining_statuses)))
                else:
                    remaining_statuses -= group_statuses
                group['statuses'] = group_statuses
        if catch_all_group:
            catch_all_group['statuses'] = remaining_statuses
        for group in groups:
            group_cnt = 0
            query_args = {}
            for s, cnt in status_cnt.iteritems():
                if s in group['statuses']:
                    group_cnt += cnt
                    query_args.setdefault('status', []).append(s)
            for arg in [kv for kv in group.get('query_args', '').split(',')
                        if '=' in kv]:
                k, v = [a.strip() for a in arg.split('=', 1)]
                query_args.setdefault(k, []).append(v)
            stat.add_interval(group.get('label', group['name']), 
                              group_cnt, query_args,
                              group.get('css_class', group['name']),
                              as_bool(group.get('overall_completion')))
        stat.refresh_calcs()
        return stat


def get_ticket_stats(provider, tickets, pid):
    return provider.get_ticket_group_stats([t['id'] for t in tickets], pid)

def get_tickets_for_milestone(env, db, milestone, field='component'):
    cursor = db.cursor()
    pid  = milestone.pid
    name = milestone.name
    fields = TicketSystem(env).get_ticket_fields(pid)
    f = fields.get(field)
    if f and not f.get('custom'):
        cursor.execute("SELECT id,status,%s FROM ticket WHERE project_id=%%s AND milestone=%%s "
                       "ORDER BY %s" % (field, field), (pid, name))
    else:
        cursor.execute("SELECT id,status,value FROM ticket LEFT OUTER "
                       "JOIN ticket_custom ON (id=ticket AND name=%s) "
                       "WHERE project_id=%s AND milestone=%s ORDER BY value",
                       (field, pid, name))
    tickets = []
    for tkt_id, status, fieldval in cursor:
        tickets.append({'id': tkt_id, 'status': status, field: fieldval})
    return tickets

def apply_ticket_permissions(env, req, tickets):
    """Apply permissions to a set of milestone tickets as returned by
    get_tickets_for_milestone()."""
    return [t for t in tickets
            if 'TICKET_VIEW' in req.perm('ticket', t['id'])]

def milestone_stats_data(env, req, stat, milestone, grouped_by='component',
                         group=None):
    has_query = env[QueryModule] is not None
    name = milestone.name
    pid  = milestone.pid
    def query_href(extra_args):
        if not has_query:
            return None
        args = {'project_id': pid, 'milestone': name, grouped_by: group, 'group': 'status'}
        args.update(extra_args)
        return req.href.query(args)
    return {'stats': stat,
            'stats_href': query_href(stat.qry_args),
            'interval_hrefs': [query_href(interval['qry_args'])
                               for interval in stat.intervals]}



class RoadmapModule(Component):

    implements(INavigationContributor, IPermissionRequestor, IRequestHandler)
    stats_provider = ExtensionOption('roadmap', 'stats_provider',
                                     ITicketGroupStatsProvider,
                                     'DefaultTicketGroupStatsProvider',
        """Name of the component implementing `ITicketGroupStatsProvider`, 
        which is used to collect statistics on groups of tickets for display
        in the roadmap views.""")

    # INavigationContributor methods

    def get_active_navigation_item(self, req):
        return 'roadmap'

    def get_navigation_items(self, req):
        if 'ROADMAP_VIEW' in req.perm:
            yield ('mainnav', 'roadmap',
                   tag.a(_('Roadmap'), href=req.href.roadmap(), accesskey=3))

    # IPermissionRequestor methods

    def get_permission_actions(self):
        actions = ['MILESTONE_CREATE', 'MILESTONE_DELETE', 'MILESTONE_MODIFY',
                   'MILESTONE_VIEW', 'ROADMAP_VIEW']
        return ['ROADMAP_VIEW'] + [('ROADMAP_ADMIN', actions)]

    # IRequestHandler methods

    def match_request(self, req):
        return req.path_info == '/roadmap'

    def process_request(self, req):
        req.perm.require('MILESTONE_VIEW')

        pm = ProjectManagement(self.env)
        pid = pm.get_current_project(req)
        pm.check_session_project(req, pid, allow_multi=True)

        show = req.args.getlist('show')
        hide = req.args.getlist('hide')
        if 'all' in show or 'completed' not in hide:
            show = ['completed']

        db = self.env.get_read_db()
        milestones = Milestone.select(self.env, pid, 'completed' not in hide, db)
        if 'noduedate' in show:
            milestones = [m for m in milestones
                          if m.due is not None or m.completed]
        milestones = [m for m in milestones
                      if 'MILESTONE_VIEW' in req.perm(m.resource)]

        stats = []
        queries = []

        for milestone in milestones:
            tickets = get_tickets_for_milestone(self.env, db, milestone,
                                                'owner')
            tickets = apply_ticket_permissions(self.env, req, tickets)
            stat = get_ticket_stats(self.stats_provider, tickets, pid)
            stats.append(milestone_stats_data(self.env, req, stat,
                                              milestone))
            #milestone['tickets'] = tickets # for the iCalendar view

        total_weight = Milestone.get_total_weight(self.env, pid)

        if req.args.get('format') == 'ics':
            self.render_ics(req, pid, db, milestones)
            return

        # FIXME should use the 'webcal:' scheme, probably
        username = None
        if req.authname and req.authname != 'anonymous':
            username = req.authname
        icshref = req.href.roadmap(show=show, user=username, format='ics')
        add_link(req, 'alternate', icshref, _('iCalendar'), 'text/calendar',
                 'ics')

        data = {
            'milestones': milestones,
            'milestone_stats': stats,
            'total_weight': total_weight,
            'queries': queries,
            'show': show,
            'hide': hide,
        }
        add_stylesheet(req, 'common/css/roadmap.css')
        return 'roadmap.html', data, None

    # Internal methods

    def render_ics(self, req, pid, db, milestones):
        req.send_response(200)
        req.send_header('Content-Type', 'text/calendar;charset=utf-8')
        buf = StringIO()

        from trac.ticket import Priority
        priorities = {}
        for priority in Priority.select(self.env, pid=pid):
            priorities[priority.name] = float(priority.value)
        def get_priority(ticket):
            value = priorities.get(ticket['priority'])
            if value:
                return int((len(priorities) + 8 * value - 9) /
                       (len(priorities) - 1))

        def get_status(ticket):
            status = ticket['status']
            if status == 'new' or status == 'reopened' and not ticket['owner']:
                return 'NEEDS-ACTION'
            elif status == 'assigned' or status == 'reopened':
                return 'IN-PROCESS'
            elif status == 'closed':
                if ticket['resolution'] == 'fixed' or ticket['resolution'] == 'done':
                    return 'COMPLETED'
                else: return 'CANCELLED'
            else: return ''

        def escape_value(text): 
            s = ''.join(map(lambda c: (c in ';,\\') and '\\' + c or c, text))
            return '\\n'.join(re.split(r'[\r\n]+', s))

        def write_prop(name, value, params={}):
            text = ';'.join([name] + [k + '=' + v for k, v in params.items()]) \
                 + ':' + escape_value(value)
            firstline = 1
            while text:
                if not firstline:
                    text = ' ' + text
                else: firstline = 0
                buf.write(text[:75] + CRLF)
                text = text[75:]

        def write_date(name, value, params={}):
            params['VALUE'] = 'DATE'
            write_prop(name, format_date(value, '%Y%m%d', req.tz), params)

        def write_utctime(name, value, params={}):
            write_prop(name, format_datetime(value, '%Y%m%dT%H%M%SZ', utc),
                       params)

        host = req.base_url[req.base_url.find('://') + 3:]
        user = req.args.get('user', 'anonymous')

        write_prop('BEGIN', 'VCALENDAR')
        write_prop('VERSION', '2.0')
        write_prop('PRODID', '-//Edgewall Software//NONSGML Trac %s//EN'
                   % __version__)
        write_prop('METHOD', 'PUBLISH')
        write_prop('X-WR-CALNAME',
                   self.env.project_name + ' - ' + _('Roadmap'))
        for milestone in milestones:
            uid = '<%s/milestone/%s/%s/%s@%s>' % (req.base_path, milestone.name, 'project', milestone.pid,
                                            host)
            if milestone.due:
                write_prop('BEGIN', 'VEVENT')
                write_prop('UID', uid)
                write_utctime('DTSTAMP', milestone.due)
                write_date('DTSTART', milestone.due)
                write_prop('SUMMARY', _('Milestone %(name)s',
                                        name=milestone.name))
                write_prop('URL', get_resource_url(self.env, milestone.resource, req.abs_href))
                if milestone.description:
                    write_prop('DESCRIPTION', milestone.description)
                write_prop('END', 'VEVENT')
            tickets = get_tickets_for_milestone(self.env, db, milestone,
                                                field='owner')
            tickets = apply_ticket_permissions(self.env, req, tickets)
            for tkt_id in [ticket['id'] for ticket in tickets
                           if ticket['owner'] == user]:
                ticket = Ticket(self.env, tkt_id)
                write_prop('BEGIN', 'VTODO')
                write_prop('UID', '<%s/ticket/%s@%s>' % (req.base_path,
                                                         tkt_id, host))
                if milestone.due:
                    write_prop('RELATED-TO', uid)
                    write_date('DUE', milestone.due)
                write_prop('SUMMARY', _('Ticket #%(num)s: %(summary)s',
                                        num=ticket.id,
                                        summary=ticket['summary']))
                write_prop('URL', req.abs_href.ticket(ticket.id))
                write_prop('DESCRIPTION', ticket['description'])
                priority = get_priority(ticket)
                if priority:
                    write_prop('PRIORITY', unicode(priority))
                write_prop('STATUS', get_status(ticket))
                if ticket['status'] == 'closed':
                    cursor = db.cursor()
                    cursor.execute("SELECT time FROM ticket_change "
                                   "WHERE ticket=%s AND field='status' "
                                   "ORDER BY time desc LIMIT 1",
                                   (ticket.id,))
                    row = cursor.fetchone()
                    if row:
                        write_utctime('COMPLETED', from_utimestamp(row[0]))
                write_prop('END', 'VTODO')
        write_prop('END', 'VCALENDAR')

        ics_str = buf.getvalue().encode('utf-8')
        req.send_header('Content-Length', len(ics_str))
        req.end_headers()
        req.write(ics_str)
        raise RequestDone


class MilestoneModule(Component):

    implements(INavigationContributor, IPermissionRequestor, IRequestHandler,
               ITimelineEventProvider, IWikiSyntaxProvider, IResourceManager,
               ISearchSource)
 
    stats_provider = ExtensionOption('milestone', 'stats_provider',
                                     ITicketGroupStatsProvider,
                                     'DefaultTicketGroupStatsProvider',
        """Name of the component implementing `ITicketGroupStatsProvider`, 
        which is used to collect statistics on groups of tickets for display
        in the milestone views.""")
    force_milestone = BoolOption('ticket-workflow-config', 'force_milestone', default='true',
                        doc="""Do not allow to have tickets without milestone""", switcher=True)

    # INavigationContributor methods

    def get_active_navigation_item(self, req):
        return 'roadmap'

    def get_navigation_items(self, req):
        return []

    # IPermissionRequestor methods

    def get_permission_actions(self):
        actions = ['MILESTONE_CREATE', 'MILESTONE_DELETE', 'MILESTONE_MODIFY',
                   'MILESTONE_MODIFY_WEIGHT', 'MILESTONE_MODIFY_CLOSED', 'MILESTONE_CLOSE',
                   'MILESTONE_VIEW']
        return actions + [('MILESTONE_ADMIN', actions)]

    # ITimelineEventProvider methods

    def get_timeline_filters(self, req):
        if 'MILESTONE_VIEW' in req.perm:
            yield ('milestone', _('Milestones reached'))

    def get_timeline_events(self, req, start, stop, filters, pid):
        if 'milestone' in filters:
            is_global = pid is None
            milestone_realm = Resource('milestone')
            db = self.env.get_read_db()
            cursor = db.cursor()
            # TODO: creation and (later) modifications should also be reported
            query = '''
                SELECT {sel_pid} completed,name,description FROM milestone
                WHERE completed>=%s AND completed<=%s {and_pid}
            '''
            sql_args = [to_utimestamp(start), to_utimestamp(stop)]
            if is_global:
                sel_pid = 'project_id,'
                and_pid = ''
            else:
                sel_pid = ''
                and_pid = 'AND project_id=%s'
                sql_args.append(pid)
            query = query.format(sel_pid=sel_pid, and_pid=and_pid)
            cursor.execute(query, sql_args)
            if is_global:
                for project_id, completed, name, description in cursor:
                    milestone = milestone_realm(id=name, pid=project_id)
                    if 'MILESTONE_VIEW' in req.perm(milestone):
                        yield('milestone', project_id, from_utimestamp(completed),
                              '', (milestone, description)) # FIXME: author?
            else:
                for completed, name, description in cursor:
                    milestone = milestone_realm(id=name, pid=pid)
                    if 'MILESTONE_VIEW' in req.perm(milestone):
                        yield('milestone', from_utimestamp(completed),
                              '', (milestone, description)) # FIXME: author?

            # Attachments
            for event in AttachmentModule(self.env).get_timeline_events(
                req, milestone_realm, start, stop, pid):
                yield event
                
    def render_timeline_event(self, context, field, event):
        milestone, description = event[3]
        if field == 'url':
            return get_resource_url(self.env, milestone, context.href)
        elif field == 'title':
            return tag_('Milestone %(name)s completed',
                        name=tag.em(milestone.id))
        elif field == 'description':
            return format_to(self.env, None, context(resource=milestone),
                             description)

    # IRequestHandler methods

    def match_request(self, req):
        match = re.match(r'/milestone(?:/(.+))?$', req.path_info)
        if match:
            if match.group(1):
                req.args['id'] = match.group(1)
            return True

    def process_request(self, req):
        milestone_id = req.args.get('id')
        action = req.args.get('action', 'view')

        pm = ProjectManagement(self.env)
        self.pm = pm
        pid = pm.get_current_project(req)
        pm.check_session_project(req, pid, allow_multi=True)
        milestone_pid = pid

        req.perm('milestone', milestone_id).require('MILESTONE_VIEW')
        
        add_link(req, 'up', req.href.roadmap(), _('Roadmap'))

        db = self.env.get_db_cnx() # TODO: db can be removed
        try:
            milestone = Milestone(self.env, milestone_pid, milestone_id, db)
        except ResourceNotFound:
            if 'MILESTONE_CREATE' not in req.perm('milestone', milestone_id):
                raise
            milestone = Milestone(self.env, milestone_pid, None, db)
            milestone.name = milestone_id
            action = 'edit' # rather than 'new' so that it works for POST/save

        if action == 'teameval':
            from trac.evaluation.web_ui import EvaluationStatsModule
            return EvaluationStatsModule(self.env).team_milestone_eval(req, milestone)

        if req.method == 'POST':
            if req.args.has_key('cancel'):
                if milestone.exists:
                    req.redirect(get_resource_url(self.env, milestone.resource, req.href))
                else:
                    req.redirect(req.href.roadmap())
            elif action == 'edit':
                return self._do_save(req, db, milestone)
            elif action == 'delete':
                self._do_delete(req, milestone)
        elif action in ('new', 'edit'):
            return self._render_editor(req, db, milestone)
        elif action == 'delete':
            return self._render_confirm(req, db, milestone)

        if not milestone.name:
            req.redirect(req.href.roadmap())

        return self._render_view(req, db, milestone)

    # Internal methods

    def _do_delete(self, req, milestone):
        req.perm(milestone.resource).require('MILESTONE_DELETE')

        retarget_to = None
        if req.args.has_key('retarget'):
            retarget_to = req.args.get('target')
        if not retarget_to: # None or empty
            syllabus_id = self.pm.get_project_syllabus(milestone.pid)
            if self.force_milestone.syllabus(syllabus_id) and milestone.has_tickets():
                raise TracError(_('Can not delete milestone %(milestone)s because there are some tickets associated with it'
                                  ' and new target is not selected for them.', milestone=milestone.name))
        milestone.delete(retarget_to, req.authname)
        add_notice(req, _('The milestone "%(name)s" has been deleted.',
                          name=milestone.name))
        req.redirect(req.href.roadmap())

    def _do_save(self, req, db, milestone):
        if milestone.exists:
            req.perm(milestone.resource).require('MILESTONE_MODIFY')
            if milestone.completed:
                req.perm(milestone.resource).require('MILESTONE_MODIFY_CLOSED')
        else:
            req.perm(milestone.resource).require('MILESTONE_CREATE')

        old_name = milestone.name
        new_name = req.args.get('name')
        
        milestone.description = req.args.get('description', '')

        if 'due' in req.args:
            due = req.args.get('duedate', '')
            milestone.due = due and parse_date(due, req.tz, 'datetime') or None
        else:
            milestone.due = None

        completed = req.args.get('completeddate', '')
        retarget_to = req.args.get('target')

        milestone_pid = milestone.pid

        # Instead of raising one single error, check all the constraints and
        # let the user fix them by going back to edit mode showing the warnings
        warnings = []
        def warn(msg):
            add_warning(req, msg)
            warnings.append(msg)

        # -- check the name
        # If the name has changed, check that the milestone doesn't already
        # exist
        # FIXME: the whole .exists business needs to be clarified
        #        (#4130) and should behave like a WikiPage does in
        #        this respect.
        try:
            new_milestone = Milestone(self.env, milestone_pid, new_name, db)
            if new_milestone.name == old_name:
                pass        # Creation or no name change
            elif new_milestone.name:
                warn(_('Milestone "%(name)s" already exists, please '
                       'choose another name.', name=new_milestone.name))
            else:
                warn(_('You must provide a name for the milestone.'))
        except ResourceNotFound:
            milestone.name = new_name

        # -- check completed date
        if 'completed' in req.args:
            completed = completed and parse_date(completed, req.tz,
                                                 'datetime') or None
            if completed != milestone.completed:
                req.perm(milestone.resource).require('MILESTONE_CLOSE')
            if completed and completed > datetime.now(utc):
                warn(_('Completion date may not be in the future'))
        else:
            completed = None
        milestone.completed = completed

        # -- check weight value
        try:
            weight = int(req.args.get('weight'))
            if weight != milestone.weight:
                req.perm(milestone.resource).require('MILESTONE_MODIFY_WEIGHT')
        except ValueError:
            warn(_('You mist provide a valid integer value for milestone weight.'))
            weight = None
        milestone.weight = weight

        if warnings:
            return self._render_editor(req, db, milestone)
        
        # -- actually save changes
        if milestone.exists:
            milestone.update()
            # eventually retarget opened tickets associated with the milestone
            if 'retarget' in req.args and completed:
                # TODO: check ticket modify permissions
                retarget_to = req.args.get('target')
                if retarget_to is None:
                    syllabus_id = self.pm.get_project_syllabus(milestone.pid)
                    if self.force_milestone.syllabus(syllabus_id):
                        raise TracError(_('Can not retarget tickets to empty milestone.'))
                milestone.retarget_tickets(retarget_to, req.authname, comment=_(
                                            'Milestone %(name)s set as completed', name=milestone.name))
        else:
            milestone.insert()

        add_notice(req, _('Your changes have been saved.'))
        req.redirect(get_resource_url(self.env, milestone.resource, req.href))

    def _render_confirm(self, req, db, milestone):
        req.perm(milestone.resource).require('MILESTONE_DELETE')

        milestones = [m for m in Milestone.select(self.env, pid=milestone.pid, db=db)
                      if m.name != milestone.name
                      and 'MILESTONE_VIEW' in req.perm(m.resource)]
        data = {
            'milestone': milestone,
            'milestone_groups': group_milestones(milestones,
                'TICKET_ADMIN' in req.perm)
        }
        return 'milestone_delete.html', data, None

    def _render_editor(self, req, db, milestone):
        # Suggest a default due time of 18:00 in the user's timezone
        default_due = datetime.now(req.tz).replace(hour=18, minute=0, second=0,
                                                   microsecond=0)
        if default_due <= datetime.now(utc):
            default_due += timedelta(days=1)
        
        data = {
            'milestone': milestone,
            'datetime_hint': get_datetime_format_hint(),
            'default_due': default_due,
            'milestone_groups': [],
        }

        if milestone.exists:
            req.perm(milestone.resource).require('MILESTONE_MODIFY')
            milestones = [m for m in Milestone.select(self.env, pid=milestone.pid, db=db)
                          if m.name != milestone.name
                          and 'MILESTONE_VIEW' in req.perm(m.resource)]
            data['milestone_groups'] = group_milestones(milestones,
                'TICKET_ADMIN' in req.perm)
        else:
            req.perm(milestone.resource).require('MILESTONE_CREATE')

        Chrome(self.env).add_wiki_toolbars(req)
        return 'milestone_edit.html', data, None

    def _render_view(self, req, db, milestone):
        pid = milestone.pid
        milestone_groups = []
        available_groups = []
        component_group_available = False
        ticket_fields = TicketSystem(self.env).get_ticket_fields(pid)

        # collect fields that can be used for grouping
        for name, field in ticket_fields.iteritems():
            if field['type'] == 'select' and name != 'milestone' \
                    or field['type'] == 'username':
                available_groups.append({'name': name,
                                         'label': field['label']})
                if name == 'component':
                    component_group_available = True

        # determine the field currently used for grouping
        by = None
        if component_group_available:
            by = 'component'
        elif available_groups:
            by = available_groups[0]['name']
        by = req.args.get('by', by)

        tickets = get_tickets_for_milestone(self.env, db, milestone, by)
        tickets = apply_ticket_permissions(self.env, req, tickets)
        stat = get_ticket_stats(self.stats_provider, tickets, pid)

        total_weight = Milestone.get_total_weight(self.env, pid)

        context = Context.from_request(req, milestone.resource)
        data = {
            'context': context,
            'milestone': milestone,
            'total_weight': total_weight,
            'attachments': AttachmentModule(self.env).attachment_data(context),
            'available_groups': available_groups, 
            'grouped_by': by,
            'groups': milestone_groups
            }
        data.update(milestone_stats_data(self.env, req, stat, milestone))

        if by:
            groups = []
            field = ticket_fields.get(by)
            if field:
                if 'options' in field:
                    groups = field['options']
                    if field.get('optional'):
                        groups.insert(0, '')
                else:
                    cursor = db.cursor()
                    cursor.execute("""
                        SELECT DISTINCT COALESCE(%s,'') FROM ticket
                        ORDER BY COALESCE(%s,'')
                        """ % (by, by))
                    groups = [row[0] for row in cursor]

            max_count = 0
            group_stats = []

            for group in groups:
                values = group and (group,) or (None, group)
                group_tickets = [t for t in tickets if t[by] in values]
                if not group_tickets:
                    continue

                gstat = get_ticket_stats(self.stats_provider, group_tickets, pid)
                if gstat.count > max_count:
                    max_count = gstat.count

                group_stats.append(gstat) 

                gs_dict = {'name': group}
                gs_dict.update(milestone_stats_data(self.env, req, gstat,
                                                    milestone, by, group))
                milestone_groups.append(gs_dict)

            for idx, gstat in enumerate(group_stats):
                gs_dict = milestone_groups[idx]
                percent = 1.0
                if max_count:
                    percent = float(gstat.count) / float(max_count) * 100
                gs_dict['percent_of_max_total'] = percent

        add_stylesheet(req, 'common/css/roadmap.css')
        add_script(req, 'common/js/folding.js')
        return 'milestone_view.html', data, None

    # IWikiSyntaxProvider methods

    def get_wiki_syntax(self):
        return []

    def get_link_resolvers(self):
        yield ('milestone', self._format_link)

    def _format_link(self, formatter, ns, name, label):
        name, query, fragment = formatter.split_link(name)
        pid  = formatter.req.args['pid']
        return self._render_link(formatter.context, pid, name, label,
                                 query + fragment)

    def _render_link(self, context, pid, name, label, extra=''):
        try:
            milestone = Milestone(self.env, pid, name)
        except TracError:
            milestone = None
        # Note: the above should really not be needed, `Milestone.exists`
        # should simply be false if the milestone doesn't exist in the db
        # (related to #4130)
        rsc = Resource('milestone', name, pid=pid)
        href = get_resource_url(self.env, rsc, context.href)
        if milestone and milestone.exists:
            if 'MILESTONE_VIEW' in context.perm(milestone.resource):
                closed = milestone.is_completed and 'closed ' or ''
                return tag.a(label, class_='%smilestone' % closed,
                             href=href + extra)
        elif 'MILESTONE_CREATE' in context.perm('milestone', name):
            return tag.a(label, class_='missing milestone', href=href + extra,
                         rel='nofollow')
        return tag.a(label, class_='missing milestone')
        
    # IResourceManager methods

    def get_resource_realms(self):
        yield 'milestone'

    def get_resource_description(self, resource, format=None, context=None,
                                 **kwargs):
#        desc = '%s:project:%s' % (resource.id, resource.pid)
        desc = resource.id
        if format != 'compact':
            desc =  _('Milestone %(name)s (project #%(pid)s)', name=resource.id, pid=resource.pid)
        if context:
            return self._render_link(context, resource.pid, resource.id, desc)
        else:
            return desc

    def resource_exists(self, resource):
        """
        >>> from trac.test import EnvironmentStub
        >>> env = EnvironmentStub()
        
        >>> m1 = Milestone(env)
        >>> m1.name = 'M1'
        >>> m1.insert()
        
        >>> MilestoneModule(env).resource_exists(Resource('milestone', 'M1'))
        True
        >>> MilestoneModule(env).resource_exists(Resource('milestone', 'M2'))
        False
        """
        db = self.env.get_read_db()
        cursor = db.cursor()
        cursor.execute("SELECT name FROM milestone WHERE name=%s",
                       (resource.id,))
        return bool(cursor.fetchall())

    def get_resource(self, realm, rsc_id, args):
        if realm == 'milestone':
            return Milestone(self.env, args['project_id'], rsc_id)

    def get_realm_info(self):
        return {
            'milestone': {
                'need_pid': True,
            }
        }

    def has_project_resources(self, realm):
        if realm == 'milestone':
            return True

    def has_global_resources(self, realm):
        if realm == 'milestone':
            return False

    def is_slave_realm(self, realm):
        if realm == 'milestone':
            return False

    def get_realm_table(self, realm):
        if realm == 'milestone':
            return 'milestone'

    def get_realm_id(self, realm):
        if realm == 'milestone':
            return 'name'

    # ISearchSource methods

    def get_search_filters(self, req):
        if 'MILESTONE_VIEW' in req.perm:
            yield ('milestone', _('Milestones'))

    def get_search_results(self, req, terms, filters):
        if not 'milestone' in filters:
            return
        db = self.env.get_db_cnx()
        sql_query, args = search_to_sql(db, ['name', 'description'], terms)
        cursor = db.cursor()
        cursor.execute("SELECT name,due,completed,description "
                       "FROM milestone "
                       "WHERE " + sql_query, args)

        milestone_realm = Resource('milestone')
        for name, due, completed, description in cursor:
            milestone = milestone_realm(id=name)
            if 'MILESTONE_VIEW' in req.perm(milestone):
                dt = (completed and from_utimestamp(completed) or
                      due and from_utimestamp(due) or datetime.now(utc))
                yield (get_resource_url(self.env, milestone, req.href),
                       get_resource_name(self.env, milestone), dt,
                       '', shorten_result(description, terms))
        
        # Attachments
        for result in AttachmentModule(self.env).get_search_results(
            req, milestone_realm, terms):
            yield result
