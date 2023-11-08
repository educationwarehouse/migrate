import os
import pathlib
import shutil
from contextlib_chdir import chdir

import plumbum
import pydal
import pytest
from configuraptor import Singleton
from pydal import DAL

from src.edwh_migrate import migrate, recover_database_from_backup
from src.edwh_migrate.migrate import get_config, schema_versioned_lock_file, MigrateLockExists, MigrationFailed
from src.edwh_migrate.__about__ import __version__


def test_version():
    assert isinstance(__version__, str)
    assert __version__


@pytest.fixture(scope="session")
def tmp_sqlite_folder(tmp_path_factory):
    return tmp_path_factory.mktemp("sqlite3.tmp")


@pytest.fixture(scope="session")
def sqlite_empty():
    return pathlib.Path(__file__).parent


@pytest.fixture
def tmp_sqlite_sql_file(tmp_sqlite_folder, sqlite_empty):
    dst = tmp_sqlite_folder / "test.sql"
    shutil.copy(sqlite_empty / "test.sql", dst)
    yield dst
    dst.unlink(missing_ok=True)


@pytest.fixture
def tmp_empty_sqlite_db_file(tmp_sqlite_folder, sqlite_empty):
    dst = tmp_sqlite_folder / "empty_sqlite.db"
    shutil.copy(sqlite_empty / "sqlite_empty" / "empty_sqlite.db", dst)
    os.environ["MIGRATE_URI"] = f"sqlite://{str(dst)}"
    yield dst
    dst.unlink(missing_ok=True)
    del os.environ["MIGRATE_URI"]


@pytest.fixture
def tmp_just_implemented_features_sqlite_sql_file(tmp_sqlite_folder, sqlite_empty):
    return sqlite_empty / "sqlite_empty" / "just_implemented_features.sql"


@pytest.fixture
def tmp_just_implemented_features_sqlite_db_file(tmp_sqlite_folder, sqlite_empty):
    dst = tmp_sqlite_folder / "just_implemented_features.db"
    shutil.copy(sqlite_empty / "sqlite_empty" / "just_implemented_features.db", dst)
    os.environ["MIGRATE_URI"] = f"sqlite://{str(dst)}"
    yield dst
    dst.unlink(missing_ok=True)
    del os.environ["MIGRATE_URI"]


@pytest.fixture
def clean_migrate():
    migrate.registered_functions = {}
    Singleton.clear()  # clean cached Config


def test_env_migrate_uri_is_missing():
    with chdir("tests"):
        with pytest.raises(migrate.InvalidConfigException):
            migrate.setup_db()


def test_migrate_from_toml(clean_migrate):
    config = get_config()
    assert migrate.setup_db(migrate=True, migrate_enabled=True)

    assert config.migrate_uri == "sqlite:///tmp/migrate_example.sqlite"

    assert pathlib.Path("/tmp/migrate_example.sqlite").exists()


def test_setup_db_custom_pydal_class(clean_migrate):
    class DALish(DAL):
        ...

    db = migrate.setup_db(dal_class=DALish)

    assert isinstance(db, DALish)


def test_apply_empty_run_to_empty_sqlite(tmp_empty_sqlite_db_file, clean_migrate):
    with pytest.raises(migrate.DatabaseNotYetInitialized):
        migrate.setup_db()


def test_starts_without_registered_migrations():
    assert len(migrate.registered_functions) == 0, "No migrations should be registered"


def test_registration_works():
    @migrate.migration
    def dummy(db):
        return True

    assert len(migrate.registered_functions) == 1, "only one function should be registered"


def dump_db(db: pydal.DAL, *, echo=False):
    output = plumbum.local["sqlite3"][db._uri.split("://")[1]][".dump"]()
    if echo:
        print(output)
    return output


def test_always_true_dummy_is_migrated(tmp_just_implemented_features_sqlite_db_file):
    @migrate.migration()
    def dummy(db):
        return True

    assert len(migrate.registered_functions) == 1, "exactly one function should be registerend"
    result = migrate.activate_migrations()
    assert result is True, "the dummy returning True should have been marked as successful"
    db = migrate.setup_db()
    # dump_db(db, echo=True)
    assert db(db.ewh_implemented_features).count() == 1, "exactly one row should be in the table"
    rs = db(db.ewh_implemented_features).select()
    assert len(rs) == 1, "exactly one row should be in the table"
    assert rs.first().name == "dummy", "the name of the row should be dummy"
    assert rs.first().installed is True, "the row should be marked as installed in the database"


