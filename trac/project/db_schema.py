from trac.db import Table, Column, ForeignKey, Index

name = 'project_management'
version = 1

schema = [
]

extra_statements = (
'''
CREATE OR REPLACE VIEW real_projects AS
SELECT *
FROM projects
WHERE id != 0
''',
'''
CREATE OR REPLACE VIEW project_info AS
SELECT p.id project_id, mg.active active, msr.syllabus_id syllabus_id, tpr.team_id team_id, tgr.studgroup_id studgroup_id, gmr.metagroup_id metagroup_id
FROM real_projects p LEFT JOIN
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
JOIN real_projects p ON p.id=tpr.project_id
''',
#'''
#CREATE OR REPLACE VIEW manager_projects AS
#SELECT u.id user_id, u.username username,
#	t.id team_id, t.name team_name,
#	p.id project_id, p.name project_name
#FROM project_managers pm
#JOIN users u ON u.id=pm.user_id
#JOIN real_projects p ON p.id=pm.project_id
#JOIN team_project_rel tpr ON tpr.project_id=p.id
#JOIN teams t ON tpr.team_id=t.id
#''',
'''
CREATE OR REPLACE VIEW manager_projects AS
SELECT u.id user_id, u.username username,
	t.id team_id, t.name team_name,
	p.id project_id, p.name project_name
FROM studgroup_managers sgm
JOIN users u ON u.id=sgm.user_id
JOIN teamgroup_rel tgr ON tgr.studgroup_id=sgm.studgroup_id
JOIN team_project_rel tpr ON tpr.team_id=tgr.team_id
JOIN teams t ON t.id=tpr.team_id
JOIN real_projects p ON p.id=tpr.project_id
''',
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
'''

''',
'''

''',
)

migrations = []
