import os
import tempfile
import textwrap
from contextlib import chdir

import pytest
from configuraptor import Singleton

from src.edwh_migrate import migrate
from src.edwh_migrate.migrate import Config, import_migrations, list_migrations


@pytest.fixture
def migrations_at_temp():
    with tempfile.TemporaryDirectory() as d:
        fname = f"{d}/migrations.py"
        with open(fname, "w") as f:
            f.write(
                textwrap.dedent(
                    """
            from src.edwh_migrate import migration
            
            @migration()
            def test(db): return True

            """
                )
            )
        yield d


@pytest.fixture()
def empty_temp():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture()
def empty_config():
    migrate.migrations.reset()
    Singleton.clear()

    return Config.load({})


def test_list(migrations_at_temp: str, empty_config: Config):
    with chdir(migrations_at_temp):
        found = list_migrations(empty_config)
        assert list(found.keys()) == ["test"]


def test_args(migrations_at_temp: str, empty_config: Config):
    assert import_migrations([migrations_at_temp], empty_config)
    migrate.migrations.reset()

    assert import_migrations([f"{migrations_at_temp}/migrations.py"], empty_config)
    migrate.migrations.reset()

    assert not import_migrations([f"{migrations_at_temp}/no_migrations.py"], empty_config)
    migrate.migrations.reset()

    assert not import_migrations([f"/no_tmp"], empty_config)
    migrate.migrations.reset()


def test_config(migrations_at_temp: str, empty_config: Config):
    empty_config.migrations_file = f"{migrations_at_temp}/migrations.py"
    assert import_migrations([], empty_config)


def test_fail(migrations_at_temp: str, empty_temp: str, empty_config: Config):
    with chdir(empty_temp):
        assert not import_migrations([], empty_config)


def test_local(migrations_at_temp: str, empty_config: Config):
    empty_config.migrations_file = "/fake/file"
    with chdir(migrations_at_temp):
        assert import_migrations([], empty_config)
