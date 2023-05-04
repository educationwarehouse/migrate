# coding=utf-8
# SPDX-FileCopyrightText: 2023-present Remco <remco@educationwarehouse.nl>
#
# SPDX-License-Identifier: MIT
"""
When writing new tasks, make sure:
 * /!\ executesql() returns tuples, explicitly use as_dict or as_ordered_dict to have easy acces for results
 * /!\ arguments and placeholders use the `where gid = %(gid)s` syntax, where gid should be a key in the `placeholders`
   argument given to executesql
 * /!\ make sure to use schema reference:
   - public."user"
   - public.item
   forget and fail...

"""
import contextlib
import datetime
import importlib
import os
import pathlib
import sqlite3
import sys
import time
import typing
import urllib
import urllib.parse
from collections import OrderedDict
from functools import wraps
from pathlib import Path

import plumbum
import psycopg2
import psycopg2.errors
import redis
from pydal import DAL, Field

registered_functions = OrderedDict()

class UnknownConfigException(BaseException):
    pass


class InvalidConfigException(BaseException):
    pass


class DatabaseNotYetInitialized(BaseException):
    pass


class RequimentsNotMet(BaseException):
    pass


class MigrateLockExists(Exception):
    pass

class MigrationFailed(Exception):
    pass


def setup_db(
        migrate: bool = False,
        migrate_enabled: bool = False,
        appname: str = " ".join(sys.argv),
        long_running: bool | int = False,
        dal_class: type = None,
):
    '''

    Connect to the database and return a DAL object.

    When using postgres, the application name is set to the appname argument, long lasting connections are enabled
    when using long_running, to avoid PGPOOL closing the connection during unpacking of a larger backup file.

    This function will also search for the ewh_implemented_features table, which is used to keep track of which migrations
    have been attempted and applied.

    If this table is not found, an DatabaseNotYetInitialized exception is raised. This is handled in the
    activate_migrations function to allow for the database to be restored from a backup before continuing.

    While migrating, functions registered with the @migration(requires=...) decorator applied, will reconnect using
    `setup_db()` without any arguments.

    :param migrate: migrate is normally turned off, but if you want to run migrations, set this to True
    :param migrate_enabled: normally migrate is turned off, but if you want to run migrations, set this to True
    :param appname: name of this application to register on postgres connections, default: " ".join(sys.argv)
    :param long_running: bool or int to indicate the number of seconds to keep the connection alive using pgpool set_client_idle_limit
    :param dal_class: optional DAL class, will use DAL if not given
    :return: database connection
    '''
    if dal_class is None:
        # default: pydal.DAL
        # (alternative: py4web.core.DAL)
        dal_class = DAL

    try:
        uri = os.environ["MIGRATE_URI"]
    except KeyError as e:
        raise InvalidConfigException("$MIGRATE_URI not found in environment.") from e
    is_postgres = uri.startswith('postgres')
    driver_args = {}
    if is_postgres:
        driver_args['application_name'] = appname
        if not long_running:
            driver_args["keepalives"] = 1

    db = dal_class(
        uri,
        migrate=migrate,
        migrate_enabled=migrate_enabled,
        driver_args=driver_args,
        pool_size=1,
    )
    if is_postgres and not long_running:
        # https://www.pgpool.net/docs/latest/en/html/sql-pgpool-set.html
        # make this connection able to live longer, because the functions can take over 30s
        # to perform the job.
        # db.executesql("PGPOOL SET client_idle_limit = 3600;")
        with contextlib.suppress(Exception):
            db.executesql(f"PGPOOL SET client_idle_limit = {long_running if str(long_running).isdigit() else 3600};")

    db.define_table(
        "ewh_implemented_features",
        Field("name", unique=True),
        Field("installed", "boolean", default=False),
        Field("last_update_dttm", "datetime", default=datetime.datetime.now()),
    )
    try:
        db(db.ewh_implemented_features).count()
    except (psycopg2.errors.UndefinedTable, sqlite3.OperationalError) as e:
        raise DatabaseNotYetInitialized(
            "ewh_implemented_features is missing.", db
        ) from e
    return db


