import os
import pathlib

import plumbum
import pydal
import pytest
from contextlib_chdir import chdir
from pydal import DAL

from src.edwh_migrate import migrate, recover_database_from_backup
from src.edwh_migrate.__about__ import __version__
from src.edwh_migrate.migrate import (
    MigrateLockExists,
    MigrationFailed,
    get_config,
    print_migrations_status_table,
    schema_versioned_lock_file,
)

from .fixtures import (  # noqa
    clean_migrate,
    fixture_temp_chdir,
    sqlite_empty,
    tmp_empty_sqlite_db_file,
    tmp_just_implemented_features_sqlite_db_file,
    tmp_just_implemented_features_sqlite_sql_file,
    tmp_sqlite_folder,
    tmp_sqlite_sql_file,
)


def test_version():
    assert isinstance(__version__, str)
    assert __version__


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
    class DALish(DAL): ...

    db = migrate.setup_db(dal_class=DALish)

    assert isinstance(db, DALish)


def test_apply_empty_run_to_empty_sqlite(tmp_empty_sqlite_db_file, clean_migrate):
    with pytest.raises(migrate.DatabaseNotYetInitialized):
        migrate.setup_db()


def test_starts_without_registered_migrations(clean_migrate):
    assert len(migrate.migrations) == 0, "No migrations should be registered"


def test_registration_works(clean_migrate):
    @migrate.migration
    def dummy(db):
        return True

    assert len(migrate.migrations) == 1, "only one function should be registered"


def dump_db(db: pydal.DAL, *, echo=False):
    output = plumbum.local["sqlite3"][db._uri.split("://")[1]][".dump"]()
    if echo:
        print(output)
    return output


def test_always_true_dummy_is_migrated(clean_migrate, tmp_just_implemented_features_sqlite_db_file):
    @migrate.migration()
    def dummy(db):
        return True

    assert len(migrate.migrations) == 1, "exactly one function should be registerend"
    result = migrate.activate_migrations()
    assert result is True, "the dummy returning True should have been marked as successful"
    db = migrate.setup_db()
    # dump_db(db, echo=True)
    assert db(db.ewh_implemented_features).count() == 1, "exactly one row should be in the table"
    rs = db(db.ewh_implemented_features).select()
    assert len(rs) == 1, "exactly one row should be in the table"
    assert rs.first().name == "dummy", "the name of the row should be dummy"
    assert rs.first().installed is True, "the row should be marked as installed in the database"


def test_dummy_is_not_migrated_twice(clean_migrate, tmp_just_implemented_features_sqlite_db_file, capsys):
    @migrate.migration
    def dummy(db):
        return True

    assert len(migrate.migrations) == 1, "exactly one function should be registerend"
    result = migrate.activate_migrations()
    assert result is True, "the dummy returning True should have been marked as successful"
    result = migrate.activate_migrations()
    assert "already installed." in capsys.readouterr().out, (
        "the dummy returning True should have been marked as successful"
    )
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

    assert len(migrate.migrations) == 1
    result = migrate.activate_migrations()
    assert result is True, "the required migration returning True should have been marked as successful"

    @migrate.migration(requires=required if scenario == "as_function" else [required])
    def dependent(db):
        return True

    assert len(migrate.migrations) == 2
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

    assert len(migrate.migrations) == 2

    with pytest.raises(migrate.RequimentsNotMet):
        migrate.activate_migrations()

    db = migrate.setup_db()
    dump_db(db, echo=True)
    assert db(db.ewh_implemented_features.installed == True).count() == 0, "requirement failed, no succes possible"
    assert db(db.ewh_implemented_features.installed == False).count() == 1, (
        "because of the exception, `dependent` is never written to the database. "
    )


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
    with pytest.raises(FileNotFoundError):
        # even if the file doesn't exist but has invalid extension, not found error is raised.
        recover_database_from_backup()

    config.database_to_restore = str(tmp_just_implemented_features_sqlite_sql_file)
    recover_database_from_backup(config=config)  # sqlite:///tmp/.../empty_sqlite.db

    # no error anymore:
    assert migrate.setup_db(migrate=False)


