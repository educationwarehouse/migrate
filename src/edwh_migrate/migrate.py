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
import os
import sys
import time
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
        migrate=False,
        migrate_enabled=False,
        appname=" ".join(sys.argv),
        long_running=False,
        dal_class=None,
):
    if dal_class is None:
        # default: pydal.DAL
        # (alternative: py4web.core.DAL)
        dal_class = DAL

    try:
        uri = os.environ["MIGRATE_URI"]
    except KeyError as e:
        raise InvalidConfigException("$MIGRATE_URI not found in environment.") from e
    is_postgres = uri.startswith('postgres')
    driver_args = dict(
        application_name=appname,
    ) if is_postgres else {}
    if not long_running and is_postgres:
        driver_args["keepalives"] = 1
    db = dal_class(
        uri,
        migrate=migrate,
        migrate_enabled=migrate_enabled,
        driver_args=driver_args,
        pool_size=1,
    )
    if is_postgres and not long_running:
        db.executesql("PGPOOL SET client_idle_limit = 10;")
    # https://www.pgpool.net/docs/latest/en/html/sql-pgpool-set.html
    # make this connection able to live longer, because the functions can take over 30s
    # to perform the job.
    # db.executesql("PGPOOL SET client_idle_limit = 3600;")

    db.define_table(
        "ewh_implemented_features",
        Field("name", unique=True),
        Field("installed", "boolean", default=False),
        Field("last_update_dttm", "datetime", default=datetime.datetime.now()),
    )
    try:
        db(db.ewh_implemented_features).count()
    except psycopg2.errors.UndefinedTable as e:
        raise DatabaseNotYetInitialized(
            "ewh_implemented_features is missing.", db
        ) from e
    return db


def migration(func: callable = None, requires: list[str] | None = None):
    if func is None and requires:
        # requires is opgegeven, dus decorator teruggeven.
        if callable(requires):
            # bij een enkelvoudige requirement, alleen een functie, neem de naam van de functie
            required_names = [requires.__name__]
        else:
            # als niet callable, dan moet het een list zijn van functies, dus pak alle namen van die functies.
            required_names = [_.__name__ for _ in requires]

        def decorator(decorated: callable):
            @wraps(decorated)
            def met_requires(*p, **kwp):
                # check requirements
                db = setup_db()
                installed = [
                    row.installed
                    for row in db(
                        db.ewh_implemented_features.name.belongs(required_names)
                    ).select("installed")
                ]
                # check of alle requirements wel gevonden zijn:
                if len(installed) != len(required_names):
                    db.close()
                    print(decorated.__name__, "REQUIREMENTS NOT MET")
                    raise RequimentsNotMet("requirements not met")
                if not all(installed):
                    db.close()
                    print(decorated.__name__, "REQUIREMENTS NOT MET")
                    raise RequimentsNotMet("requirements not met")
                return decorated(*p, **kwp)

            registered_functions[decorated.__name__] = met_requires
            return met_requires

        return decorator
    if func:
        registered_functions[func.__name__] = func
    return func


def should_run(db, name):
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
    print("RECOVER_DATABASE_FROM_BACKEND  started ")
    prepared_sql_path = "/data/database_to_restore.sql"
    prepared_sql_path_gz = f"{prepared_sql_path}.gz"
    prepared_sql_path_xz = f"{prepared_sql_path}.xz"
    if os.path.exists(prepared_sql_path):
        print("RECOVER:", prepared_sql_path, "exists. ")
        # option C
        unpack = plumbum.local["cat"][prepared_sql_path]
    elif os.path.exists(prepared_sql_path_xz):
        print("RECOVER:", prepared_sql_path_xz, "exists. ")
        # option C
        unpack = plumbum.local["xzcat"][prepared_sql_path_xz]
    elif os.path.exists(prepared_sql_path_gz):
        print("RECOVER:", prepared_sql_path_gz, "exists. ")
        # option C
        unpack = plumbum.local["zcat"][prepared_sql_path_gz]
    else:
        print("RECOVER:", prepared_sql_path, " not found.")
        # option A and B
        raise NotImplementedError(
            "Recovering from the .7z file is not implemented at the moment. "
        )
        # local_backup = "/data/database_to_restore.7z"
        # if not os.path.exists(local_backup):
        #     print("RECOVER:", local_backup, "not found. Downloading from B2")
        #     # option A
        #     b2_application_key_id = os.environ["B2_APPLICATION_KEY_ID"]
        #     b2_application_key = os.environ["B2_APPLICATION_KEY"]
        #     b2_file_id = os.environ["B2_FILE_ID"]
        #     b2_file_password = os.environ["B2_FILE_PASSWORD"]
        #     # craft a reference to the executable
        #     b2 = plumbum.local["b2"]
        #     # authorize the account
        #     print("RECOVER: authenticating b2")
        #     b2(
        #         "authorize-account",
        #         b2_application_key_id,
        #         b2_application_key,
        #     )
        #     # download the file, it's not that big (30+mb) at the time of writing.
        #     # b2 doesn't support outputting to stdout, so an intermediate file is required
        #     print("RECOVER: downloading backup file to ", local_backup)
        #     b2("download-file-by-id", b2_file_id, local_backup)
        #     print("RECOVER: download done")
        # # option A en B mere gere
        # # prepare the 7z command
        # archive_password = base64.b64decode(b2_file_password).decode()
        # unpack = plumbum.local["7z"][
        #     "x", "-so", "-p{}".format(archive_password), local_backup
        # ]
    # option A, B and C merge here
    # unpack is now the command to cat the sql to stdout
    # whih is piped to psql ot perform the recovery

    # parse the db uri to find hostname and port and such to
    # feed to pqsl as commandline arguments
    uri = urllib.parse.urlparse(os.environ["MIGRATE_URI"])
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

    # prepare the psql command
    psql = plumbum.local["psql"]["-h", hostname, "-U", username, "-d", database]
    if password:
        raise InvalidConfigException(
            "Postgresql Password NOT SUPPORTED for automatic migrations... "
        )
    if port:
        psql = psql["-p", port]

    # combine both
    cmd = unpack | psql

    print("UNPACKING AND INSTALLING DATABASE:", cmd)
    # noinspection PyStatementEffect
    # is plumbum syntax
    cmd() > "/dev/null"
    print("phew. that took a while")

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
            try:
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
                    db.commit()
                else:
                    print("ran: ", name, " and failed. ")
                    successes.append(False)
                    # try a rollback, because we should ignore whatever happend
                    db_for_this_function.rollback()
                    # and close because this connection is not used any longer.
                    db_for_this_function.close()

            except:
                raise
            # except:
            #     print(sys.exc_info())
            #     # ignore elke error!
            #     exception_type, exception_value, exception_traceback = sys.exc_info()
            #     print(f"ERROR: {exception_type}({exception_value} ")
            #     print(exception_traceback)
            #     success = False
            #     successes.append(False)
            #     raise
        else:
            print("already installed. ")
    # db(db.ewh_implemented_features.name == 'feature_2').delete()
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
            if Path('migrations.py').exists():
                print("migrations.py exists, importing @migration decorated functions.")
                sys.path.insert(0, os.getcwd())
                # importing the migrations.py file will register the functions
                import migrations
                print(f'{len(registered_functions)} migrations discovered')

            print("starting migrate hook")
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

