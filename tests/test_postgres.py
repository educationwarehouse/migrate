import shutil
import tempfile
from pathlib import Path

import psycopg2
import pytest
from configuraptor import Singleton
from pydal import DAL
from testcontainers.postgres import PostgresContainer

from src.edwh_migrate import (
    Config,
    activate_migrations,
    migrate,
    recover_database_from_backup,
)


def rmdir(path: Path):
    shutil.rmtree(path)


DB_NAME = "edwh_migrate_test"

postgres = PostgresContainer("postgres:16-alpine", dbname=DB_NAME)


@pytest.fixture(scope="module", autouse=True)
def psql(request):
    # defer teardown:
    request.addfinalizer(postgres.stop)

    postgres.start()
    # note: ONE PostgresContainer with scope module can be used,
    # if you try to use containers in a function scope, it will not work.
    # thus, this clean_db fixture is added to cleanup between tests:


@pytest.fixture(scope="function", autouse=True)
def clean_db():
    # Connection URI
    from sqlalchemy_utils.functions import create_database, drop_database

    uri = postgres.get_connection_url()
    drop_database(uri)
    create_database(uri)

    Singleton.clear()


@pytest.fixture()
def conn_str():
    conn_str = postgres.get_connection_url()
    # make pydal-friendly:
    return "postgres://" + conn_str.split("://")[-1]


@pytest.fixture()
def tempdir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def test_setup_on_psql_not_long_running(conn_str: str, tempdir: str):
    config = Config.load(dict(migrate_uri=conn_str, db_folder=tempdir))

    assert config.migrate_uri.startswith("postgres://")

    db = migrate.setup_db(
        config=config, migrate=True, migrate_enabled=True, long_running=False, remove_migrate_tablefile=True
    )

    assert db.ewh_implemented_features


def test_setup_on_psql_long_running(conn_str: str, tempdir: str):
    config = Config.load(dict(migrate_uri=conn_str, db_folder=tempdir))

    db = migrate.setup_db(
        config=config, migrate=True, migrate_enabled=True, long_running=True, remove_migrate_tablefile=True
    )

    assert db.ewh_implemented_features


def psql_backup():
    path = Path(__file__).parent / "sqlite_empty" / "just_implemented_features.psql.sql"
    return str(path)


def test_postgres_backup(conn_str: str, tempdir: str):
    db = DAL(conn_str)

    with pytest.raises(psycopg2.errors.UndefinedTable):
        db.executesql("SELECT count(*) FROM ewh_implemented_features")
    db.rollback()

    config = Config.load(dict(migrate_uri=conn_str, db_folder=tempdir, database_to_restore=psql_backup()))
    recover_database_from_backup(set_schema="public")

    rows = db.executesql("SELECT count(*) FROM ewh_implemented_features")
    assert rows[0][0] == 0  # no rows, but table exists


def test_postgres_unavailable(conn_str: str, tempdir: str):
    config = Config.load(
        dict(
            migrate_uri=conn_str.replace(DB_NAME, "INVALID_DB_NAME"),
            db_folder=tempdir,
            database_to_restore=psql_backup(),
        )
    )
    with pytest.raises(ValueError):
        activate_migrations(config=config, max_time=5)