def test_dummy_is_not_migrated_twice(tmp_just_implemented_features_sqlite_db_file, capsys):
    @migrate.migration
    def dummy(db):
        return True

    assert len(migrate.registered_functions) == 1, "exactly one function should be registerend"
    result = migrate.activate_migrations()
    assert result is True, "the dummy returning True should have been marked as successful"
    result = migrate.activate_migrations()
    assert (
            "already installed." in capsys.readouterr().out
    ), "the dummy returning True should have been marked as successful"
    db = migrate.setup_db()
    # dump_db(db, echo=True)
    assert db(db.ewh_implemented_features).count() == 1, "exactly one row should be in the table"
    rs = db(db.ewh_implemented_features).select()
    assert len(rs) == 1, "exactly one row should be in the table"
    assert rs.first().name == "dummy", "the name of the row should be dummy"
    assert rs.first().installed is True, "the row should be marked as installed in the database"


@pytest.mark.parametrize("scenario", ["as_list", "as_function"])
def test_dependencies(clean_migrate, tmp_just_implemented_features_sqlite_db_file, capsys, scenario):
    @migrate.migration
    def required(db):
        return True

    print(migrate.registered_functions)
    assert len(migrate.registered_functions) == 1
    result = migrate.activate_migrations()
    assert result is True, "the required migration returning True should have been marked as successful"

    @migrate.migration(requires=required if scenario == "as_function" else [required])
    def dependent(db):
        return True

    assert len(migrate.registered_functions) == 2
    result = migrate.activate_migrations()
    assert result is True

    db = migrate.setup_db()
    assert result is True, "the dependent returning True should have been marked as successful"

    assert db(db.ewh_implemented_features.installed == True).count() == 2, "exactly two rows should be marked installed"


@pytest.mark.parametrize("scenario", ["as_list", "as_function"])
def test_dependency_failure(clean_migrate, tmp_just_implemented_features_sqlite_db_file, capsys, scenario):
    @migrate.migration
    def required(db):
        return False

    @migrate.migration(requires=required if scenario == "as_function" else [required])
    def dependent(db):
        return True

    assert len(migrate.registered_functions) == 2

    with pytest.raises(migrate.RequimentsNotMet):
        migrate.activate_migrations()

    db = migrate.setup_db()
    dump_db(db, echo=True)
    assert db(db.ewh_implemented_features.installed == True).count() == 0, "requirement failed, no succes possible"
    assert (
            db(db.ewh_implemented_features.installed == False).count() == 1
    ), "because of the exception, `dependent` is never written to the database. "


def test_recover_database_from_backup(tmp_just_implemented_features_sqlite_sql_file, tmp_empty_sqlite_db_file):
    config = get_config()

    with pytest.raises(migrate.DatabaseNotYetInitialized):
        migrate.setup_db(migrate=False)

    fake_path = pathlib.Path("/tmp/fake_file.xyz")
    fake_path.unlink(missing_ok=True)
    config.database_to_restore = str(fake_path)

    with pytest.raises(FileNotFoundError):
        recover_database_from_backup()

    fake_path.touch()
    with pytest.raises(NotImplementedError):
        # invalid extension
        recover_database_from_backup()

    config.database_to_restore = str(tmp_just_implemented_features_sqlite_sql_file)
    recover_database_from_backup()

    # no error anymore:
    assert migrate.setup_db(migrate=False)


def test_config():
    config = get_config()
    assert config is get_config()  # singleton

    assert config.database_to_restore == get_config("database_to_restore")

    assert "<Config{" in repr(config)

def test_schema_versioned_lock_file(capsys):
    config = get_config()
    flag_dir = pathlib.Path("/tmp/test_flag_dir")
    if flag_dir.exists():
        [_.unlink() for _ in flag_dir.glob("*")]
        flag_dir.rmdir()

    with pytest.raises(NotADirectoryError):
        with schema_versioned_lock_file() as lock:
            pass

    config.schema_version = None

    with schema_versioned_lock_file(flag_location=flag_dir, create_flag_location=True) as lock:
        assert lock is None

    config.schema_version = "1"

    with schema_versioned_lock_file(flag_location=flag_dir, create_flag_location=True) as lock:
        assert lock

    with pytest.raises(MigrateLockExists):
        with schema_versioned_lock_file(flag_location=flag_dir, create_flag_location=False) as lock:
            pass

    config.schema_version = "2"

    with schema_versioned_lock_file(flag_location=flag_dir, create_flag_location=False) as lock:
        raise MigrationFailed()

    captured = capsys.readouterr()

    assert "removing the lock file" in captured.out

    with pytest.raises(Exception):
        with schema_versioned_lock_file(flag_location=flag_dir, create_flag_location=False) as lock:
            raise Exception()

    captured = capsys.readouterr()

    assert "removing the lock file" not in captured.out
