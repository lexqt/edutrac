Развертывание и установка
=========================

Инструкция составлена для развертывания и установки EduTrac на Linux сервере
на примере дистрибутива Ubuntu Server 11.10. Все написанное далее применимо
и к любым Debian дистрибутивам при наличии необходимых минимальных версий пакетов.

В качестве основного веб-сервера выбран Apache 2 с модулем mod_wsgi.

При выборе других веб-серверов, для более тонкой настройки и пр.
полезно будет прочитать официальную документацию по установке Trac 0.12:

 * [Установка Trac](http://trac.edgewall.org/wiki/0.12/TracInstall)
 * [Trac и mod_wsgi (документация Trac)](http://trac.edgewall.org/wiki/TracModWSGI)
 * [Trac и mod_wsgi (документация mod_wsgi)](http://code.google.com/p/modwsgi/wiki/IntegrationWithTrac)
 * [Подключение PostgreSQL](http://trac.edgewall.org/wiki/DatabaseBackend#Postgresql)


Установка пакетов
----------------------------------

Apache и Subversion: `apache2 subversion libapache2-svn libapache2-mod-wsgi`

PostgreSQL: `postgresql-9.1 postgresql`

Python и модули: `python2.7 python2.7-dev python python-subversion python-psycopg2 libc6 python-setuptools python-babel python-docutils python-pygments`

Прочее: `graphviz`

Установка пакетов:

    apt-get install <список пакетов>

__Здесь и далее если не сказано иное, то выполнение команд производить от имени пользователя root (или через `sudo`).__


Установка Trac и модулей
------------------------

Зависимости:

    easy_install "Genshi>=0.6,<0.7dev"
    easy_install "lazy>=1.0"
    easy_install "SQLAlchemy>=0.7"
    easy_install "FormEncode>=1.2.4"

Обязательные:

    easy_install https://github.com/lexqt/edutrac/tarball/edutrac
    easy_install https://github.com/lexqt/EduTracAccountManager/tarball/master

Крайне рекомендуемые:

    easy_install https://github.com/lexqt/EduTracSvnAdmin/tarball/master
    easy_install https://github.com/lexqt/TracMenusPlugin/tarball/master
    easy_install https://github.com/lexqt/EduTracIniAdminPanel/tarball/master
    easy_install http://trac-hacks.org/svn/translatedpagesmacro/0.11/#egg=TranslatedPages

Опциональные:

    easy_install https://github.com/lexqt/EduTracMasterTickets/tarball/master
    easy_install https://github.com/lexqt/EduTracTimingAndEstimation/tarball/master
    easy_install https://github.com/lexqt/EduTracGanttCalendar/tarball/trunk
    easy_install https://github.com/lexqt/EduTracTeamCalendar/tarball/master
    easy_install https://github.com/lexqt/EduTracMetrix/tarball/master
    easy_install https://github.com/lexqt/EduTracTicketWorklog/tarball/master


Создание пользователей и групп
------------------------------

    adduser trac
    addgroup subversion
    adduser trac subversion
    adduser www-data subversion


Подготовка директорий среды
---------------------------

Все команды в этом подразделе должны выполняться от имени пользователя trac:

    sudo su trac

Создание директорий:

    mkdir -p /home/trac/env/main
    mkdir /home/trac/env/main/svn
    mkdir /home/trac/public_html

### Подготовка hook-скриптов для SVN ###

Скачайте https://github.com/downloads/lexqt/edutrac/trac-svn-hooks.tar.gz и
распакуйте содержимое (3 скрипта) в директорию `/home/trac/env/main/svn`:

    cd /home/trac/env/main/svn
    wget https://github.com/downloads/lexqt/edutrac/trac-svn-hooks.tar.gz
    tar xzf trac-svn-hooks.tar.gz
    rm trac-svn-hooks.tar.gz


Подготовка Subversion
---------------------

    mkdir /home/svn
    chown -R www-data:subversion /home/svn/
    chmod -R g+rws /home/svn/

Создание файла для паролей:

    touch /etc/subversion/passwd
    chown -R www-data:subversion /etc/subversion/passwd
    chmod -R g+rw /etc/subversion/passwd

Добавление учетной записи SVN (выполняется от имени пользователя trac):

    sudo su trac
    htpasswd -b /etc/subversion/passwd admin <svn admin password>

Добавление репозитория (выполняется от имени пользователя trac):

    sudo su trac
    REPOS_NAME=<имя репозитория>
    TRAC_ENV_SVN=/home/trac/env/main/svn
    mkdir /home/svn/$REPOS_NAME
    svnadmin create /home/svn/$REPOS_NAME
    cp $TRAC_ENV_SVN/post-commit /home/svn/$REPOS_NAME/hooks/
    cp $TRAC_ENV_SVN/post-revprop-change /home/svn/$REPOS_NAME/hooks/
    cp $TRAC_ENV_SVN/trac-svn-hook /home/svn/$REPOS_NAME/hooks/

Если планируется разграничивать доступ к репозиториям, то выполнить команды:

    touch /etc/subversion/authz.conf
    chown -R www-data:subversion /etc/subversion/authz.conf
    chmod -R g+rw /etc/subversion/authz.conf

Пример содержания файла authz.conf:

    [groups]
    training = dev1, dev2, dev3
    
    [/]
    * = 
    admin = rw
    
    [training:/]
    @training = rw

В дальнейшем создание, изменение, удаление пользователей SVN и
редактирование authz.conf можно осуществлять через административный
интерфейс EduTrac с помощью плагина EduTracSvnAdmin.


Подготовка PostgreSQL
---------------------

Если необходим доступ к БД извне, то:

1. В файле `/etc/postgresql/9.1/main/postgresql.conf`:

        listen_addresses = '127.0.0.1,<IP адрес сервера>'

1. В файле `/etc/postgresql/9.1/main/pg_hba.conf`:

        host trac trac 0.0.0.0 0.0.0.0 md5

Создание пользователя и базы данных:

    sudo su postgres
    createuser -D -P -R -S trac
    createdb -O trac trac


Создание среды EduTrac
----------------------

Все команды в этом подразделе должны выполняться от имени пользователя trac:

    sudo su trac

Инициализация среды:

    trac-admin /home/trac/env/main/ initenv

При запросе строки подключения к БД введите:

    postgres://trac:<пароль PostgreSQL пользователя trac>@localhost/trac

Изменение прав для директории с логами:

    chown -R trac:www-data /home/trac/env/main/log
    chmod -R 771 /home/trac/env/main/log

Первоначальная настройка EduTrac может быть проведена с нуля, но
рекомендуется воспользоваться примером конфигурационного файла по ссылке:
https://github.com/downloads/lexqt/edutrac/trac.ini
и предварительно отредактировать `/home/trac/env/main/conf/trac.ini`.

Копирование статических ресурсов:

    trac-admin /home/trac/env/main/ deploy /home/trac/public_html/

__Данную команду необходимо будет выполнять каждый раз при подключении новых плагинов и модулей.__

Подготовка WSGI приложения:

    mkdir /home/trac/public_html/wsgi
    cd /home/trac/public_html/wsgi
    wget https://github.com/downloads/lexqt/edutrac/trac.wsgi


Подключение Account Manager
---------------------------

Все команды в этом подразделе должны выполняться от имени пользователя trac:

    sudo su trac

Убедитесь, что в файле конфигурации `trac.ini` активированы компоненты:

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

Установите *AccountManagerIntegration* как основное хранилище паролей:

    [account-manager]
    password_store = AccountManagerIntegration

Добавление учетной записи администратора:

    trac-admin /home/trac/env/main/
    account add admin <пароль> <полное имя> <email>
    permission add G admin TRAC_ADMIN


Конфигурирование виртуального хоста Apache
------------------------------------------

Отредактировать файл `/etc/apache2/sites-available/default`:

    <VirtualHost *:80>
            ServerAdmin <email администратора>
            ServerName <используемое доменное имя>
    
            <Location /svn>
                    DAV svn
                    SVNParentPath /home/svn
                    AuthType Basic
                    AuthName "Subversion Repository"
                    AuthUserFile /etc/subversion/passwd
                    SVNPathAuthz on
                    AuthzSVNAccessFile /etc/subversion/authz.conf
                    Require valid-user
            </Location>
    
            WSGIDaemonProcess tracapp user=trac group=trac
            WSGIScriptAlias /trac /home/trac/public_html/wsgi/trac.wsgi
    
            <Directory /home/trac/public_html/wsgi>
                WSGIProcessGroup tracapp
                WSGIApplicationGroup %{GLOBAL}
                Order deny,allow
                Allow from all
            </Directory>
    
            Alias /trac/chrome "/home/trac/public_html/htdocs"
    
            <Directory /home/trac/public_html/htdocs/>
                    Options -Indexes FollowSymLinks MultiViews
                    AllowOverride None
                    Order allow,deny
                    allow from all
            </Directory>
    
    
            ErrorLog /var/log/apache2/error.log
    
            # Possible values include: debug, info, notice, warn, error, crit,
            # alert, emerg.
            LogLevel warn
    
            CustomLog /var/log/apache2/access.log combined
    
    </VirtualHost>

Директивы `SVNPathAuthz` и `AuthzSVNAccessFile` указывать, только если
используется файл `authz.conf`.