def migration(func: callable = None, requires: list[callable] | typing.Callable | None = None):
    """
    Decorator to register a function as a migration function.

    example:

    @migration
    def my_migration_function(db):
        db.executesql("select 1")
        return True # or False, if the migration failed. On true db.commit() will be performed.

    :param func: function to register as a migration function
    :param requires: list of function names that need to be applied before this function can be applied.

    """
    if func is None and requires:
        # requires is given, so return the decorator that will test if the requirements are met before
        # executing the decorated function, when it's time to really execute the function.
        if callable(requires):
            # when a single requirement is given, and it is a function, take the name of the function
            required_names = [requires.__name__]
        else:
            # if requires is not callable, then it must be a list of functions, so take the names of those functions.
            required_names = [_.__name__ for _ in requires]

        def decorator(decorated: callable):
            @wraps(decorated)
            def with_requires(*p, **kwp):
                # check requirements
                db = setup_db()
                installed = [
                    row.installed
                    for row in db(
                        db.ewh_implemented_features.name.belongs(required_names) &
                        (db.ewh_implemented_features.installed == True)
                    ).select("installed")
                ]
                # check if all requirements are in the list of installed features
                if len(installed) != len(required_names):
                    db.close()
                    print(decorated.__name__, "REQUIREMENTS NOT MET")
                    raise RequimentsNotMet("requirements not met")
                if not all(installed):
                    db.close()
                    print(decorated.__name__, "REQUIREMENTS NOT MET")
                    raise RequimentsNotMet("requirements not met")
                return decorated(*p, **kwp)

            registered_functions[decorated.__name__] = with_requires
            return with_requires

        return decorator
    if func:
        registered_functions[func.__name__] = func
    return func


def should_run(db: DAL, name: str) -> bool:
    """
    Checks if a migration function should be run.

    :param db: database connection
    :param name: name of the migration function
    :return: whether the migration function should be run (if not installed) or not (when installed).
    """
    resultset = db(db.ewh_implemented_features.name == name).select()
    row = resultset.first() if resultset else None
    return row.installed is False if row else True


def recover_database_from_backup():
    """
    Handles 3 situations:
    a) /data/database_to_restore.sql exists:
       just recover the database (uses cat)
    b) /data/database_to_restore.xz exists:
       unpacks and recovers the file (uses xzcat)
    c) /data/database_to_restore.gz exists:
       unpacks and recovers the file (uses zcat)
    d) no file exists:
        tries to recover using an un7zipped file,
        possibly downloaded from backblaze, but this code
        is stale.
    Effectively running something like:
        A,B)  7z x -so -p"secret" db.7z | psql -h  127.0.0.1 -U postgres -d backend
          C) cat /data/database_to_restore.sql | psql -h  127.0.0.1 -U postgres -d backend

    """
    print("RECOVER_DATABASE_FROM_BACKEND started ")
    prepared_sql_path = pathlib.Path(os.getenv('DATABASE_TO_RESTORE', "/data/database_to_restore.sql"))
    if not prepared_sql_path.exists():
        raise FileNotFoundError(prepared_sql_path)
    extension = prepared_sql_path.suffix.lower()

    cat_command = {
        '.sql': 'cat',
        '.xz': 'xzcat',
        '.gz': 'zcat',
    }.get(extension, os.getenv('MIGRATE_CAT_COMMAND'))
    if not cat_command:
        raise NotImplementedError(f"Extension {extension} not supported for {prepared_sql_path}")
    unpack = plumbum.local[cat_command][prepared_sql_path]

    # unpack is now the command to cat the sql to stdout
    # which is piped to psql to perform the recovery

    # parse the db uri to find hostname and port and such to
    # feed to pqsl as commandline arguments
    uri = urllib.parse.urlparse(os.environ["MIGRATE_URI"])
    is_postgres = uri.scheme.startswith("postgres")
    database = str(uri.path).lstrip("/")
    netloc = str(uri.netloc)
    if "@" in netloc:
        username_password, hostname_port = netloc.split("@")
    else:
        username_password = "postgres"
        hostname_port = netloc
    if ":" in username_password:
        username, password = username_password.split(":")
    else:
        username = username_password
        password = None
    if ":" in hostname_port:
        hostname, port = hostname_port.split(":")
    else:
        hostname = hostname_port
        port = "5432"

    if is_postgres:
        # prepare the psql command
        psql = plumbum.local["psql"]["-h", hostname, "-U", username, "-d", database]
        if password:
            raise InvalidConfigException(
                "Postgresql Password NOT SUPPORTED for automatic migrations... "
            )
        if port:
            psql = psql["-p", port]
        sql_consumer = psql
    else:
        sqlite_database_path = pathlib.Path(uri.netloc) / pathlib.Path(uri.path.strip('/'))
        sql_consumer = plumbum.local["sqlite3"][sqlite_database_path]
    # combine both
    cmd = unpack | sql_consumer

    print("UNPACKING AND INSTALLING DATABASE:", cmd)
    # noinspection PyStatementEffect
    # is plumbum syntax
    cmd() > "/dev/null"
    print("Done unpacking and feeding to", cmd)

    # os.unlink(local_backup)


