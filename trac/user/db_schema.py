from trac.db import Table, Column, ForeignKey, Index

name = 'user_management'
version = 1

schema = [
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
        Column('user_id', type='int'),
        Column('team_id', type='int'),
        ForeignKey('user_id', 'users', 'id', on_delete='CASCADE'),
        ForeignKey('team_id', 'teams', 'id', on_delete='CASCADE'),
    ],
    Table('teamgroup_rel', key=('studgroup_id', 'team_id'))[
        Column('studgroup_id', type='int'),
        Column('team_id', type='int'),
        ForeignKey('studgroup_id', 'student_groups', 'id', on_delete='CASCADE'),
        ForeignKey('team_id', 'teams', 'id', on_delete='CASCADE'),
    ],
    Table('groupmeta_rel', key=('metagroup_id', 'studgroup_id'))[
        Column('metagroup_id', type='int'),
        Column('studgroup_id', type='int'),
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
]

extra_statements = (
'''
DROP TYPE IF EXISTS group_level
''',
'''
CREATE TYPE group_level AS ENUM ('team', 'stud', 'meta')
''',
'''
CREATE OR REPLACE VIEW membership AS
SELECT u.id user_id, u.username, t.id team_id, sg.id studgroup_id, mg.id metagroup_id,  mg.active meta_active
FROM users u LEFT JOIN (
    team_members tm
    JOIN teams t ON t.id=tm.team_id
    JOIN teamgroup_rel tr ON tr.team_id=t.id
    JOIN student_groups sg ON sg.id=tr.studgroup_id
    JOIN groupmeta_rel gr ON gr.studgroup_id=sg.id
    JOIN metagroups mg ON mg.id=gr.metagroup_id
    ) ON u.id=tm.user_id
''',
# optimized
#SELECT u.id user_id, u.username, tm.team_id team_id, tr.studgroup_id studgroup_id, mg.id metagroup_id,  mg.active meta_active
#FROM users u LEFT JOIN (
#    team_members tm
#    JOIN teamgroup_rel tr ON tr.team_id=tm.team_id
#    JOIN groupmeta_rel gr ON gr.studgroup_id=tr.studgroup_id
#    JOIN metagroups mg ON mg.id=gr.metagroup_id
#    ) ON u.id=tm.user_id
'''
CREATE OR REPLACE VIEW group_hierarchy AS
SELECT mg.id metagroup_id, sg.id studgroup_id, t.id team_id
FROM metagroups mg LEFT JOIN (
    groupmeta_rel gr
    JOIN student_groups sg ON gr.studgroup_id=sg.id
    LEFT JOIN teamgroup_rel tr ON sg.id=tr.studgroup_id
    LEFT JOIN teams t ON tr.team_id=t.id
    ) ON mg.id=gr.metagroup_id
''',
'''
CREATE OR REPLACE FUNCTION get_group_table(lvl group_level) RETURNS varchar AS $$
BEGIN
    CASE lvl
        WHEN 'team' THEN
            RETURN 'teams';
        WHEN 'stud' THEN
            RETURN 'student_groups';
        WHEN 'meta' THEN
            RETURN 'metagroups';
    END CASE;
END;
$$ LANGUAGE plpgsql;
''',
'''
CREATE OR REPLACE FUNCTION get_group_column(lvl group_level) RETURNS varchar AS $$
BEGIN
    CASE lvl
        WHEN 'team' THEN
            RETURN 'team_id';
        WHEN 'stud' THEN
            RETURN 'studgroup_id';
        WHEN 'meta' THEN
            RETURN 'metagroup_id';
    END CASE;
END;
$$ LANGUAGE plpgsql;
''',
'''
CREATE OR REPLACE FUNCTION check_membership(username varchar, gid integer, lvl group_level) RETURNS bool AS $$
DECLARE
    colname varchar;
    res integer;
BEGIN
    SELECT get_group_column(lvl) INTO colname;
    EXECUTE 'SELECT 1 FROM membership
        WHERE username=$1 AND ' || quote_ident(colname) || '=$2
        LIMIT 1'
        INTO res USING username, gid;
    RETURN res IS NOT NULL;
END;
$$ LANGUAGE plpgsql;
''',
'''
CREATE OR REPLACE FUNCTION check_group_exists(gid integer, lvl group_level) RETURNS bool AS $$
DECLARE
    tabname varchar;
    res integer;
BEGIN
    SELECT get_group_table(lvl) INTO tabname;
    EXECUTE 'SELECT 1 FROM ' || quote_ident(tabname) || '
        WHERE id=$1
        LIMIT 1'
        INTO res USING gid;
    RETURN res IS NOT NULL;
END;
$$ LANGUAGE plpgsql;
''',
'''
CREATE OR REPLACE FUNCTION check_group_has_parent(ch_gid integer, ch_lvl group_level, par_gid integer, par_lvl group_level) RETURNS bool AS $$
DECLARE
    ch_colname  varchar;
    par_colname varchar;
    res integer;
BEGIN
    IF ch_lvl >= par_lvl THEN
        RAISE 'Precondition ''Child lvl < Parent lvl'' failed: % >= %', ch_lvl, par_lvl
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    SELECT get_group_column(ch_lvl)  INTO ch_colname;
    SELECT get_group_column(par_lvl) INTO par_colname;
    EXECUTE 'SELECT 1 FROM group_hierarchy
        WHERE ' || quote_ident(ch_colname) || '=$1 AND ' || quote_ident(par_colname) || '=$2
        LIMIT 1'
        INTO res USING ch_gid, par_gid;
    RETURN res IS NOT NULL;
END;
$$ LANGUAGE plpgsql;
''',
'''

''',
'''

''',
'''

''',
)

migrations = []
