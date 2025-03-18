# coding=utf-8
# SPDX-FileCopyrightText: 2023-present Remco <remco@educationwarehouse.nl>
#
# SPDX-License-Identifier: MIT
"""
This file contains most of the (core) code.

When writing new tasks, make sure:
 * ! executesql() returns tuples, explicitly use as_dict or as_ordered_dict to have easy acces for results
 * ! arguments and placeholders use the `where gid = %(gid)s` syntax, where gid should be a key in the `placeholders`
   argument given to executesql
 * ! make sure to use schema reference:
   - public."user"
   - public.item
   forget and fail...
"""

import contextlib
import datetime
import importlib
import inspect
import os
import pathlib
import sqlite3
import sys
import time
import traceback
import typing
import urllib
import urllib.parse
import warnings
from collections import OrderedDict
from functools import wraps
from pathlib import Path
from typing import Optional

import configuraptor
import dotenv
import plumbum
from configuraptor import Singleton, alias, asdict, postpone
from configuraptor.errors import ConfigErrorMissingKey, IsPostponedError
from dotenv import find_dotenv
from pydal import DAL, Field
from pydal.objects import Table
from tabulate import tabulate

from .constants import CURRENT_MIGRATION
from .postgres import PostgresError, PostgresUndefinedTable

try:
    from typedal import TypeDAL
except ImportError:  # pragma: no cover
    TypeDAL = DAL

Migration: typing.TypeAlias = typing.Callable[[DAL], bool]


class MigrationStore(Singleton):
    """
    Singleton that stores registered migrations (names, functions and ordering).
    """

    _order: list[str]
    _functions: list[Migration]
    _names: set[str]

    def __init__(self) -> None:
        self._order = []
        self._functions = []
        # ^ can be zipped together
        self._names = set()

    def has(self, name: str) -> bool:
        return name in self._names

    def register_ordered(self, fn: Migration, requires: typing.Iterable[str] = ()) -> Migration:
        """Register a migration function with ordering and dependencies.

        Order migrations to ensure they are run in the correct sequence,
        handling dependencies correctly.

        Args:
           fn: The migration function to register.
           requires: A sequence of migration names or functions that
             `fn` depends on. The migrations in `requires` must be
             ordered before `fn`.

        Returns:
           The registered migration function.

        Usage:
            used by @migration, you probably don't want to call this yourself.

        Raises:
           ValueError: If a migration with the same name is attempted to be registered.
           ValueError: If `fn` depends on an unknown migration.
        """

        fn_name = fn.__name__

        if migrations.has(fn_name):
            raise ValueError(f"Duplicate migration name {fn_name}")

        if requires:
            ranks = []
            for dep in requires:
                dep_name = dep if isinstance(dep, str) else dep.__name__

                if dep_name not in self._order:
                    raise ValueError(f"{fn_name} depends on {dep_name} which is unknown.")

                ranks.append(self._order.index(dep_name))

            rank = max(ranks) + 1

        else:
            rank = len(migrations)

        self._order.insert(rank, fn_name)
        self._functions.insert(rank, fn)
        self._names.add(fn_name)

        return fn

    def list(self) -> OrderedDict[str, Migration]:
        """
        Helper function to list all @registered migrations.

        (does NOT auto-import migrations)
        """
        return OrderedDict(iter(self))

    def __iter__(self) -> typing.Iterator[tuple[str, Migration]]:
        """
        Usage:
            `for name, function in migrations:`
        """
        # return iter(self.list().items())
        return zip(
            self._order,
            self._functions,
        )

    def reset(self) -> None:
        self._order.clear()
        self._functions.clear()
        self._names.clear()

    def __len__(self) -> int:
        return len(self._order)

    def __bool__(self) -> bool:
        return any(self._order)


migrations = MigrationStore()

TEN_MINUTES = 600


class BaseEDWHMigrateException(BaseException):
    """
    Most top-level exception class for this module.

    Not caught by `except Exception`.
    """


class EDWHMigrateException(BaseEDWHMigrateException, Exception):
    """
    Common exception class for this module.

    Is caught by `except Exception`.
    """


class UnknownConfigException(BaseEDWHMigrateException):
    """
    Not currently used.
    """


class InvalidConfigException(BaseEDWHMigrateException):
    """
    Thrown when not all requires settings (e.g. database uri) can be found.
    """


class DatabaseNotYetInitialized(BaseEDWHMigrateException):
    """
    Thrown when trying to access the implemented features table before setting it up.
    """


