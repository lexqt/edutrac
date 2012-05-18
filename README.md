About EduTrac
=============

EduTrac is a fork of Trac. It includes some modifications and enhancements
aimed to incorporate project management system into software engineering
courses.

Main features (WIP)
-------------------

 * Multi-project.
 * User groups (3 levels: team, group, metagroup).
 * Syllabuses (something like specific configuration for project set in one metagroup).
 * More flexible ticket workflow (new operations and parameters).
 * New ticket field types and parameters (+ conversion, validation, etc).
 * Enhanced ticket queries.
 * Evaluation modules.
 * SQLAlchemy integration.

Some things are not ready yet:

 * Unit tests.
 * Search subsystem.

Dependencies
------------

### Trac Account Manager Plugin integration

1.  [Download](https://github.com/lexqt/EduTracAccountManager/downloads) and install right after EduTrac.

    You can do it with a command (executed from root):

        easy_install https://github.com/lexqt/EduTracAccountManager/tarball/master

2.  Enable plugin.

    _trac.ini_

        [components]
        acct_mgr.admin.accountmanageradminpages = enabled
        acct_mgr.api.accountmanager = enabled
        acct_mgr.db.sessionstore = enabled
        acct_mgr.guard.accountguard = enabled
        acct_mgr.notification.accountchangelistener = enabled
        acct_mgr.notification.accountchangenotificationadminpage = enabled
        acct_mgr.pwhash.htdigesthashmethod = enabled
        acct_mgr.web_ui.* = enabled
        trac.web.auth.loginmodule = disabled

3.  Activate *AccountManagerIntegration* as *password_store*.

    _trac.ini_

        [account-manager]
        password_store = AccountManagerIntegration

Deployment and installation
---------------------------

https://github.com/lexqt/edutrac/blob/edutrac/DEPLOY_RU.md (On Russian)

About Trac
==========

Trac is a minimalistic web-based software project management and bug/issue
tracking system. It provides an interface to the Subversion revision control
systems, an integrated wiki, flexible issue tracking and convenient report
facilities.

Trac is distributed using the modified BSD License.

 * For installation instructions, please see the INSTALL.
 * If you are upgrading from a previous Trac version, please read UPGRADE.

You might also want to take a look at the RELEASE and ChangeLog files for more
information.

Otherwise, the primary source of information is the main Trac web site:

 <http://trac.edgewall.org/>

We hope you enjoy it,

/The Trac Team