def activate_migrations():
    """Start the migration process, don't wait for a lock"""
    started = time.time()
    while time.time() - started < 600:
        try:
            db = setup_db()
            print(
                "activate_migrations connected after", time.time() - started, "seconds."
            )

            db.commit()
            # without an error, all *should* be well...
            break
        except DatabaseNotYetInitialized as e:
            # the connection succeeded, but when encountering an empty databse,
            # the features table will not be found, and this will raise an exception
            # this error is to be expected, since the database is not yet recovered...
            print("table not found, starting database restore")
            # recover the erroneous database connection to start database recovery.
            _, db = e.args
            # clear the current connection from errors :
            db.rollback()
            try:
                print("RECOVER: attempting recovery from a backup")
                db.close()
                recover_database_from_backup()
                # give db-0 a while to catch up
                time.sleep(10)
                # reconnect to the database, since the above operation takes longer than timeout period on dev machines.
                db = setup_db()
            except Exception as e:
                print("RECOVER: database recovery went wrong:", e)
            break  # don retry
        except Exception as e:
            print(
                "activate_migrations failed to connect to database. "
                "sleeping and retrying in 3 seconds. will try for 10 min."
            )
            print(e)
            time.sleep(3)

    successes = []
    # perform migrations
    for name, function in registered_functions.items():
        print("test:", name)
        if should_run(db, name):
            print("run: ", name)
            # create a new database connection
            # because there could be tables being defined,
            # and we want all the functions to be siloed and not
            # have database schema dependencies and collisions.
            db_for_this_function = setup_db()
            result = function(db_for_this_function)
            successes.append(result)
            if result:
                # commit the change to db
                db_for_this_function.commit()
                # close this specific cursor, it's not used any longer.
                db_for_this_function.close()
                print("ran: ", name, "successfully. ")
                # alleen bij success opslaan dat er de feature beschikbaar is
                db.ewh_implemented_features.update_or_insert(
                    db.ewh_implemented_features.name == name,
                    name=name,
                    installed=True,
                    last_update_dttm=datetime.datetime.now(),
                )
            else:
                print("ran: ", name, " and failed. ")
                successes.append(False)
                # try a rollback, because we should ignore whatever happend
                db_for_this_function.rollback()
                # and close because this connection is not used any longer.
                db_for_this_function.close()
                db.ewh_implemented_features.update_or_insert(
                    db.ewh_implemented_features.name == name,
                    name=name,
                    installed=False,
                    last_update_dttm=datetime.datetime.now(),
                )
            db.commit()
        else:
            print("already installed. ")

    db.close()

    # clean redis whenever possible
    # reads REDIS_MASTER_HOST from the environment
    if redis_host := os.getenv("REDIS_HOST", None):
        r = redis.Redis(redis_host)
        keys = r.keys()
        print(f"Removing {len(keys)} keys from redis.")
        for key in keys:
            del r[key]
        print("done")
    return all(successes)


