import os

import pytest
from typedal import TypeDAL

from src.edwh_migrate import activate_migrations, setup_db

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


@pytest.fixture
def env_use_typedal():
    os.environ["USE_TYPEDAL"] = "1"
    yield
    del os.environ["USE_TYPEDAL"]


@pytest.fixture
def tmp_typedal_env(fixture_temp_chdir):
    os.environ["DB_URI"] = f"sqlite://{fixture_temp_chdir / 'some.sqlite'}"
    os.environ["FOLDER"] = str(fixture_temp_chdir / "database")
    yield
    del os.environ["DB_URI"]
    del os.environ["FOLDER"]


def test_setup_db(tmp_just_implemented_features_sqlite_db_file, clean_migrate):
    db = setup_db(dal_class=TypeDAL)

    assert isinstance(db, TypeDAL)


def test_setup_empty(tmp_typedal_env, clean_migrate):
    db = setup_db(dal_class=TypeDAL, migrate=True, migrate_enabled=True)

    assert isinstance(db, TypeDAL)


def test_activate_migrations(env_use_typedal, tmp_typedal_env, clean_migrate):
    assert activate_migrations()
