import os
import pathlib

import pydal
import pytest
import shutil
import plumbum

from edwh_migrate import migrate


@pytest.fixture(scope='session')
def tmp_sqlite_folder(tmp_path_factory):
    return tmp_path_factory.mktemp('sqlite3.tmp')


@pytest.fixture(scope='session')
def sqlite_empty():
    return pathlib.Path(__file__).parent


@pytest.fixture
def tmp_sqlite_sql_file(tmp_sqlite_folder, sqlite_empty):
    dst = tmp_sqlite_folder / 'test.sql'
    shutil.copy(sqlite_empty / 'test.sql', dst)
    yield dst
    dst.unlink(missing_ok=True)


@pytest.fixture
def tmp_empty_sqlite_db_file(tmp_sqlite_folder, sqlite_empty):
    dst = tmp_sqlite_folder / 'empty_sqlite.db'
    shutil.copy(sqlite_empty / 'sqlite_empty' / 'empty_sqlite.db', dst)
    os.environ['MIGRATE_URI'] = f'sqlite://{str(dst)}'
    yield dst
    dst.unlink(missing_ok=True)
    del os.environ['MIGRATE_URI']


@pytest.fixture
def tmp_just_implemented_features_sqlite_db_file(tmp_sqlite_folder, sqlite_empty):
    dst = tmp_sqlite_folder / 'just_implemented_features.db'
    shutil.copy(sqlite_empty / 'sqlite_empty' / 'just_implemented_features.db', dst)
    os.environ['MIGRATE_URI'] = f'sqlite://{str(dst)}'
    yield dst
    dst.unlink(missing_ok=True)
    del os.environ['MIGRATE_URI']


@pytest.fixture
def clean_migrate():
    migrate.registered_functions = {}

def test_env_migrate_uri_is_missing():
    with pytest.raises(migrate.InvalidConfigException):
        migrate.setup_db()


def test_apply_empty_run_to_empty_sqlite(tmp_empty_sqlite_db_file):
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
    output = plumbum.local['sqlite3'][db._uri.split('://')[1]]['.dump']()
    if echo:
        print(output)
    return output


def test_always_true_dummy_is_migrated(tmp_just_implemented_features_sqlite_db_file):
    @migrate.migration
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
    assert rs.first().name == 'dummy', "the name of the row should be dummy"
    assert rs.first().installed is True, "the row should be marked as installed in the database"


def test_dummy_is_not_migrated_twice(tmp_just_implemented_features_sqlite_db_file, capsys):
    @migrate.migration
    def dummy(db):
        return True

    assert len(migrate.registered_functions) == 1, "exactly one function should be registerend"
    result = migrate.activate_migrations()
    assert result is True, "the dummy returning True should have been marked as successful"
    result = migrate.activate_migrations()
    assert 'already installed.' in capsys.readouterr().out, "the dummy returning True should have been marked as successful"
    db = migrate.setup_db()
    # dump_db(db, echo=True)
    assert db(db.ewh_implemented_features).count() == 1, "exactly one row should be in the table"
    rs = db(db.ewh_implemented_features).select()
    assert len(rs) == 1, "exactly one row should be in the table"
    assert rs.first().name == 'dummy', "the name of the row should be dummy"
    assert rs.first().installed is True, "the row should be marked as installed in the database"


@pytest.mark.parametrize("scenario", ['as_list', 'as_function'])
def test_dependencies(clean_migrate, tmp_just_implemented_features_sqlite_db_file, capsys, scenario):
    @migrate.migration
    def required(db):
        return True

    print(migrate.registered_functions)
    assert len(migrate.registered_functions) == 1
    result = migrate.activate_migrations()
    assert result is True, "the required migration returning True should have been marked as successful"

    @migrate.migration(requires=required if scenario == 'as_function' else [required])
    def dependent(db):
        return True


    assert len(migrate.registered_functions) == 2
    result = migrate.activate_migrations()
    assert result is True


    db = migrate.setup_db()
    assert result is True, "the dependent returning True should have been marked as successful"
    assert db(db.ewh_implemented_features.installed == True).count() == 2, "exactly two rows should be marked installed"


@pytest.mark.parametrize("scenario", ['as_list', 'as_function'])
def test_dependency_failure(clean_migrate, tmp_just_implemented_features_sqlite_db_file, capsys, scenario):
    @migrate.migration
    def required(db):
        return False

    @migrate.migration(requires=required if scenario == 'as_function' else [required])
    def dependent(db):
        return True

    assert len(migrate.registered_functions) == 2
    with pytest.raises(migrate.RequimentsNotMet):
        migrate.activate_migrations()
    db = migrate.setup_db()
    dump_db(db, echo=True)
    assert db(db.ewh_implemented_features.installed == True).count() == 0, "requirement failed, no succes possible"
    assert db(db.ewh_implemented_features.installed == False).count() == 1, "because of the exception, `dependent` is never written to the database. "

