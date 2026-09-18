import shutil
import tempfile
from pathlib import Path

import pytest
from configuraptor import Singleton
from pydal import DAL
from testcontainers.postgres import PostgresContainer

from edwh_migrate import migration
from src.edwh_migrate import (
    Config,
    activate_migrations,
    migrate,
    recover_database_from_backup,
)
from src.edwh_migrate.postgres import PostgresUndefinedTable


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
    from sqlalchemy import create_engine, text
    from sqlalchemy_utils.functions import create_database, drop_database

    uri = postgres.get_connection_url()

    # kill leftover connections from previous test
    engine = create_engine(uri, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(
            text("""
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid <> pg_backend_pid()
            """)
        )
    engine.dispose()

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
    db.close()


def test_setup_on_psql_long_running(conn_str: str, tempdir: str):
    config = Config.load(dict(migrate_uri=conn_str, db_folder=tempdir))

    db = migrate.setup_db(
        config=config, migrate=True, migrate_enabled=True, long_running=True, remove_migrate_tablefile=True
    )

    assert db.ewh_implemented_features
    db.close()


def psql_backup():
    path = Path(__file__).parent / "sqlite_empty" / "just_implemented_features.psql.sql"
    return str(path)


@pytest.fixture()
def psql_in_container():
    return migrate.plumbum.local["docker"]["exec", "-i", postgres.get_wrapped_container().id, "psql"]


def test_postgres_backup(conn_str: str, tempdir: str, psql_in_container):
    db = DAL(conn_str)

    with pytest.raises(PostgresUndefinedTable):
        db.executesql("SELECT count(*) FROM ewh_implemented_features")
    db.rollback()

    container_uri = f"postgres://{postgres.username}:{postgres.password}@127.0.0.1:5432/{DB_NAME}"
    config = Config.load(dict(migrate_uri=container_uri, db_folder=tempdir, database_to_restore=psql_backup()))
    recover_database_from_backup(config=config, set_schema="public", postgres_client=psql_in_container)

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


def test_very_long_migration_name_notice(conn_str: str, tempdir: str, capfd):
    # capfd is like capsys but also works for c-libraries like postgres
    config = Config.load(
        dict(
            migrate_uri=conn_str,
            db_folder=tempdir,
        )
    )

    @migration()
    def veryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryverylong(
        db,
    ):
        print("ok")

    activate_migrations(config=config, max_time=5)
    captured = capfd.readouterr()

    assert "NOTICE:" not in captured.err
