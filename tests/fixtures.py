import os
import shutil
import tempfile
from contextlib import chdir
from pathlib import Path

import pytest
from configuraptor.singleton import Singleton

from src.edwh_migrate import migrate


@pytest.fixture
def clean_migrate():
    migrate.registered_functions = {}
    Singleton.clear()  # clean cached Config


@pytest.fixture(scope="session")
def tmp_sqlite_folder(tmp_path_factory):
    return tmp_path_factory.mktemp("sqlite3.tmp")


@pytest.fixture(scope="session")
def sqlite_empty():
    return Path(__file__).parent


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


@pytest.fixture()
def fixture_temp_chdir():
    with tempfile.TemporaryDirectory() as _dir:
        cwd = Path(_dir)
        with chdir(cwd):
            yield cwd
