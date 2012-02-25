from trac.core import Component, implements
from trac.env import IEnvironmentSetupParticipant
from trac.db import DatabaseManager

import db_schema


class GroupManagement(Component):
    """
    This class prepare environment for GroupManagment plugin support.
    """

    implements(IEnvironmentSetupParticipant)

    # IEnvironmentSetupParticipant methods
    def environment_created(self):
        self.found_db_version = 0
        self.upgrade_environment(self.env.get_db_cnx())
    
    def environment_needs_upgrade(self, db):
        cursor = db.cursor()
        cursor.execute("SELECT value FROM system WHERE name=%s", (db_schema.name,))
        value = cursor.fetchone()
        if not value:
            self.found_db_version = None
            return True
        else:
            self.found_db_version = int(value[0])
            if self.found_db_version < db_schema.version:
                return True
        
        # Fall through
        return False
    
    def upgrade_environment(self, db):
        db_manager, _ = DatabaseManager(self.env)._get_connector()
        
        # Insert / update version, Fetch old data
#        old_data = {} # {table_name: (col_names, [row, ...]), ...}
        cursor = db.cursor()
        if self.found_db_version is None:
            cursor.execute("INSERT INTO system (name, value) VALUES (%s, %s)", (db_schema.name, db_schema.version))
        else:
            cursor.execute("UPDATE system SET value=%s WHERE name=%s", (db_schema.version, db_schema.name))
            for tbl in db_schema.schema:
#                try:
#                    cursor.execute('SELECT * FROM %s' % tbl.name)
#                    old_data[tbl.name] = ([d[0] for d in cursor.description], cursor.fetchall())
#                except Exception, e:
#                    pass
                try:
                    cursor.execute('DROP TABLE "%s"' % tbl.name)
                except Exception, e:
                    pass
        
        # Migrate
#        for vers, migration in db_schema.migrations:
#            if self.found_db_version in vers:
#                self.log.info('GroupManagement: Running migration %s', migration.__doc__)
#                migration(old_data)          
        
        # Create plugin tables
        for tbl in db_schema.schema:
            for sql in db_manager.to_sql(tbl):
                cursor.execute(sql)
            for sql in db_schema.extra_statements:
                cursor.execute(sql)
            
            # Try to reinsert any old data
#            if tbl.name in old_data:
#                data = old_data[tbl.name]
#                sql = 'INSERT INTO %s (%s) VALUES (%s)' % \
#                      (tbl.name, ','.join(data[0]), ','.join(['%s'] * len(data[0])))
#                for row in data[1]:
#                    try:
#                        cursor.execute(sql, row)
#                    except Exception, e:
#                        pass

