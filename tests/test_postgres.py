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
    ViewMigrationManager,
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


def report_model_managers():
    class Models(ViewMigrationManager):
        uses = ()

        def up(self): ...

        def down(self): ...

    def model_manager(table_name):
        class Model(ViewMigrationManager):
            uses = (Models,)

            def up(self):
                if self.db.executesql(f"SELECT to_regclass('{table_name}_backup')") == [(None,)]:
                    return
                self.db.executesql(f"CREATE TABLE {table_name} (id integer PRIMARY KEY)")
                self.db.executesql(f"INSERT INTO {table_name} SELECT * FROM {table_name}_backup")
                self.db.executesql(f"DROP TABLE {table_name}_backup")

            def down(self):
                if self.db.executesql(f"SELECT to_regclass('{table_name}')") == [(None,)]:
                    return
                self.db.executesql(f"CREATE TEMP TABLE {table_name}_backup AS SELECT * FROM {table_name}")
                self.db.executesql(f"DROP TABLE {table_name}")

        return Model

    return Models, model_manager("item_model"), model_manager("experience_model"), model_manager("tag_model")


def setup_report_models(config):
    db = migrate.setup_db(config=config, migrate=True, migrate_enabled=True)
    db.executesql("CREATE TABLE item_model (id integer PRIMARY KEY)")
    db.executesql("INSERT INTO item_model VALUES (1)")
    db.executesql("CREATE TABLE tag_model (id integer PRIMARY KEY)")
    db.executesql("INSERT INTO tag_model VALUES (10)")
    db.commit()
    return db


@pytest.fixture
def report_migrations():
    migrate.migrations.reset()
    yield
    migrate.migrations.reset()


@pytest.mark.usefixtures("report_migrations")
def test_report_replacement_on_fresh_database(conn_str: str, tempdir: str):
    config = Config.load(dict(migrate_uri=conn_str, db_folder=tempdir))
    db = setup_report_models(config)
    Models, ItemModel, _, TagModel = report_model_managers()
    rebuilt = []
    hooks = []

    class ReportV1(ViewMigrationManager):
        uses = (ItemModel, TagModel)
        since = "activate_item_report"

        def up(self):
            rebuilt.append("old")
            self.db.executesql("""
                CREATE MATERIALIZED VIEW item_report AS
                SELECT item.id, tag.id AS tag_id, 'old'::text AS version
                FROM item_model item
                CROSS JOIN tag_model tag
            """)

        def down(self):
            self.db.executesql("DROP MATERIALIZED VIEW IF EXISTS item_report")

    class ReportV2(ViewMigrationManager):
        uses = (ItemModel, TagModel)
        replaces = ReportV1
        since = "activate_item_report"

        def up(self):
            rebuilt.append("new")
            self.db.executesql("""
                CREATE MATERIALIZED VIEW item_report AS
                SELECT item.id, tag.id AS tag_id, 'new'::text AS version
                FROM item_model item
                CROSS JOIN tag_model tag
            """)

        def down(self):
            self.db.executesql("DROP MATERIALIZED VIEW IF EXISTS item_report")

    assert ReportV1 in ItemModel._used_by and ReportV2 in ItemModel._used_by
    assert ReportV1 in TagModel._used_by and ReportV2 in TagModel._used_by

    class Consumer(ViewMigrationManager):
        uses = (ReportV1,)
        since = "activate_item_report"

        def up(self):
            self.db.executesql("CREATE VIEW item_consumer AS SELECT * FROM item_report")
            rebuilt.append("consumer")

        def down(self):
            self.db.executesql("DROP VIEW IF EXISTS item_consumer")

        def __enter__(self):
            hooks.append("enter")
            return super().__enter__()

        def __exit__(self, exc_type, exc_value, tb):
            hooks.append("exit")
            return super().__exit__(exc_type, exc_value, tb)

    @migrate.migration()
    def activate_item_report(db):
        with ItemModel(db):
            assert db.executesql("SELECT to_regclass('item_report')") == [(None,)]
        return True

    assert migrate.activate_migrations(config=config)
    assert db.executesql("SELECT * FROM item_report") == [(1, 10, "new")]
    assert db.executesql("SELECT * FROM item_consumer") == [(1, 10, "new")]
    assert rebuilt == ["new", "consumer"]
    assert hooks == ["enter", "exit"]
    db.commit()

    @migrate.migration()
    def rebuild_item_and_tag(db):
        with Models(db):
            assert db.executesql("SELECT to_regclass('item_report')") == [(None,)]
            assert db.executesql("SELECT to_regclass('item_model'), to_regclass('tag_model')") == [(None, None)]
        return True

    assert migrate.activate_migrations(config=config)
    assert db.executesql("SELECT * FROM item_report") == [(1, 10, "new")]
    assert db.executesql("SELECT * FROM item_consumer") == [(1, 10, "new")]
    assert rebuilt == ["new", "consumer", "new", "consumer"]
    assert hooks == ["enter", "exit", "enter", "exit"]
    db.close()


