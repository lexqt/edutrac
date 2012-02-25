from trac.db import Table, Column, ForeignKey, Index

name = 'project_management'
version = 1

schema = [
    Table('team_project_rel', key=('team_id',))[
        Column('team_id', type='int'),
        Column('project_id', type='int'),
        ForeignKey('team_id', 'teams', 'id', on_delete='CASCADE'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE'),
    ],
    Table('project_managers', key=('user_id', 'project_id'))[
        Column('user_id', type='int'),
        Column('project_id', type='int'),
        ForeignKey('user_id', 'users', 'id', on_delete='CASCADE'),
        ForeignKey('project_id', 'projects', 'id', on_delete='CASCADE'),
    ],
    Table('syllabuses', key=('id',))[
        Column('id', auto_increment=True),
        Column('name', type='varchar (255)', null=False),
    ],
    Table('metagroup_syllabus_rel', key=('metagroup_id',))[
        Column('metagroup_id', type='int'),
        Column('syllabus_id', type='int'),
        ForeignKey('metagroup_id', 'metagroups', 'id', on_delete='CASCADE'),
        ForeignKey('syllabus_id', 'syllabuses', 'id', on_delete='CASCADE'),
    ],
]

extra_statements = (
'''
CREATE OR REPLACE VIEW project_info AS
SELECT p.id project_id, mg.active active, msr.syllabus_id syllabus_id, tpr.team_id team_id, tgr.studgroup_id studgroup_id, gmr.metagroup_id metagroup_id
FROM projects p LEFT JOIN
team_project_rel tpr ON p.id=tpr.project_id
JOIN teamgroup_rel tgr ON tgr.team_id=tpr.team_id
JOIN groupmeta_rel gmr ON gmr.studgroup_id=tgr.studgroup_id
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
JOIN projects p ON p.id=tpr.project_id
''',
'''
CREATE OR REPLACE VIEW manager_projects AS
SELECT u.id user_id, u.username username,
	t.id team_id, t.name team_name,
	p.id project_id, p.name project_name
FROM project_managers pm
JOIN users u ON u.id=pm.user_id
JOIN projects p ON p.id=pm.project_id
JOIN team_project_rel tpr ON tpr.project_id=p.id
JOIN teams t ON tpr.team_id=t.id
''',
'''

''',
)

migrations = []