@contextlib.contextmanager
def schema_versioned_lock_file():
    """
    Context manager that creates a lock file for the current schema version.
    """
    if (schema_version := os.getenv("SCHEMA_VERSION")) is None:
        print('No schema version found, ignoring any lock files.')
        yield
    else:
        print("testing migrate lock file with the current version")
        lock_file = Path(f'/flags/migrate-{schema_version}.complete')
        print("Using lock file: ", lock_file)
        if lock_file.exists():
            print(
                "migrate: lock file already exists, migration should be completed. Aborting migration"
            )
            raise MigrateLockExists(str(lock_file))
        else:
            # create the lock asap, to avoid racing conditions with other possible migration processes
            lock_file.touch()
            try:
                yield
            except MigrationFailed:
                # remove the lock file, so that the migration can be retried.
                print("ERROR: migration failed, removing the lock file.\n"
                      "Check the ewh_implemented_features table for details.")
                lock_file.unlink()

            except BaseExceptionGroup:
                # since another exception was raised, reraise it for the stack trace.
                lock_file.unlink()
                raise


def console_hook():
    """
    Activated by migrate shell script, sets a lock file before activate_migrations.

    lockfile: '/flags/migrate-{os.environ["SCHEMA_VERSION"]}.complete'
    """
    # get the versioned lock file path, as the config performs the environment variable expansion

    if '-h' in sys.argv or '--help' in sys.argv:
        print('''
        Execute migrate to run the migration in `migrations.py` from the current working directory. 
        
        The database connection url is read from the MIGRATE_URI environment variable. It should be a 
        pydal compatible connection string. 
        
        
        ## Testing migrations using sqlite
        
        Create a test setup using sqlite3: 
        $sqlite3 test.db  "create table ewh_implemented_features(id, name, installed, last_update_dttm);"
        $export MIGRATE_URI='sqlite://test.db'
        
        ''')
        exit(0)

    with contextlib.suppress(MigrateLockExists):
        with schema_versioned_lock_file():
            arg = None
            if sys.argv[1:]:
                print(f'Using argument {sys.argv[1]} as a reference to the migrations file.')
                # use the first argument as a reference to the migrations file
                # or the folder where the migrations file is stored
                arg = pathlib.Path(sys.argv[1])
                if arg.exists() and arg.is_file():
                    print(f"importing migrations from {arg}")
                    sys.path.insert(0, str(arg.parent))
                    # importing the migrations.py file will register the functions
                    importlib.import_module(arg.stem)
                elif arg.exists() and arg.is_dir():
                    print(f"importing migrations from {arg}/migrations.py")
                    sys.path.insert(0, str(arg))
                    # importing the migrations.py file will register the functions
                    importlib.import_module('migrations')
                else:
                    print(f"ERROR: no migrations found at {arg}", file=sys.stderr)
                    exit(1)
            elif Path('migrations.py').exists():
                print("migrations.py exists, importing @migration decorated functions.")
                sys.path.insert(0, os.getcwd())
                # importing the migrations.py file will register the functions
                import migrations
            else:
                print(f"ERROR: no migrations found at {os.getcwd()}", file=sys.stderr)
                exit(1)
            print("starting migrate hook")
            print(f'{len(registered_functions)} migrations discovered')
            if activate_migrations():
                print("migration completed successfully, marking success.")
            else:
                raise MigrationFailed('Not every migration succeeded.')

# ------------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------------
# ----------------------------- registered functions ---------------------------------------------
# ------------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------------

# @migration
# def start_from_scratch(db: DAL) -> bool:
#     print(f"String from scratch using {db}")
#     return True

