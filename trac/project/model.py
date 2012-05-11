from trac.core import TracError
from trac.config import Configuration
from trac.util.translation import _

import os
import os.path
from trac.util import create_file

from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import relationship, backref
from trac.db_sqlalchemy import ModelBase, team_project_rel, metagroup_syllabus_rel

from trac.user.model import Team, Metagroup


__all__ = ['Project', 'Syllabus']



class Project(ModelBase):
    '''Project model class

    Also provides methods to create/remove project
    configuration.

    '''

    __tablename__ = 'projects'

    # declare fields
    id          = Column('id', Integer, primary_key=True, autoincrement=True)
    name        = Column('name', String(255), nullable=False, unique=True)
    description = Column('description', Text, server_default='')

    # relations
    team = relationship(Team, secondary=team_project_rel, uselist=False,
                        backref=backref('project', uselist=False))

    @classmethod
    def check_exists(cls, env, pid):
        '''Check if project `pid` exists. Raise error on false.'''
        pid = int(pid)
        db = env.get_read_db()
        cursor = db.cursor()
        cursor.execute('SELECT 1 FROM projects WHERE id=%s LIMIT 1', (pid,))
        if not cursor.rowcount:
            raise TracError(_("Project #%(id)s doesn't exist", id=pid))

    @classmethod
    def config_path(cls, env, id):
        return os.path.join(env.path, 'conf', 'project', 'id%s.ini' % id)

    @classmethod
    def add_config(cls, env, id):
        '''Add empty project configuration
        or do nothing if configuration exists'''
        path = cls.config_path(env, id)
        if os.path.exists(path):
            return
        create_file(path)
        config = Configuration(path)
        config.save()

    @classmethod
    def remove_config(cls, env, id):
        '''Remove project configuration'''
        path = cls.config_path(env, id)
        if os.path.exists(path):
            os.remove(path)

    @classmethod
    def revoke_permission(cls, env, id, username, action=None):
        '''Revoke project permission (or perm group) `action`
        (or all project permissions if `action` is not specified)
        for specified project `id` and `username`.'''

        q = '''
            DELETE FROM project_permissions
            WHERE project_id=%s AND username=%s {and_action}
        '''
        args = [id, username]
        if action:
            ext = 'AND action=%s'
            args.append(action)
        else:
            ext = ''
        @env.with_transaction()
        def do_revoke(db):
            cursor = db.cursor()
            cursor.execute(q.format(and_action=ext), args)

    @classmethod
    def grant_permission(cls, env, id, username, action):
        '''Grant project permission (or perm group) `action`
        for specified project `id` and `username`.
        Do nothing if user already has specified permission.'''

        args = (id, username, action)
        @env.with_transaction()
        def do_revoke(db):
            cursor = db.cursor()
            cursor.execute('''
                SELECT 1
                FROM project_permissions
                WHERE project_id=%s AND username=%s AND action=%s
                ''', args)
            if cursor.rowcount:
                return
            cursor.execute('''
                INSERT INTO project_permissions
                (project_id, username, action)
                VALUES (%s, %s, %s)
            ''', args)

    @classmethod
    def set_permission(cls, env, id, username, action, grant=True):
        '''Grant or revoke project permission based on `grant`
        boolean argument.'''
        if grant:
            return cls.grant_permission(env, id, username, action)
        else:
            return cls.revoke_permission(env, id, username, action)



class Syllabus(ModelBase):
    '''Syllabus model class

    Also provides methods to create/remove syllabus
    configuration.

    '''

    __tablename__ = 'syllabuses'

    # declare fields
    id          = Column('id', Integer, primary_key=True, autoincrement=True)
    name        = Column('name', String(255), nullable=False)
    description = Column('description', Text, server_default='')

    # relations
    metagroups = relationship(Metagroup, secondary=metagroup_syllabus_rel,
                              backref=backref('syllabus', uselist=False))

    def __init__(self, name, description=''):
        self.name = name
        self.description = description

    @classmethod
    def config_path(cls, env, id):
        return os.path.join(env.path, 'conf', 'syllabus', 'id%s.ini' % id)

    @classmethod
    def add_config(cls, env, id):
        '''Add default syllabus configuration
        (with global configuration inheritance section)
        or do nothing if configuration exists.'''
        path = cls.config_path(env, id)
        if os.path.exists(path):
            return
        create_file(path)
        config = Configuration(path)
        cls.set_default_config(env, config)
        config.save()

    @classmethod
    def set_default_config(cls, env, config):
        config['inherit'].set('file', '../trac.ini')
        config.set_defaults(env, only_switcher=True)
        from trac.ticket.default_workflow import load_workflow_config_snippet
        load_workflow_config_snippet(config, 'team-workflow.ini')

    @classmethod
    def remove_config(cls, env, id):
        '''Remove syllabus configuration'''
        path = cls.config_path(env, id)
        if os.path.exists(path):
            os.remove(path)