class RequimentsNotMet(BaseEDWHMigrateException):
    """
    Thrown when a migration depends on some requirements, which have not been succesfully installed yet.
    """


class MigrateLockExists(EDWHMigrateException):
    """
    Thrown when trying to migrate but a lock file is already present.

    This indicates the migration has already happened.
    """


class MigrationFailed(EDWHMigrateException):
    """
    Raised when a migration fails for any reason.
    """


class Config(configuraptor.TypedConfig, configuraptor.Singleton):
    """
    These options can be set via pyproject.toml or .env (or a combination).

    Use the [tool.migrate] key.
    Either - or _ can be used in the keys and they can be in any case.
    """

    migrate_uri: str = postpone()
    schema_version: Optional[str]
    redis_host: Optional[str]
    migrate_cat_command: Optional[str]
    database_to_restore: str = "/data/database_to_restore.sql"
    migrate_table: str = "ewh_implemented_features"
    flag_location: str = "/flags"
    schema: str | bool = "public"
    create_flag_location: bool = False
    db_folder: Optional[str] = None
    migrations_file: str = "migrations.py"
    use_typedal: bool = False

    db_uri: str = alias("migrate_uri")

    def __repr__(self) -> str:
        """
        Represent the class by dumping its data.
        """
        data = asdict(self, with_top_level_key=False)
        return f"<Config{data}>"


def _get_config() -> Config:
    """
    First try config from env, then fallback to pyproject.
    """
    dotenv.load_dotenv(find_dotenv(usecwd=True))
    try:
        return Config.load("pyproject.toml", key="tool.migrate")
    except (configuraptor.errors.ConfigError, FileNotFoundError):
        return Config.from_env(load_dotenv=False)


def get_config() -> Config:
    """
    Get the whole config or a specific key.
    """
    config = _get_config()
    config.update_from_env()  # extend toml defaults with env secrets

    return config


T_Dal = typing.TypeVar("T_Dal", bound=DAL)


def define_ewh_implemented_features(db: DAL, rname: str = "ewh_implemented_features") -> Table:
    """
    Define the required table.

    Can be used by pydal2sql to generate a CREATE TABLE statement:
    Example:
        pydal2sql create src/edwh_migrate/migrate.py
            --magic
            --function 'define_ewh_implemented_features(db, "custom_rname")'
            --dialect sqlite
            --format edwh-migrate
    """
    return db.define_table(
        "ewh_implemented_features",
        Field("name", unique=True),
        Field("installed", "boolean", default=False),
        Field("last_update_dttm", "datetime", default=datetime.datetime.now),
        rname=rname,
    )


@typing.overload
def setup_db(
    migrate: bool = False,
    migrate_enabled: bool = False,
    appname: str = " ".join(sys.argv),
    long_running: bool | int = False,
    dal_class: None = None,
    impl_feat_table_name: Optional[str] = None,
    folder: Optional[str] = None,
    config: Optional[Config] = None,
    remove_migrate_tablefile: bool = False,
) -> DAL:
    """
    If `dal_class` is not filled in, a normal DAL instance is returned.
    """


@typing.overload
def setup_db(
    migrate: bool = False,
    migrate_enabled: bool = False,
    appname: str = " ".join(sys.argv),
    long_running: bool | int = False,
    dal_class: typing.Type[T_Dal] = DAL,
    impl_feat_table_name: Optional[str] = None,
    folder: Optional[str] = None,
    config: Optional[Config] = None,
    remove_migrate_tablefile: bool = False,
) -> T_Dal:
    """
    If `dal_class` is passed, an instance of that class will be returned.
    """


