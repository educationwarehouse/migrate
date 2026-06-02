import tempfile
import textwrap
from contextlib import chdir
from pathlib import Path

import pytest
from configuraptor import Singleton

from src.edwh_migrate import migrate
from src.edwh_migrate.migrate import Config, import_migrations, list_migrations


@pytest.fixture
def migrations_at_temp():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "migrations.py").write_text(
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

    config = Config.load({})
    # Avoid accidentally importing the repository-level migrations.py during pytest.
    config.migrations_file = "/fake/file"
    yield config

    # Also clean up after each test so failed imports don't leak into other test modules.
    migrate.migrations.reset()
    Singleton.clear()


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


def test_import_cross_module_dependency_ordering(empty_temp: str, empty_config: Config):
    tmp = Path(empty_temp)

    (tmp / "ordering_a.py").write_text(
        textwrap.dedent(
            """
            from src.edwh_migrate import migration

            @migration(requires=["ensure_sync_gid_defaults_use_uuidv7_20260423_001"])
            def drop_pg_uuidv7_extension_20260423_001(db): return True
            """
        )
    )

    (tmp / "ordering_b.py").write_text(
        textwrap.dedent(
            """
            import ordering_a
            from src.edwh_migrate import migration

            @migration()
            def ensure_sync_gid_defaults_use_uuidv7_20260423_001(db): return True
            """
        )
    )

    (tmp / "migrations.py").write_text("import ordering_b\n")

    with chdir(empty_temp):
        assert import_migrations([], empty_config)


def test_import_cross_module_dependency_cycle(empty_temp: str, empty_config: Config):
    tmp = Path(empty_temp)

    (tmp / "cycle_a.py").write_text(
        textwrap.dedent(
            """
            from src.edwh_migrate import migration

            @migration(requires=["migration_b_20260423_001"])
            def migration_a_20260423_001(db): return True
            """
        )
    )

    (tmp / "cycle_b.py").write_text(
        textwrap.dedent(
            """
            import cycle_a
            from src.edwh_migrate import migration

            @migration(requires=["migration_a_20260423_001"])
            def migration_b_20260423_001(db): return True
            """
        )
    )

    (tmp / "migrations.py").write_text("import cycle_b\n")

    with chdir(empty_temp):
        with pytest.raises(ValueError, match="circular dependency"):
            import_migrations([], empty_config)


def test_import_intertwined_suffix_ordering(empty_temp: str, empty_config: Config):
    tmp = Path(empty_temp)
    empty_config.migration_ordering_mode = "intertwined"

    (tmp / "core_intertwined.py").write_text(
        textwrap.dedent(
            """
            from src.edwh_migrate import migration

            @migration()
            def define_item_000(db): return True

            @migration()
            def define_tag_000(db): return True

            @migration()
            def old_style_without_suffix(db): return True

            @migration()
            def rename_item_002(db): return True
            
            @migration(requires=[define_item_000])
            def execute_me_early_004(db): return True
            """
        )
    )

    (tmp / "whitelabel_intertwined.py").write_text(
        textwrap.dedent(
            """
            from src.edwh_migrate import migration

            @migration()
            def update_tag_001(db): return True

            @migration()
            def update_tag_003(db): return True
            """
        )
    )

    (tmp / "migrations.py").write_text("import core_intertwined\nimport whitelabel_intertwined\n")

    with chdir(empty_temp):
        assert import_migrations([], empty_config)
        found = list_migrations(empty_config)
        assert list(found.keys()) == [
            "define_item_000",
            "execute_me_early_004",
            "define_tag_000",
            "old_style_without_suffix",
            "update_tag_001",
            "rename_item_002",
            "update_tag_003",
        ]


def test_import_legacy_ordering_keeps_definition_order(empty_temp: str, empty_config: Config):
    tmp = Path(empty_temp)
    empty_config.migration_ordering_mode = "legacy"

    (tmp / "core_legacy.py").write_text(
        textwrap.dedent(
            """
            from src.edwh_migrate import migration

            @migration()
            def define_item_000(db): return True

            @migration()
            def define_tag_000(db): return True

            @migration()
            def rename_item_002(db): return True
            
            @migration(requires=[define_item_000])
            def execute_me_early_004(db): return True
            """
        )
    )

    (tmp / "whitelabel_legacy.py").write_text(
        textwrap.dedent(
            """
            from src.edwh_migrate import migration

            @migration()
            def update_tag_001(db): return True

            @migration()
            def update_tag_003(db): return True
            """
        )
    )

    (tmp / "migrations.py").write_text("import core_legacy\nimport whitelabel_legacy\n")

    with chdir(empty_temp):
        assert import_migrations([], empty_config)
        found = list_migrations(empty_config)
        assert list(found.keys()) == [
            "define_item_000",
            "execute_me_early_004",
            "define_tag_000",
            "rename_item_002",
            "update_tag_001",
            "update_tag_003",
        ]
