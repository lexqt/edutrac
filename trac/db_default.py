# -*- coding: utf-8 -*-
#
# Copyright (C) 2012 Aleksey A. Porfirov
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
    # System
    Table('system', key='name')[
        Column('name', type='varchar (255)'),
        Column('value', type='varchar (255)')],
    Table('cache', key='id')[
        Column('id', type='varchar (255)'),
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
    Table('groups', key=('id',))[
        Column('id', auto_increment=True),
        Column('name', type='varchar (255)', null=False),
        Column('description', type='text', default="''"),
    ],
    Table('metagroups', key=('id',))[
        Column('id', auto_increment=True),
        Column('name', type='varchar (255)', null=False),
        Column('year', type='smallint', null=False),
        Column('active', type='bool', default='TRUE', null=False),
    ],
    Table('team_members', key=('user_id', 'team_id'))[
        Column('user_id', type='int'),
        Column('team_id', type='int'),
        ForeignKey('user_id', 'users', 'id', on_delete='CASCADE'),
        ForeignKey('team_id', 'teams', 'id', on_delete='CASCADE'),
    ],
    Table('teamgroup_rel', key=('group_id', 'team_id'))[
        Column('group_id', type='int'),
        Column('team_id', type='int', unique=True),
        ForeignKey('group_id', 'groups', 'id', on_delete='CASCADE'),
        ForeignKey('team_id', 'teams', 'id', on_delete='CASCADE'),
    ],
    Table('groupmeta_rel', key=('metagroup_id', 'group_id'))[
        Column('metagroup_id', type='int'),
        Column('group_id', type='int', unique=True),
        ForeignKey('metagroup_id', 'metagroups', 'id', on_delete='CASCADE'),
        ForeignKey('group_id', 'groups', 'id', on_delete='CASCADE'),
    ],
    # TODO: not used, to be deleted?
    Table('team_attributes', key=('gid', 'name'))[
        Column('gid', type='int'),
        Column('name', type='varchar (255)'),
        Column('value', type='text'),
        ForeignKey('gid', 'teams', 'id', on_delete='CASCADE'),
    ],

    # Project system
    Table('projects', key=('id',))[
        Column('id', auto_increment=True),
        Column('name', type='varchar (255)', null=False, unique=True),
        Column('description', type='text', default="''"),
    ],
    Table('team_project_rel', key=('team_id', 'project_id'))[
        Column('team_id', type='int'),
        Column('project_id', type='int', unique=True),
        ForeignKey('team_id', 'teams', 'id', on_delete='CASCADE'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE'),
    ],
    # TODO: not used, to be deleted?
    Table('project_managers', key=('user_id', 'project_id'))[
        Column('user_id', type='int'),
        Column('project_id', type='int'),
        ForeignKey('user_id', 'users', 'id', on_delete='CASCADE'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE'),
    ],
    Table('group_managers', key=('user_id', 'group_id'))[
        Column('user_id', type='int'),
        Column('group_id', type='int'),
        ForeignKey('user_id', 'users', 'id', on_delete='CASCADE'),
        ForeignKey('group_id', 'groups', 'id', on_delete='CASCADE'),
    ],
    Table('syllabuses', key=('id',))[
        Column('id', auto_increment=True),
        Column('name', type='varchar (255)', null=False),
        Column('description', type='text', default="''"),
    ],
    Table('metagroup_syllabus_rel', key=('metagroup_id', 'syllabus_id'))[
        Column('metagroup_id', type='int'),
        Column('syllabus_id', type='int'),
        ForeignKey('metagroup_id', 'metagroups', 'id', on_delete='CASCADE'),
        ForeignKey('syllabus_id', 'syllabuses', 'id', on_delete='CASCADE'),
    ],

    # Permissions, authentication, session
    Table('permission', key=('username', 'action'))[
        Column('username', type='varchar (255)'), # user or permgroup name
        Column('action', type='varchar (255)'),
    ],
    Table('project_permissions', key=('username', 'project_id', 'action'))[
        Column('username', type='varchar (255)'), # user name only
        Column('project_id', type='int'),
        Column('action', type='varchar (255)'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE'),
        ForeignKey('username', 'users', 'username', on_delete='CASCADE', on_update='CASCADE'),
    ],
    Table('syllabus_permissions', key=('username', 'syllabus_id', 'action'))[
        Column('username', type='varchar (255)'), # user or permgroup name
        Column('syllabus_id', type='int'),
        Column('action', type='varchar (255)'),
        ForeignKey('syllabus_id', 'syllabuses', 'id', on_delete='CASCADE'),
    ],
    Table('auth_cookie', key=('cookie', 'ipnr', 'name'))[
        Column('cookie', type='varchar (255)'),
        Column('name', type='varchar (255)'),
        Column('ipnr', type='varchar (255)'),
        Column('time', type='int'),
        ForeignKey('name', 'users', 'username', on_delete='CASCADE', on_update='CASCADE'),
    ],
    Table('session', key=('sid', 'authenticated'))[
        Column('sid', type='varchar (255)'),
        Column('authenticated', type='int'),
        Column('last_visit', type='int'),
        ForeignKey('sid', 'users', 'username', on_delete='CASCADE', on_update='CASCADE'),
        Index(['last_visit']),
        Index(['authenticated']),
    ],
    Table('session_attribute', key=('sid', 'authenticated', 'name'))[
        Column('sid', type='varchar (255)'),
        Column('authenticated', type='int'),
        Column('name', type='varchar (255)'),
        Column('value'),
        ForeignKey('sid', 'users', 'username', on_delete='CASCADE', on_update='CASCADE'),
    ],

    # Attachments
    Table('attachment', key=('type', 'id', 'project_id', 'filename'))[
        Column('type', type='varchar (255)'),
        Column('id'),
        Column('project_id', type='int', default='0'),
        Column('filename'),
        Column('size', type='int'),
        Column('time', type='int64'),
        Column('description'),
        Column('author', type='varchar (255)'),
        Column('ipnr', type='varchar (255)'),
        ForeignKey('author', 'users', 'username', on_delete='CASCADE', on_update='CASCADE'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE'),],

    # Wiki system
    Table('wiki', key=('name', 'version'))[
        Column('name', type='varchar (255)'),
        Column('version', type='int'),
        Column('time', type='int64'),
        Column('author', type='varchar (255)'),
        Column('ipnr', type='varchar (255)'),
        Column('text'),
        Column('comment'),
        Column('readonly', type='int'),
        Column('project_id', type='int', null=True),
        ForeignKey('author', 'users', 'username', on_delete='CASCADE', on_update='CASCADE'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE'),
        Index(['time'])],
    Table('syllabus_pages', key=('syllabus_id', 'pagename'))[
        Column('syllabus_id', type='int'),
        Column('pagename', type='varchar (255)'),
        ForeignKey('syllabus_id', 'syllabuses', 'id', on_delete='CASCADE'),
    ],

    # Version control cache
    Table('repository', key=('id', 'name'))[
        Column('id', type='int'),
        Column('name', type='varchar (255)'),
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
        Column('type', type='varchar (255)'),
        Column('name', type='varchar (255)'),
        Column('value', type='varchar (255)'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE')],
    Table('enum_syllabus', key=('syllabus_id', 'type', 'name'))[
        Column('syllabus_id', type='int', null=False),
        Column('type', type='varchar (255)'),
        Column('name', type='varchar (255)'),
        Column('value', type='varchar (255)'),
        ForeignKey('syllabus_id', 'syllabuses', 'id', on_delete='CASCADE')],
    Table('component', key=('project_id', 'name'))[
        Column('project_id', type='int', null=False),
        Column('name', type='varchar (255)'),
        Column('owner', type='varchar (255)'),
        Column('description'),
        ForeignKey('owner', 'users', 'username', on_delete='CASCADE', on_update='CASCADE'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE')],
    Table('milestone', key=('project_id', 'name'))[
        Column('project_id', type='int', null=False),
        Column('name', type='varchar (255)'),
        Column('due', type='int64'),
        Column('completed', type='int64'),
        Column('description'),
        Column('weight', type='int', null=False, default='0'),
        Column('rating', type='int', null=False, default='0'),
        Column('approved', type='bool', null=False, default='FALSE'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE')],
    Table('version', key=('project_id', 'name'))[
        Column('project_id', type='int', null=False),
        Column('name', type='varchar (255)'),
        Column('time', type='int64'),
        Column('description'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE')],
    Table('ticket', key='id')[
        Column('id', auto_increment=True),
        Column('project_id', type='int', null=False),
        Column('type', type='varchar (255)'),
        Column('time', type='int64'),
        Column('changetime', type='int64'),
        Column('component', type='varchar (255)'),
        Column('severity', type='varchar (255)'),
        Column('priority', type='varchar (255)'),
        Column('owner', type='varchar (255)'),
        Column('reporter', type='varchar (255)'),
        Column('cc'),
        Column('version', type='varchar (255)'),
        Column('milestone', type='varchar (255)'),
        Column('status', type='varchar (255)'),
        Column('resolution', type='varchar (255)'),
        Column('summary', type='varchar (255)'),
        Column('description'),
        Column('keywords'),
        ForeignKey('owner', 'users', 'username', on_delete='SET NULL', on_update='CASCADE'),
        ForeignKey('reporter', 'users', 'username', on_delete='SET NULL', on_update='CASCADE'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE'),
        Index(['time']),
        Index(['status']),
    ],    
    Table('ticket_change', key=('ticket', 'time', 'field'))[
        Column('ticket', type='int'),
        Column('time', type='int64'),
        Column('author', type='varchar (255)'),
        Column('field', type='varchar (255)'),
        Column('oldvalue'),
        Column('newvalue'),
        ForeignKey('ticket', 'ticket', 'id', on_delete='CASCADE'),
        ForeignKey('author', 'users', 'username', on_delete='SET NULL', on_update='CASCADE'),
        Index(['ticket']),
        Index(['time']),
    ],
    Table('ticket_custom', key=('ticket', 'name'))[
        Column('ticket', type='int'),
        Column('name', type='varchar (255)'),
        Column('value'),
        ForeignKey('ticket', 'ticket', 'id', on_delete='CASCADE'),
    ],

    # Report system
    Table('report', key='id')[
        Column('id', auto_increment=True),
        Column('author', type='varchar (255)'),
        Column('title', type='varchar (255)'),
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
        Column('approved', type='bool', default='FALSE', null=False),
        ForeignKey('username', 'users', 'username', on_delete='CASCADE', on_update='CASCADE'),
        ForeignKey(('milestone', 'project_id'), 'milestone', ('name', 'project_id'), on_delete='CASCADE', on_update='CASCADE'),],
    Table('team_milestone_evaluation_results', key=('author', 'target', 'project_id', 'milestone'))[
        Column('author', type='varchar(255)'),
        Column('target', type='varchar(255)'),
        Column('project_id', type='int'),
        Column('milestone', type='varchar(255)'),
        Column('value', type='int', null=False, default='0'),
        Column('public_comment', type='text', default="''", null=False),
        Column('private_comment', type='text', default="''", null=False),
        ForeignKey('author', 'users', 'username', on_delete='CASCADE', on_update='CASCADE'),
        ForeignKey('target', 'users', 'username', on_delete='CASCADE', on_update='CASCADE'),
        ForeignKey(('milestone', 'project_id'), 'milestone', ('name', 'project_id'), on_delete='CASCADE', on_update='CASCADE'),],
    Table('project_evaluation', key=('project_id', 'criterion'))[
        Column('project_id', type='int'),
        Column('criterion', type='varchar(255)'),
        Column('value', default="''", null=False),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE')],
]

##
## Extra SQL statements (views, types, default obligatory data, etc)
##

extra_statements = (

# Project system
'''
CREATE OR REPLACE VIEW real_projects AS
SELECT *
FROM projects
WHERE id != 0
''',
'''
CREATE OR REPLACE VIEW project_info AS
SELECT p.id project_id, p.name project_name, p.description as project_description,
       mg.active active, msr.syllabus_id syllabus_id,
       tpr.team_id team_id, tgr.group_id group_id, gmr.metagroup_id metagroup_id
FROM projects p JOIN
team_project_rel tpr ON p.id=tpr.project_id
JOIN teamgroup_rel tgr ON tgr.team_id=tpr.team_id
JOIN groupmeta_rel gmr ON gmr.group_id=tgr.group_id
JOIN metagroups mg ON mg.id=gmr.metagroup_id
JOIN metagroup_syllabus_rel msr ON msr.metagroup_id=gmr.metagroup_id
''',
'''
CREATE OR REPLACE VIEW developer_projects AS
SELECT u.id user_id, u.username username,
    t.id team_id, t.name team_name,
    p.id project_id, p.name project_name
FROM users u
JOIN team_members tm ON tm.user_id=u.id
JOIN teams t ON t.id=tm.team_id
JOIN team_project_rel tpr ON tpr.team_id=t.id
JOIN real_projects p ON p.id=tpr.project_id
JOIN project_permissions pp ON pp.project_id=p.id AND pp.username=u.username
WHERE pp.action='Developer'
''',
'''
CREATE OR REPLACE VIEW manager_projects AS
SELECT u.id user_id, u.username username,
    t.id team_id, t.name team_name,
    p.id project_id, p.name project_name
FROM group_managers gm
JOIN users u ON u.id=gm.user_id
JOIN teamgroup_rel tgr ON tgr.group_id=gm.group_id
JOIN team_project_rel tpr ON tpr.team_id=tgr.team_id
JOIN teams t ON t.id=tpr.team_id
JOIN real_projects p ON p.id=tpr.project_id
JOIN project_permissions pp ON pp.project_id=p.id AND pp.username=u.username
WHERE pp.action='Manager'
''',

# Ticket system

'''
CREATE OR REPLACE VIEW syllabus_reports AS
SELECT id, author, title, query, description, syllabus_id
FROM report
WHERE syllabus_id IS NOT NULL
''',
'''
CREATE OR REPLACE VIEW project_reports AS
SELECT id, author, title, query, description, project_id
FROM report
WHERE project_id IS NOT NULL
''',
'''
CREATE OR REPLACE VIEW global_reports AS
SELECT id, author, title, query, description
FROM report
WHERE project_id IS NULL AND syllabus_id IS NULL
''',

# User / group system

'''
CREATE OR REPLACE VIEW membership AS
SELECT u.id user_id, u.username, t.id team_id, g.id group_id, mg.id metagroup_id, mg.active meta_active
FROM users u JOIN (
    team_members tm
    JOIN teams t ON t.id=tm.team_id
    JOIN teamgroup_rel tr ON tr.team_id=t.id
    JOIN groups g ON g.id=tr.group_id
    JOIN groupmeta_rel gr ON gr.group_id=g.id
    JOIN metagroups mg ON mg.id=gr.metagroup_id
    ) ON u.id=tm.user_id
''',
'''
CREATE OR REPLACE VIEW group_hierarchy AS
SELECT mg.id metagroup_id, g.id group_id, t.id team_id
FROM metagroups mg LEFT JOIN (
    groupmeta_rel gr
    JOIN groups g ON gr.group_id=g.id
    JOIN teamgroup_rel tr ON g.id=tr.group_id
    JOIN teams t ON tr.team_id=t.id
    ) ON mg.id=gr.metagroup_id
''',
'''
CREATE OR REPLACE VIEW user_info AS
SELECT u.id id, u.username username, un.value fullname
FROM users u LEFT OUTER JOIN session_attribute un
ON un.name='name' AND u.username=un.sid
''',
)

##
## Default Reports
##

def get_reports(db):
    return (
('All Project Tickets by Milestone',
"""
List of all project tickets sorted by creation time
and grouped by milestone.
""",
"""
query:?area=project
&
group=milestone
&
order=time
&
desc=1
&
col=id
&
col=summary
&
col=owner
&
col=type
&
col=priority
&
col=severity
&
col=status
&
col=time
"""),
#----------------------------------------------------------------------------
('Active Project Tickets',
"""
List of all active project tickets sorted by priority.
""",
"""
query:?status=!closed
&
area=project
&
order=priority
&
col=id
&
col=summary
&
col=milestone
&
col=owner
&
col=type
&
col=priority
&
col=severity
&
col=status
&
col=time
"""),
#----------------------------------------------------------------------------
('Active Project Tickets by Milestone',
"""
List of all active project tickets sorted by priority
and grouped by milestone.
""",
"""
query:?status=!closed
&
group=milestone
&
area=project
&
order=priority
&
col=id
&
col=summary
&
col=status
&
col=owner
&
col=type
&
col=priority
&
col=severity
&
col=time
"""),
#----------------------------------------------------------------------------
('My Active Project Tickets',
"""
List of all active project tickets for current user
ordered by last change time.
""",
"""
query:?status=!closed
&
owner=$USER
&
area=project
&
order=changetime
&
desc=1
&
col=id
&
col=summary
&
col=status
&
col=resolution
&
col=type
&
col=priority
&
col=severity
&
col=milestone
&
col=time
&
col=changetime
"""),
#----------------------------------------------------------------------------
)


##
## Default database values
##

# (table, (column1, column2), ((row1col1, row1col2), (row2col1, row2col2)))
def get_data(db):
    return (
            # Default null project, syllabus, etc for global administration
            ('projects',
              ('id', 'name', 'description'),
                ((0, 'Global admin project', 'Global project record for administration'),)),
            ('syllabuses',
              ('id', 'name', 'description'),
                ((0, 'Global admin syllabus', 'Global syllabus record for administration'),)),
            ('metagroups',
              ('id', 'name', 'year', 'active'),
                ((0, 'Global admin metagroup', 3000, True),)),
            ('metagroup_syllabus_rel',
              ('metagroup_id', 'syllabus_id'),
                ((0, 0),)),
            ('groups',
              ('id', 'name', 'description'),
                ((0, 'Global admin group', 'Global group record for administration'),)),
            ('groupmeta_rel',
              ('metagroup_id', 'group_id'),
                ((0, 0),)),
            ('teams',
              ('id', 'name'),
                ((0, 'Global admin team'),)),
            ('teamgroup_rel',
              ('group_id', 'team_id'),
                ((0, 0),)),
            ('team_project_rel',
              ('team_id', 'project_id'),
                ((0, 0),)),

            ('users',
              ('id', 'username'),
                ((0, 'trac'),)),
            ('enum_syllabus',
              ('type', 'name', 'value', 'syllabus_id'),
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
                (('anonymous', 'WIKI_VIEW'),
                 ('authenticated', 'LOG_VIEW'),
                 ('authenticated', 'FILE_VIEW'),
                 ('authenticated', 'WIKI_CREATE'),
                 ('authenticated', 'WIKI_MODIFY'),
#                 ('authenticated', 'SEARCH_VIEW'),  # not adapted for EduTrac yet
                 ('authenticated', 'REPORT_VIEW'),
                 ('authenticated', 'REPORT_SQL_VIEW'),
                 ('authenticated', 'TICKET_VIEW'),
                 ('authenticated', 'TICKET_CREATE'),
                 ('authenticated', 'TICKET_MODIFY'),
                 ('authenticated', 'BROWSER_VIEW'),
                 ('authenticated', 'TIMELINE_VIEW'),
                 ('authenticated', 'CHANGESET_VIEW'),
                 ('authenticated', 'ROADMAP_VIEW'),
                 ('authenticated', 'MILESTONE_VIEW'))),
            ('system',
              ('name', 'value'),
                (('database_version', str(db_version)),
                 ('initial_database_version', str(db_version)))),
            ('report',
              ('author', 'title', 'query', 'description'),
                __mkreports(get_reports(db))))
