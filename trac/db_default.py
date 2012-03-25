# -*- coding: utf-8 -*-
#
# Copyright (C) 2003-2009 Edgewall Software
# Copyright (C) 2003-2005 Daniel Lundin <daniel@edgewall.com>
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
# Author: Daniel Lundin <daniel@edgewall.com>

from trac.db import Table, Column, Index, ForeignKey

# Database version identifier. Used for automatic upgrades.
db_version = 26

def __mkreports(reports):
    """Utility function used to create report data in same syntax as the
    default data. This extra step is done to simplify editing the default
    reports."""
    result = []
    for report in reports:
        result.append((None, report[0], report[2], report[1]))
    return result


##
## Database schema
##

schema = [
    # Common
    Table('system', key='name')[
        Column('name'),
        Column('value')],
    Table('permission', key=('username', 'action'))[
        Column('username'),
        Column('action')],
    Table('auth_cookie', key=('cookie', 'ipnr', 'name'))[
        Column('cookie'),
        Column('name'),
        Column('ipnr'),
        Column('time', type='int')],
    Table('session', key=('sid', 'authenticated'))[
        Column('sid'),
        Column('authenticated', type='int'),
        Column('last_visit', type='int'),
        Index(['last_visit']),
        Index(['authenticated'])],
    Table('session_attribute', key=('sid', 'authenticated', 'name'))[
        Column('sid'),
        Column('authenticated', type='int'),
        Column('name'),
        Column('value')],
    Table('cache', key='id')[
        Column('id'),
        Column('generation', type='int')],

    # User / group system
    Table('users', key=('id',))[
        Column('id', auto_increment=True),
        Column('username', type='varchar (255)', null=False, unique=True),
        Column('password', type='varchar (255)'),
    ],
    Table('teams', key=('id',))[
        Column('id', auto_increment=True),
        Column('name', type='varchar (255)', null=False),
    ],
    Table('student_groups', key=('id',))[
        Column('id', auto_increment=True),
        Column('name', type='varchar (255)', null=False),
    ],
    Table('metagroups', key=('id',))[
        Column('id', auto_increment=True),
        Column('name', type='varchar (255)', null=False),
        Column('year', type='smallint', null=False),
        Column('active', type='bool', default='TRUE', null=False),
    ],
    Table('team_members', key=('user_id', 'team_id'))[
        Column('user_id', type='int', null=False),
        Column('team_id', type='int', null=False),
        ForeignKey('user_id', 'users', 'id', on_delete='CASCADE'),
        ForeignKey('team_id', 'teams', 'id', on_delete='CASCADE'),
    ],
    Table('teamgroup_rel', key=('studgroup_id', 'team_id'))[
        Column('studgroup_id', type='int', null=False),
        Column('team_id', type='int', null=False),
        ForeignKey('studgroup_id', 'student_groups', 'id', on_delete='CASCADE'),
        ForeignKey('team_id', 'teams', 'id', on_delete='CASCADE'),
    ],
    Table('groupmeta_rel', key=('metagroup_id', 'studgroup_id'))[
        Column('metagroup_id', type='int', null=False),
        Column('studgroup_id', type='int', null=False),
        ForeignKey('metagroup_id', 'metagroups', 'id', on_delete='CASCADE'),
        ForeignKey('studgroup_id', 'student_groups', 'id', on_delete='CASCADE'),
    ],
    Table('team_attributes', key=('gid', 'name'))[
        Column('gid', type='int'),
        Column('name', type='varchar (255)'),
        Column('value', type='text'),
        ForeignKey('studgroup_id', 'student_groups', 'id', on_delete='CASCADE'),
        ForeignKey('team_id', 'teams', 'id', on_delete='CASCADE'),
    ],

    # Project system
    Table('projects', key=('id',))[
        Column('id', auto_increment=True),
        Column('name', type='varchar (255)', null=False, unique=True),
        Column('description', type='text', default="''"),
    ],
    Table('team_project_rel', key=('team_id',))[
        Column('team_id', type='int', null=False),
        Column('project_id', type='int', null=False),
        ForeignKey('team_id', 'teams', 'id', on_delete='CASCADE'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE'),
    ],
    Table('project_managers', key=('user_id', 'project_id'))[
        Column('user_id', type='int', null=False),
        Column('project_id', type='int', null=False),
        ForeignKey('user_id', 'users', 'id', on_delete='CASCADE'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE'),
    ],
    Table('studgroup_managers', key=('user_id', 'studgroup_id'))[
        Column('user_id', type='int', null=False),
        Column('studgroup_id', type='int', null=False),
        ForeignKey('user_id', 'users', 'id', on_delete='CASCADE'),
        ForeignKey('studgroup_id', 'student_groups', 'id', on_delete='CASCADE'),
    ],
    Table('syllabuses', key=('id',))[
        Column('id', auto_increment=True),
        Column('name', type='varchar (255)', null=False),
    ],
    Table('metagroup_syllabus_rel', key=('metagroup_id',))[
        Column('metagroup_id', type='int', null=False),
        Column('syllabus_id', type='int', null=False),
        ForeignKey('metagroup_id', 'metagroups', 'id', on_delete='CASCADE'),
        ForeignKey('syllabus_id', 'syllabuses', 'id', on_delete='CASCADE'),
    ],

    # Attachments
    Table('attachment', key=('type', 'id', 'project_id', 'filename'))[
        Column('type'),
        Column('id'),
        Column('project_id', type='int', default='0'),
        Column('filename'),
        Column('size', type='int'),
        Column('time', type='int64'),
        Column('description'),
        Column('author'),
        Column('ipnr'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE'),],

    # Wiki system
    Table('wiki', key=('name', 'version'))[
        Column('name'),
        Column('version', type='int'),
        Column('time', type='int64'),
        Column('author'),
        Column('ipnr'),
        Column('text'),
        Column('comment'),
        Column('readonly', type='int'),
        Column('project_id', type='int', null=True),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE'),
        Index(['time'])],

    # Version control cache
    Table('repository', key=('id', 'name'))[
        Column('id', type='int'),
        Column('name'),
        Column('value')],
    Table('revision', key=('repos', 'rev'))[
        Column('repos', type='int'),
        Column('rev', key_size=20),
        Column('time', type='int64'),
        Column('author'),
        Column('message'),
        Index(['repos', 'time'])],
    Table('node_change', key=('repos', 'rev', 'path', 'change_type'))[
        Column('repos', type='int'),
        Column('rev', key_size=20),
        Column('path', key_size=255),
        Column('node_type', size=1),
        Column('change_type', size=1, key_size=2),
        Column('base_path'),
        Column('base_rev'),
        Index(['repos', 'rev'])],

    # Ticket system
    Table('enum', key=('project_id', 'type', 'name'))[
        Column('project_id', type='int', null=False),
        Column('type'),
        Column('name'),
        Column('value'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE')],
    Table('enum_syllabus', key=('syllabus_id', 'type', 'name'))[
        Column('syllabus_id', type='int', null=False),
        Column('type'),
        Column('name'),
        Column('value'),
        ForeignKey('syllabus_id', 'syllabuses', 'id', on_delete='CASCADE')],
    Table('component', key=('project_id', 'name'))[
        Column('project_id', type='int', null=False),
        Column('name'),
        Column('owner'),
        Column('description'),
        ForeignKey('owner', 'users', 'username', on_delete='CASCADE', on_update='CASCADE'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE')],
    Table('milestone', key=('project_id', 'name'))[
        Column('project_id', type='int', null=False),
        Column('name'),
        Column('due', type='int64'),
        Column('completed', type='int64'),
        Column('description'),
        Column('weight', type='int', null=False, default='0'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE')],
    Table('version', key=('project_id', 'name'))[
        Column('project_id', type='int', null=False),
        Column('name'),
        Column('time', type='int64'),
        Column('description'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE')],
    Table('ticket', key='id')[
        Column('id', auto_increment=True),
        Column('project_id', type='int', null=False),
        Column('type'),
        Column('time', type='int64'),
        Column('changetime', type='int64'),
        Column('component'),
        Column('severity'),
        Column('priority'),
        Column('owner'),
        Column('reporter'),
        Column('cc'),
        Column('version'),
        Column('milestone'),
        Column('status'),
        Column('resolution'),
        Column('summary'),
        Column('description'),
        Column('keywords'),
        ForeignKey('owner', 'users', 'username', on_delete='CASCADE', on_update='CASCADE'),
        ForeignKey('reporter', 'users', 'username', on_delete='CASCADE', on_update='CASCADE'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE'),
#        ForeignKey(('milestone', 'project_id'), 'milestone', ('name', 'project_id'), on_update='CASCADE'),
        Index(['time']),
        Index(['status'])],    
    Table('ticket_change', key=('ticket', 'time', 'field'))[
        Column('ticket', type='int'),
        Column('time', type='int64'),
        Column('author'),
        Column('field'),
        Column('oldvalue'),
        Column('newvalue'),
        ForeignKey('author', 'users', 'username', on_delete='CASCADE', on_update='CASCADE'),
        Index(['ticket']),
        Index(['time'])],
    Table('ticket_custom', key=('ticket', 'name'))[
        Column('ticket', type='int'),
        Column('name'),
        Column('value')],

    # Report system
    Table('report', key='id')[
        Column('id', auto_increment=True),
        Column('author'),
        Column('title'),
        Column('query'),
        Column('description'),
        Column('syllabus_id', type='int', null=True),
        Column('project_id', type='int', null=True),
        ForeignKey('author', 'users', 'username', on_delete='CASCADE', on_update='CASCADE'),
        ForeignKey('syllabus_id', 'syllabuses', 'id', on_delete='CASCADE'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE')],

    # Evaluation system
    Table('ticket_evaluation', key=('ticket_id',))[
        Column('ticket_id', type='int', null=False),
        Column('value', type='int', null=False, default='0'),
        ForeignKey('ticket_id', 'ticket', 'id', on_delete='CASCADE')],
    Table('team_milestone_evaluation', key=('username', 'project_id', 'milestone'))[
        Column('username', type='varchar(255)'),
        Column('project_id', type='int'),
        Column('milestone', type='varchar(255)'),
        Column('complete', type='bool', default='TRUE', null=False),
        Column('completed_on', type='timestamp', default='CURRENT_TIMESTAMP', null=False),
        ForeignKey('username', 'users', 'username', on_delete='CASCADE', on_update='CASCADE'),
        ForeignKey(('milestone', 'project_id'), 'milestone', ('name', 'project_id'), on_delete='CASCADE', on_update='CASCADE'),],
    Table('team_milestone_evaluation_results', key=('author', 'target', 'project_id', 'milestone'))[
        Column('author', type='varchar(255)'),
        Column('target', type='varchar(255)'),
        Column('project_id', type='int'),
        Column('milestone', type='varchar(255)'),
        Column('value', type='int', null=False, default='0'),
        Column('comment', type='text', default="''", null=False),
        ForeignKey('author', 'users', 'username', on_delete='CASCADE', on_update='CASCADE'),
        ForeignKey('target', 'users', 'username', on_delete='CASCADE', on_update='CASCADE'),
        ForeignKey(('milestone', 'project_id'), 'milestone', ('name', 'project_id'), on_delete='CASCADE', on_update='CASCADE'),],
]


##
## Default Reports
##

def get_reports(db):
    return (
('Active Tickets',
"""
 * List all active tickets by priority.
 * Color each row based on priority.
""",
"""
SELECT p.value AS __color__,
   id AS ticket, summary, component, version, milestone, t.type AS type, 
   owner, status,
   time AS created,
   changetime AS _changetime, description AS _description,
   reporter AS _reporter
  FROM ticket t
  LEFT JOIN enum p ON p.name = t.priority AND p.type = 'priority'
  WHERE status <> 'closed'
  ORDER BY """ + db.cast('p.value', 'int') + """, milestone, t.type, time
"""),
#----------------------------------------------------------------------------
 ('Active Tickets by Version',
"""
This report shows how to color results by priority,
while grouping results by version.

Last modification time, description and reporter are included as hidden fields
for useful RSS export.
""",
"""
SELECT p.value AS __color__,
   version AS __group__,
   id AS ticket, summary, component, version, t.type AS type, 
   owner, status,
   time AS created,
   changetime AS _changetime, description AS _description,
   reporter AS _reporter
  FROM ticket t
  LEFT JOIN enum p ON p.name = t.priority AND p.type = 'priority'
  WHERE status <> 'closed'
  ORDER BY (version IS NULL),version, """ + db.cast('p.value', 'int') +
  """, t.type, time
"""),
#----------------------------------------------------------------------------
('Active Tickets by Milestone',
"""
This report shows how to color results by priority,
while grouping results by milestone.

Last modification time, description and reporter are included as hidden fields
for useful RSS export.
""",
"""
SELECT p.value AS __color__,
   %s AS __group__,
   id AS ticket, summary, component, version, t.type AS type, 
   owner, status,
   time AS created,
   changetime AS _changetime, description AS _description,
   reporter AS _reporter
  FROM ticket t
  LEFT JOIN enum p ON p.name = t.priority AND p.type = 'priority'
  WHERE status <> 'closed' 
  ORDER BY (milestone IS NULL),milestone, %s, t.type, time
""" % (db.concat("'Milestone '", 'milestone'), db.cast('p.value', 'int'))),
#----------------------------------------------------------------------------
('Accepted, Active Tickets by Owner',
"""
List accepted tickets, group by ticket owner, sorted by priority.
""",
"""

SELECT p.value AS __color__,
   owner AS __group__,
   id AS ticket, summary, component, milestone, t.type AS type, time AS created,
   changetime AS _changetime, description AS _description,
   reporter AS _reporter
  FROM ticket t
  LEFT JOIN enum p ON p.name = t.priority AND p.type = 'priority'
  WHERE status = 'accepted'
  ORDER BY owner, """ + db.cast('p.value', 'int') + """, t.type, time
"""),
#----------------------------------------------------------------------------
('Accepted, Active Tickets by Owner (Full Description)',
"""
List tickets accepted, group by ticket owner.
This report demonstrates the use of full-row display.
""",
"""
SELECT p.value AS __color__,
   owner AS __group__,
   id AS ticket, summary, component, milestone, t.type AS type, time AS created,
   description AS _description_,
   changetime AS _changetime, reporter AS _reporter
  FROM ticket t
  LEFT JOIN enum p ON p.name = t.priority AND p.type = 'priority'
  WHERE status = 'accepted'
  ORDER BY owner, """ + db.cast('p.value', 'int') + """, t.type, time
"""),
#----------------------------------------------------------------------------
('All Tickets By Milestone  (Including closed)',
"""
A more complex example to show how to make advanced reports.
""",
"""
SELECT p.value AS __color__,
   t.milestone AS __group__,
   (CASE status 
      WHEN 'closed' THEN 'color: #777; background: #ddd; border-color: #ccc;'
      ELSE 
        (CASE owner WHEN $USER THEN 'font-weight: bold' END)
    END) AS __style__,
   id AS ticket, summary, component, status, 
   resolution,version, t.type AS type, priority, owner,
   changetime AS modified,
   time AS _time,reporter AS _reporter
  FROM ticket t
  LEFT JOIN enum p ON p.name = t.priority AND p.type = 'priority'
  ORDER BY (milestone IS NULL), milestone DESC, (status = 'closed'), 
        (CASE status WHEN 'closed' THEN changetime ELSE (-1) * %s END) DESC
""" % db.cast('p.value', 'int')),
#----------------------------------------------------------------------------
('My Tickets',
"""
This report demonstrates the use of the automatically set 
USER dynamic variable, replaced with the username of the
logged in user when executed.
""",
"""
SELECT p.value AS __color__,
   (CASE status WHEN 'accepted' THEN 'Accepted' ELSE 'Owned' END) AS __group__,
   id AS ticket, summary, component, version, milestone,
   t.type AS type, priority, time AS created,
   changetime AS _changetime, description AS _description,
   reporter AS _reporter
  FROM ticket t
  LEFT JOIN enum p ON p.name = t.priority AND p.type = 'priority'
  WHERE t.status <> 'closed' AND owner = $USER
  ORDER BY (status = 'accepted') DESC, """ + db.cast('p.value', 'int') + 
  """, milestone, t.type, time
"""),
#----------------------------------------------------------------------------
('Active Tickets, Mine first',
"""
 * List all active tickets by priority.
 * Show all tickets owned by the logged in user in a group first.
""",
"""
SELECT p.value AS __color__,
   (CASE owner 
     WHEN $USER THEN 'My Tickets' 
     ELSE 'Active Tickets' 
    END) AS __group__,
   id AS ticket, summary, component, version, milestone, t.type AS type, 
   owner, status,
   time AS created,
   changetime AS _changetime, description AS _description,
   reporter AS _reporter
  FROM ticket t
  LEFT JOIN enum p ON p.name = t.priority AND p.type = 'priority'
  WHERE status <> 'closed' 
  ORDER BY (COALESCE(owner, '') = $USER) DESC, """
  + db.cast('p.value', 'int') + """, milestone, t.type, time
"""))


##
## Default database values
##

# (table, (column1, column2), ((row1col1, row1col2), (row2col1, row2col2)))
def get_data(db):
    return (
            ('projects',
              ('id', 'name'),
                ((0, 'Global'),)),
#            ('component',
#              ('name', 'owner'),
#                (('component1', 'somebody'),
#                 ('component2', 'somebody'))),
#            ('milestone',
#              ('name', 'due', 'completed'),
#                (('milestone1', 0, 0),
#                 ('milestone2', 0, 0),
#                 ('milestone3', 0, 0),
#                 ('milestone4', 0, 0))),
#            ('version',
#              ('name', 'time'),
#                (('1.0', 0),
#                 ('2.0', 0))),
            ('enum',
              ('type', 'name', 'value', 'project_id'),
                (('resolution', 'fixed', 1, 0),
                 ('resolution', 'invalid', 2, 0),
                 ('resolution', 'wontfix', 3, 0),
                 ('resolution', 'duplicate', 4, 0),
                 ('resolution', 'worksforme', 5, 0),
                 ('priority', 'blocker', 5, 0),
                 ('priority', 'critical', 4, 0),
                 ('priority', 'major', 3, 0),
                 ('priority', 'minor', 2, 0),
                 ('priority', 'trivial', 1, 0),
                 ('severity', 'hard', 3, 0),
                 ('severity', 'normal', 2, 0),
                 ('severity', 'easy', 1, 0),
                 ('ticket_type', 'defect', 1, 0),
                 ('ticket_type', 'enhancement', 2, 0),
                 ('ticket_type', 'task', 3, 0))),
            ('permission',
              ('username', 'action'),
                (('anonymous', 'LOG_VIEW'),
                 ('anonymous', 'FILE_VIEW'),
                 ('anonymous', 'WIKI_VIEW'),
                 ('authenticated', 'WIKI_CREATE'),
                 ('authenticated', 'WIKI_MODIFY'),
                 ('anonymous', 'SEARCH_VIEW'),
                 ('anonymous', 'REPORT_VIEW'),
                 ('anonymous', 'REPORT_SQL_VIEW'),
                 ('anonymous', 'TICKET_VIEW'),
                 ('authenticated', 'TICKET_CREATE'),
                 ('authenticated', 'TICKET_MODIFY'),
                 ('anonymous', 'BROWSER_VIEW'),
                 ('anonymous', 'TIMELINE_VIEW'),
                 ('anonymous', 'CHANGESET_VIEW'),
                 ('anonymous', 'ROADMAP_VIEW'),
                 ('anonymous', 'MILESTONE_VIEW'))),
            ('system',
              ('name', 'value'),
                (('database_version', str(db_version)),
                 ('initial_database_version', str(db_version)))),
            ('report',
              ('author', 'title', 'query', 'description'),
                __mkreports(get_reports(db))))