def test_recover_database_from_backup_relative(tmp_just_implemented_features_sqlite_sql_file, tmp_empty_sqlite_db_file):
    config = get_config()

    filepath = pathlib.Path(config.migrate_uri.split("://")[-1])
    with chdir(filepath.parent):
        config.migrate_uri = f"sqlite://{filepath.name}"  # sqlite://empty_sqlite.db
        config.database_to_restore = str(tmp_just_implemented_features_sqlite_sql_file)
        recover_database_from_backup(config=config)

        assert migrate.setup_db(migrate=False)


def test_config():
    config = get_config()
    assert config is get_config()  # singleton

    assert config.database_to_restore is get_config().database_to_restore

    assert "<Config{" in repr(config)


def test_schema_versioned_lock_file(capsys, clean_migrate):
    config = get_config()

    config.flag_location = "/tmp/test_flag_dir"

    flag_dir = pathlib.Path(config.flag_location)
    if flag_dir.exists():
        [_.unlink() for _ in flag_dir.glob("*")]
        flag_dir.rmdir()

    config.create_flag_location = False
    with pytest.raises(NotADirectoryError):
        with schema_versioned_lock_file(config=config) as lock:
            assert not lock

    config.schema_version = None

    with schema_versioned_lock_file(config=config, flag_location=flag_dir, create_flag_location=True) as lock:
        assert config.schema_version is None, "Schema version should be none"
        assert lock is None, "expected no lock due to empty schema version"

    config.schema_version = "1"

    with schema_versioned_lock_file(config=config, flag_location=flag_dir, create_flag_location=True) as lock:
        assert lock

    with pytest.raises(MigrateLockExists):
        with schema_versioned_lock_file(config=config, flag_location=flag_dir, create_flag_location=False) as lock:
            pass

    # config.schema_version = "2"
    os.environ["SCHEMA-VERSION"] = "2"
    config.update_from_env()

    assert config.schema_version == "2"

    with schema_versioned_lock_file(config=config, flag_location=flag_dir, create_flag_location=False) as lock:
        raise MigrationFailed()

    captured = capsys.readouterr()

    assert "removing the lock file" in captured.out

    with pytest.raises(Exception):
        with schema_versioned_lock_file(config=config, flag_location=flag_dir, create_flag_location=False) as lock:
            raise Exception()

    captured = capsys.readouterr()

    assert "removing the lock file" not in captured.out


def test_without_migrate_uri_but_with_db_uri_and_folder(fixture_temp_chdir, clean_migrate):
    os.environ["DB_URI"] = "sqlite://storage.sqlite"

    db_folder = fixture_temp_chdir / "database"
    db_folder.mkdir()

    os.environ["DB_FOLDER"] = str(db_folder)

    try:
        migrate.setup_db(migrate_enabled=True, migrate=True)

        assert db_folder.exists()

        assert plumbum.local["ls"](os.getcwd()).strip() == "database"

        db_ls = plumbum.local["ls"](db_folder)

        assert "ewh_implemented_features.table" in db_ls
        assert "sql.log" in db_ls
        assert "storage.sqlite" in db_ls
    finally:
        del os.environ["DB_URI"]
        del os.environ["DB_FOLDER"]


def test_migration_failure_traceback(tmp_empty_sqlite_db_file, clean_migrate, capsys):
    config = migrate.get_config()

    @migrate.migration()
    def fails_horribly(db):
        0 / 0

    assert migrate.activate_migrations(config) is False
    captured = capsys.readouterr()
    assert "failed" in captured.out
    assert "ZeroDivisionError" in captured.err

    print_migrations_status_table(config)
    captured = capsys.readouterr()
    stdout = captured.out
    assert "fails_horribly" in stdout
    assert "missing" in stdout
    assert "function test_migration_failure_traceback.<locals>.fails" not in stdout
