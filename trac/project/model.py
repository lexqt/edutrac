from trac.core import TracError
from trac.resource import ResourceNotFound
from trac.util.translation import _


def simplify_whitespace(name):
    """Strip spaces and remove duplicate spaces within names"""
    if name:
        return ' '.join(name.split())
    return name



class Project(object):

    def __init__(self, env, id=None, db=None):
        self.env = env
        if id:
            if not db:
                db = self.env.get_read_db()
            cursor = db.cursor()
            cursor.execute("""
                SELECT name, description FROM projects WHERE id=%s
                """, (id,))
            row = cursor.fetchone()
            if not row:
                raise ResourceNotFound(_('Project #%(pid)s does not exist.',
                                         pid=id))
            self.id = id
            self.name = row[0] or None
            self.description = row[1] or ''
        else:
            self.id = None
            self.name = None
            self.description = None

    exists = property(lambda self: self.id is not None)

    @classmethod
    def check_exists(cls, env, pid):
        pid = int(pid)
        db = env.get_read_db()
        cursor = db.cursor()
        cursor.execute('SELECT 1 FROM projects WHERE id=%s LIMIT 1', (pid,))
        return bool(cursor.rowcount)

    def delete(self, db=None):
        """Delete the project."""
        assert self.exists(self.env, self.id), 'Cannot delete non-existent project'

        @self.env.with_transaction(db)
        def do_delete(db):
            cursor = db.cursor()
            self.env.log.info('Deleting project #%s' % self.id)
            cursor.execute("DELETE FROM projects WHERE id=%s", (self.id,))
            self.id = None

    def insert(self, db=None):
        """Insert a new project."""
        assert not self.exists(self.env, self.id), 'Cannot insert existing project'
        self.name = simplify_whitespace(self.name)
        if not self.name:
            raise TracError(_('Invalid project name.'))

        @self.env.with_transaction(db)
        def do_insert(db):
            cursor = db.cursor()
            self.env.log.debug("Creating new project '%s'" % self.name)
            cursor.execute("""
                INSERT INTO projects (name, description)
                VALUES (%s, %s)
                RETURNING id
                """, (self.name, self.description))
            pid = cursor.fetchone()[0]
            self.id = pid

    def update(self, db=None):
        """Update the project.

        The `db` argument is deprecated in favor of `with_transaction()`.
        """
        assert self.exists(self.env, self.id), 'Cannot update non-existent project'
        self.name = simplify_whitespace(self.name)
        if not self.name:
            raise TracError(_('Invalid project name.'))

        @self.env.with_transaction(db)
        def do_update(db):
            cursor = db.cursor()
            self.env.log.info('Updating project "%s"' % self.name)
            cursor.execute("""
                UPDATE projects SET name=%s, description=%s
                WHERE id=%s
                """, (self.name, self.description, self.id))