def setup_db(
    migrate: bool = False,
    migrate_enabled: bool = False,
    appname: str = " ".join(sys.argv),
    long_running: bool | int = False,
    dal_class: typing.Type[T_Dal] | None = None,
    impl_feat_table_name: Optional[str] = None,
    folder: Optional[str] = None,
    config: Optional[Config] = None,
    remove_migrate_tablefile: bool = False,
) -> T_Dal | DAL:
    """
    Connect to the database and return a DAL object.

    When using postgres, the application name is set to the appname argument, long lasting connections are enabled
    when using long_running, to avoid PGPOOL closing the connection during unpacking of a larger backup file.

    This function will also search for the ewh_implemented_features table,
    which is used to keep track of which migrations have been attempted and applied.

    If this table is not found, an DatabaseNotYetInitialized exception is raised. This is handled in the
    activate_migrations function to allow for the database to be restored from a backup before continuing.

    While migrating, functions registered with the @migration(requires=...) decorator applied, will reconnect using
    `setup_db()` without any arguments.

    :param migrate: migrate is normally turned off, but if you want to run migrations, set this to True
    :param migrate_enabled: normally migrate is turned off, but if you want to run migrations, set this to True
    :param appname: name of this application to register on postgres connections, default: " ".join(sys.argv)
    :param long_running: bool or int to indicate the number of seconds to keep the connection alive
        using pgpool set_client_idle_limit
    :param dal_class: optional DAL class, will use DAL if not given
    :param impl_feat_table_name: optional custom table name for ewh_implemented_features
    :param folder: directory to store sql log, table files etc
    :param config: existing Config object. If not passed, get_config will be called.
    :param remove_migrate_tablefile: remove the ewh_implemented_features.table file if it exists?

    :return: database connection
    """
    try:
        config = config or get_config()

        uri = config.migrate_uri
    except (KeyError, ConfigErrorMissingKey, IsPostponedError) as e:
        raise InvalidConfigException("$MIGRATE_URI not found in environment.") from e

    if dal_class is None:
        # default: pydal.DAL
        # (alternatives: py4web.core.DAL, typedal.TypeDAL, typedal.py4web.DAL)
        dal_class = TypeDAL if config.use_typedal else DAL

    is_postgres = uri.startswith("postgres")
    driver_args: dict[str, typing.Any] = {}
    if is_postgres:
        driver_args["application_name"] = appname
        if not long_running:
            driver_args["keepalives"] = 1

    db = dal_class(
        uri,
        migrate=migrate,
        migrate_enabled=migrate_enabled,
        driver_args=driver_args,
        pool_size=1,
        folder=folder or config.db_folder,
    )

    if is_postgres and long_running:
        # https://www.pgpool.net/docs/latest/en/html/sql-pgpool-set.html
        # make this connection able to live longer, because the functions can take over 30s
        # to perform the job.
        # db.executesql("PGPOOL SET client_idle_limit = 3600;")
        print("Setting up for long running connection")
        try:
            db.executesql(f"PGPOOL SET client_idle_limit = {long_running if str(long_running).isdigit() else 3600};")
        except PostgresError:
            # maybe not using PGPOOL, ignore
            db.rollback()

    if remove_migrate_tablefile:
        tablefile_path = Path(db._folder or ".") / f"{db._uri_hash}_ewh_implemented_features.table"
        tablefile_path.unlink(missing_ok=True)

    define_ewh_implemented_features(db, impl_feat_table_name or config.migrate_table)
    db.commit()

    try:
        db(db.ewh_implemented_features).count()
    except (PostgresUndefinedTable, sqlite3.OperationalError) as e:
        db.rollback()
        raise DatabaseNotYetInitialized(f"{config.migrate_table} is missing.", db) from e
    return db


@typing.overload
def migration(
    func: None = None,
    requires: list[Migration | str] | Migration | None = None,
) -> typing.Callable[[Migration], Migration]:
    """
    Allows calling the decorator with parentheses.

    Example:
        @migration()
        def my_migration_1(): ...
    """


@typing.overload
def migration(
    func: Migration,
    requires: list[Migration | str] | Migration | None = None,
) -> Migration:
    """
    Allows calling @migration without parens.
    """


def migration(
    func: Migration | None = None,
    requires: list[Migration | str] | Migration | None = None,
) -> Migration | typing.Callable[[Migration], Migration]:
    """
    Decorator to register a function as a migration function.

    :param func: function to register as a migration function
    :param requires: list of function names that need to be applied before this function can be applied.

    Example:
        @migration
        def my_migration_function(db):
            db.executesql("select 1")
            return True # or False, if the migration failed. On true db.commit() will be performed.
    """
    if func is None and requires:
        # requires is given, so return the decorator that will test if the requirements are met before
        # executing the decorated function, when it's time to really execute the function.

        if callable(requires):  # noqa: SIM108
            # when a single requirement is given, and it is a function, take the name of the function
            required_names = [requires if isinstance(requires, str) else requires.__name__]
        else:
            # if requires is not callable, then it must be a list of functions, so take the names of those functions.
            required_names = [_ if isinstance(_, str) else _.__name__ for _ in requires]

        def decorator(decorated: Migration) -> Migration:
            @wraps(decorated)
            def with_requires(*p: typing.Any, **kwp: typing.Any) -> bool:
                # check requirements
                db = setup_db()
                installed = (
                    db(
                        db.ewh_implemented_features.name.belongs(required_names)
                        & (db.ewh_implemented_features.installed == True)
                    )
                    .select("installed")
                    .column("installed")
                )

                # check if all requirements are in the list of installed features
                if len(installed) != len(required_names) or not all(installed):
                    db.close()
                    print(decorated.__name__, "REQUIREMENTS NOT MET")
                    raise RequimentsNotMet("requirements not met")

                return decorated(*p, **kwp)

            return migrations.register_ordered(with_requires, required_names)

        return decorator

    if func:
        return migrations.register_ordered(func)

    return migration


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