@pytest.mark.usefixtures("report_migrations")
def test_report_replacement_during_model_rename(conn_str: str, tempdir: str):
    config = Config.load(dict(migrate_uri=conn_str, db_folder=tempdir))
    db = setup_report_models(config)
    Models, ItemModel, ExperienceModel, TagModel = report_model_managers()
    rebuilt = []
    hooks = []

    class ReportV1(ViewMigrationManager):
        uses = (ItemModel, TagModel)
        since = "activate_item_report"
        until = "rename_item_to_experience"

        def up(self):
            rebuilt.append("old")
            self.db.executesql("""
                CREATE MATERIALIZED VIEW item_report AS
                SELECT item.id, tag.id AS tag_id
                FROM item_model item
                CROSS JOIN tag_model tag
            """)

        def down(self):
            self.db.executesql("DROP MATERIALIZED VIEW IF EXISTS item_report")

    class ReportV2(ViewMigrationManager):
        uses = (ExperienceModel, TagModel)
        replaces = ReportV1
        since = "rename_item_to_experience"

        def up(self):
            rebuilt.append("new")
            self.db.executesql("""
                CREATE MATERIALIZED VIEW item_report AS
                SELECT experience.id, tag.id AS tag_id
                FROM experience_model experience
                CROSS JOIN tag_model tag
            """)

        def down(self):
            self.db.executesql("DROP MATERIALIZED VIEW IF EXISTS item_report")

    class Consumer(ViewMigrationManager):
        uses = (ReportV1,)
        since = "activate_item_report"

        def up(self):
            self.db.executesql("CREATE VIEW item_consumer AS SELECT * FROM item_report")
            rebuilt.append("consumer")

        def down(self):
            self.db.executesql("DROP VIEW IF EXISTS item_consumer")

        def __enter__(self):
            hooks.append("enter")
            return super().__enter__()

        def __exit__(self, exc_type, exc_value, tb):
            hooks.append("exit")
            return super().__exit__(exc_type, exc_value, tb)

    ReportV1(db).up()
    Consumer(db).up()
    rebuilt.clear()
    db.ewh_implemented_features.insert(name="activate_item_report", installed=True)
    db.commit()

    @migrate.migration()
    def rename_item_to_experience(db):
        with ExperienceModel(db):
            assert db.executesql("SELECT to_regclass('item_report')") == [(None,)]
            db.executesql("ALTER TABLE item_model RENAME TO experience_model")
        return True

    assert migrate.activate_migrations(config=config)
    assert db.executesql("SELECT to_regclass('item_model')") == [(None,)]
    assert db.executesql("SELECT * FROM item_report") == [(1, 10)]
    assert db.executesql("SELECT * FROM item_consumer") == [(1, 10)]
    assert rebuilt == ["new", "consumer"]
    assert hooks == ["enter", "exit"]
    dependencies = db.executesql("""
        SELECT DISTINCT source.relname
        FROM pg_rewrite rewrite
        JOIN pg_depend dependency ON dependency.objid = rewrite.oid
            AND dependency.classid = 'pg_rewrite'::regclass
            AND dependency.refclassid = 'pg_class'::regclass
        JOIN pg_class source ON source.oid = dependency.refobjid
        WHERE rewrite.ev_class = 'item_report'::regclass AND source.relkind = 'r'
    """)
    assert {row[0] for row in dependencies} == {"experience_model", "tag_model"}
    db.commit()

    @migrate.migration()
    def rebuild_experience_and_tag(db):
        with Models(db):
            assert db.executesql("SELECT to_regclass('item_report')") == [(None,)]
            assert db.executesql("SELECT to_regclass('experience_model'), to_regclass('tag_model')") == [(None, None)]
        return True

    assert migrate.activate_migrations(config=config)
    assert db.executesql("SELECT * FROM item_report") == [(1, 10)]
    assert db.executesql("SELECT * FROM item_consumer") == [(1, 10)]
    assert rebuilt == ["new", "consumer", "new", "consumer"]
    assert hooks == ["enter", "exit", "enter", "exit"]
    assert ReportV1.until == "rename_item_to_experience"
    db.close()