def recover_database_from_backup(set_schema: Optional[str | bool] = None, config: Optional[Config] = None) -> None:
    """
    Recover a database backup.

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
    config = config or get_config()
    set_schema = set_schema or config.schema

    print("RECOVER_DATABASE_FROM_BACKEND started ")
    prepared_sql_path = pathlib.Path(config.database_to_restore)

    name, extension = os.path.splitext(prepared_sql_path)
    for ext in [".sql", ".sql.gz", ".gz", "sql.xz", ".xz", ".NOTFOUND"]:
        prepared_sql_path = pathlib.Path(name + ext)
        if prepared_sql_path.exists():
            break

    if ext == ".NOTFOUND":
        raise FileNotFoundError(prepared_sql_path)

    extension = prepared_sql_path.suffix.lower()

    cat_command = {
        ".sql": "cat",
        ".xz": "xzcat",
        ".gz": "zcat",
    }.get(extension, config.migrate_cat_command)
    if not cat_command:  # pragma: no cover
        raise NotImplementedError(f"Extension {extension} not supported for {prepared_sql_path}")
    unpack = plumbum.local[cat_command][prepared_sql_path]

    # unpack is now the command to cat the sql to stdout
    # which is piped to psql to perform the recovery

    # parse the db uri to find hostname and port and such to
    # feed to pqsl as commandline arguments
    uri = urllib.parse.urlparse(config.migrate_uri)

    if is_postgres := uri.scheme.startswith("postgres"):
        # prepare the psql command
        psql = plumbum.local["psql"][config.migrate_uri]
        sql_consumer = psql
    else:
        filepath = uri.path
        if "///" not in config.migrate_uri:
            # else absolute path, don't strip!
            filepath = filepath.strip("/")

        sqlite_database_path = pathlib.Path(uri.netloc) / pathlib.Path(filepath)
        sql_consumer = plumbum.local["sqlite3"][sqlite_database_path]
    # combine both
    cmd = unpack | sql_consumer

    print("UNPACKING AND INSTALLING DATABASE:", cmd)
    # noinspection PyStatementEffect
    # is plumbum syntax
    cmd() > "/dev/null"
    print("Done unpacking and feeding to", cmd)

    if is_postgres and set_schema:
        echo = plumbum.local["echo"]
        cmd = echo[f"SET search_path TO {set_schema};"] | sql_consumer
        print("For postgres: set schema to public:", cmd)
        cmd()


def try_setup_db(config: Optional[Config] = None, max_time: int = TEN_MINUTES) -> typing.Optional[DAL]:
    """
    Handle multiple scenario's such as an existing db, a db that can be loaded from a backup or a fully new db.
    """
    started = time.time()
    while time.time() - started < max_time:
        try:
            db = setup_db(config=config)
            print("activate_migrations connected after", time.time() - started, "seconds.")

            db.commit()
            # without an error, all *should* be well...
            return db
        except DatabaseNotYetInitialized as e:  # pragma: no cover
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
                return setup_db()

            except FileNotFoundError as e:
                with contextlib.suppress(DatabaseNotYetInitialized):
                    print(f"RECOVER: {e} not found. Starting from scratch.")
                    return setup_db(migrate=True, migrate_enabled=True)
                with contextlib.suppress(DatabaseNotYetInitialized):
                    print("RECOVER: Failed. Starting from scratch with new .table file.")
                    return setup_db(migrate=True, migrate_enabled=True, remove_migrate_tablefile=True)

            except Exception as e:
                print("RECOVER: database recovery went wrong:", e)
            break  # don't retry
        except Exception as e:  # pragma: no cover
            print(
                "activate_migrations failed to connect to database. "
                "sleeping and retrying in 3 seconds. will try for 10 min."
            )
            print(e)
            time.sleep(3)

    # shouldn't happen :(
    return None  # pragma: no cover


def mark_migration(db: DAL, name: str, installed: bool) -> int | None:
    """
    Store the result of a migration in the implemented_features table.
    """
    new_id = db.ewh_implemented_features.update_or_insert(
        db.ewh_implemented_features.name == name,
        name=name,
        installed=installed,
        last_update_dttm=datetime.datetime.now(),
    )  # type: int | None
    return new_id


def activate_migrations(config: Optional[Config] = None, max_time: int = TEN_MINUTES) -> bool:
    """
    Start the migration process, don't wait for a lock.
    """
    config = config or get_config()

    db = try_setup_db(config, max_time=max_time)
    if not db:
        raise ValueError("No db could be set up!")

    successes = []

    # perform migrations
    for name, function in migrations:
        print("test:", name)
        if should_run(db, name):
            print("run: ", name)
            # black magic fuckery via env
            # but ewh_implemented doesn't really support adding new columns
            # (such as active)
            # + this doesn't require database lookups so it's more performant too :)
            os.environ[CURRENT_MIGRATION] = name

            # create a new database connection
            # because there could be tables being defined,
            # and we want all the functions to be siloed and not
            # have database schema dependencies and collisions.
            db_for_this_function = setup_db()
            try:
                result = function(db_for_this_function)
                successes.append(result)
            except Exception:
                print(f"failed: {name} in {inspect.getfile(function)}:{inspect.getsourcelines(function)[1]}")
                print(traceback.format_exc(), file=sys.stderr)
                return False

            if result:
                # commit the change to db
                db_for_this_function.commit()
                # close this specific cursor, it's not used any longer.
                db_for_this_function.close()
                print("ran: ", name, "successfully. ")
                # alleen bij success opslaan dat er de feature beschikbaar is
                mark_migration(db, name, installed=True)
            else:
                print("ran: ", name, " and failed. ")
                successes.append(False)
                # try a rollback, because we should ignore whatever happend
                db_for_this_function.rollback()
                # and close because this connection is not used any longer.
                db_for_this_function.close()
                mark_migration(db, name, installed=False)
            db.commit()
        else:
            print("already installed. ")

    db.close()

    # clean redis whenever possible
    # reads REDIS_MASTER_HOST from the environment
    if redis_host := config.redis_host:
        import redis

        if not redis_host.startswith("redis://"):
            redis_host = f"redis://{redis_host}"

        r = redis.Redis.from_url(redis_host)
        keys = r.keys()
        print(f"Removing {len(keys)} keys from redis.")
        for key in keys:
            del r[key]
        print("done")
    return any(successes) and all(successes)


@contextlib.contextmanager
def schema_versioned_lock_file(
    flag_location: str | Path | None = None, create_flag_location: bool = False, config: Optional[Config] = None
) -> typing.Generator[Path | None, None, None]:
    """
    Context manager that creates a lock file for the current schema version.
    """
    config = config or get_config()

    flag_location = Path(flag_location or config.flag_location)
    if not flag_location.exists():
        if create_flag_location or config.create_flag_location:
            flag_location.mkdir()
        else:
            raise NotADirectoryError(
                f"Flag directory {flag_location} does not exist. "
                f"Please create it or set `create_flag_location` to True."
            )

    if (schema_version := config.schema_version) is None:
        print("No schema version found, ignoring any lock files.")
        yield None
    else:
        print("testing migrate lock file with the current version")
        lock_file = flag_location / f"migrate-{schema_version}.complete"
        print("Using lock file: ", lock_file)
        if lock_file.exists():
            print("migrate: lock file already exists, migration should be completed. Aborting migration")
            raise MigrateLockExists(str(lock_file))
        else:
            try:
                yield lock_file
                # executed after successful with block:
                lock_file.touch()
            except MigrationFailed:
                # remove the lock file, so that the migration can be retried.
                print("ERROR: migration failed, removing the lock file.")
                print(f"Check the {config.migrate_table} table for details.")
                lock_file.unlink(missing_ok=True)

            except BaseException:
                # since another exception was raised, reraise it for the stack trace.
                lock_file.unlink(missing_ok=True)
                raise


def temporary_import(name: str) -> None:
    """
    Prevent caching of module (relevant in pytest)
    """
    importlib.import_module(name)
    del sys.modules[name]


def import_migrations(args: list[str], config: Config) -> bool:
    """
    Import defined migrations in a number of ways, without executing them yet.

    Migrations get stored in `registered_functions`.
    """
    if args:
        print(f"Using argument {args[0]} as a reference to the migrations file.")
        # use the first argument as a reference to the migrations file
        # or the folder where the migrations file is stored
        arg = Path(args[0])
        if arg.exists() and arg.is_file():
            print(f"importing migrations from {arg}")
            sys.path.insert(0, str(arg.parent))
            # importing the migrations.py file will register the functions
            temporary_import(arg.stem)
            return True
        elif arg.exists() and arg.is_dir():
            print(f"importing migrations from {arg}/migrations.py")
            sys.path.insert(0, str(arg))
            # importing the migrations.py file will register the functions
            temporary_import("migrations")
            return True
        else:
            print(f"ERROR: no migrations found at {arg}", file=sys.stderr)
            return False

    elif config.migrations_file and (arg := Path(config.migrations_file)) and arg.exists():
        print(f"importing migrations from {arg.absolute()}")
        sys.path.insert(0, str(arg.parent))
        # importing the migrations.py file will register the functions
        temporary_import(arg.stem)

        return True

    elif Path("migrations.py").exists():
        print("migrations.py exists, importing @migration decorated functions.")
        sys.path.insert(0, os.getcwd())
        # importing the migrations.py file will register the functions
        import migrations  # noqa F401: semantic import here

        return True
    else:
        print(f"ERROR: no migrations found at {os.getcwd()}", file=sys.stderr)
        return False


def list_migrations(config: Config, args: Optional[list[str]] = None) -> OrderedDict[str, Migration]:
    """
    Helper function for external usage to list all @registered migrations.
    """
    if not migrations:
        import_migrations(args or [], config)

    return migrations.list()


def print_migrations_status_table(config: Config) -> None:  # pragma: no cover
    """
    Output a table to display each registered migration with status (success, failed, new).
    """
    db = setup_db(config=config)

    migrations = list_migrations(config)
    if not migrations:
        # nothing to do, exit with error:
        exit(1)

    # take the content from the database to put it inside a dict.
    rows = db(db.ewh_implemented_features).select().as_dict("name")
    table = []

    print(f"{len(migrations)} migrations discovered:")

    for migration_name in migrations:
        # Print out the content for every row where the name has been found in registered_functions.
        if migration_name in rows:
            status = "succeeded" if rows[migration_name]["installed"] else "failed"
            table.append([migration_name, status, rows[migration_name]["last_update_dttm"]])
        else:
            table.append([migration_name, "missing", "N/A"])

    print(tabulate(table, headers=["Migration Name", "Status", "Last Updated"]))


def _console_hook(args: list[str], config: Optional[Config] = None) -> int:  # pragma: no cover
    if "-h" in args or "--help" in args:
        print(
            """
        Execute migrate to run the migration in `migrations.py` from the current working directory.

        The database connection url is read from the MIGRATE_URI environment variable.
        It should be a pydal compatible connection string.

        use -l or --list to get a list of migrations.

        ## Testing migrations using sqlite

        Create a test setup using sqlite3:
        $sqlite3 test.db  "create table ewh_implemented_features(id, name, installed, last_update_dttm);"
        $export MIGRATE_URI='sqlite://test.db'

        """
        )
        return 0
    config = config or get_config()
    if "-l" in args or "--list" in args:
        print_migrations_status_table(config)
        return 0

    success = False
    try:
        # get the versioned lock file path, as the config performs the environment variable expansion
        with schema_versioned_lock_file(config=config):
            if not import_migrations(args, config):
                # nothing to do, exit with error:
                return 1

            print("starting migrate hook")
            print(f"{len(migrations)} migrations discovered")

            if not activate_migrations(config):
                raise MigrationFailed("Not every migration succeeded.")

            print("migration completed successfully, marking success.")
            success = True
    except MigrateLockExists:
        # that's okay, should still have exit code 0
        success = True
    except BaseException as e:
        warnings.warn(str(e), category=RuntimeWarning, source=e)
        success = False

    # with exit code:
    return 0 if success else 1


def console_hook() -> None:  # pragma: no cover
    """
    Activated by migrate shell script, sets a lock file before activate_migrations.

    lockfile: '/flags/migrate-{os.environ["SCHEMA_VERSION"]}.complete'
    """
    exit(_console_hook(sys.argv[1:]))


# ------------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------------
# ----------------------------- registered functions ---------------------------------------------
# ------------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------------

# @migration
# def start_from_scratch(db: DAL) -> bool:
#     print(f"String from scratch using {db}")
#     return True
