from sqlite3 import OperationalError

import pytest
from pydal import DAL

from src.edwh_migrate import (
    ViewMigrationManager,
    migrate,
)

from .fixtures import clean_migrate, sqlite_empty, tmp_empty_sqlite_db_file, tmp_sqlite_folder  # noqa


class StandaloneView(ViewMigrationManager):
    since = "first_migration"
    until = "third_migration"  # doesn't exist

    def up(self): ...

    def down(self): ...


class Ignored(ViewMigrationManager):
    since = "second_migration"  # doesn't exist

    def up(self):
        2 / 0

    def down(self):
        1 / 0


class MyBaseView(ViewMigrationManager):
    uses = ()

    def up(self) -> None:
        self.db.executesql("""
            CREATE VIEW base_view AS
            SELECT Rowid AS id
            ;
        """)

    def down(self) -> None:
        self.db.executesql("""
            DROP VIEW IF EXISTS base_view;
        """)


class MyChildView1(ViewMigrationManager):
    uses = (MyBaseView,)

    def up(self) -> None:
        self.db.executesql("""
            CREATE VIEW my_child_view_1 AS
            SELECT id FROM base_view
            ;
        """)

    def down(self) -> None:
        self.db.executesql("""
            DROP VIEW IF EXISTS my_child_view_1;
        """)


class MyChildView2(ViewMigrationManager):
    uses = (MyBaseView, MyChildView1)

    def up(self) -> None:
        self.db.executesql("""
            CREATE VIEW my_child_view_2 AS
            SELECT id FROM my_child_view_1
            ;
        """)

    def down(self) -> None:
        self.db.executesql("""
            DROP VIEW IF EXISTS my_child_view_2;
        """)


def test_resolving_manager_order(tmp_empty_sqlite_db_file, clean_migrate):
    @migrate.migration()
    def first_migration(db):
        with StandaloneView(db), Ignored(db):
            ...

        return True

    config = migrate.get_config()

    assert len(migrate.migrations) == 1
    assert migrate.activate_migrations(config=config)

    db = migrate.setup_db(config=config)

    assert db(db.ewh_implemented_features).count()

    # one should be fine:
    with MyChildView2(db):
        ...

    with MyBaseView(db):
        ...

    # multiple without combine may crash:
    with pytest.raises(OperationalError):
        with MyChildView2(db), MyBaseView(db), MyChildView1(db):
            ...


def test_circular_dependencies_fail_before_dropping_views():
    operations = []

    class FirstView(ViewMigrationManager):
        uses: tuple[type[ViewMigrationManager], ...] = ()

        def up(self):
            operations.append("first up")

        def down(self):
            operations.append("first down")

    class SecondView(ViewMigrationManager):
        uses = (FirstView,)

        def up(self):
            operations.append("second up")

        def down(self):
            operations.append("second down")

    class OldLeaf(ViewMigrationManager):
        uses = (SecondView,)

        def up(self): ...

        def down(self): ...

    class NewLeaf(ViewMigrationManager):
        uses = (SecondView,)
        replaces = OldLeaf

        def up(self): ...

        def down(self): ...

    # Close the cycle after both classes exist, registering the reverse dependency.
    FirstView.uses = (SecondView,)
    SecondView._used_by.append(FirstView)

    db = DAL("sqlite:memory")
    try:
        with pytest.raises(ValueError, match="Circular view migration dependencies"), FirstView(db):
            operations.append("migration body")
        assert operations == []
    finally:
        db.close()


def test_without_replacements_preserves_recursive_lifecycle_hooks():
    operations = []

    class Root(ViewMigrationManager):
        uses = ()

        def up(self):
            operations.append("root up")

        def down(self):
            operations.append("root down")

    class Middle(ViewMigrationManager):
        uses = (Root,)

        def up(self):
            operations.append("middle up")

        def down(self):
            operations.append("middle down")

        def __enter__(self):
            operations.append("middle enter")
            return super().__enter__()

        def __exit__(self, exc_type, exc_value, tb):
            operations.append("middle exit")
            return super().__exit__(exc_type, exc_value, tb)

    class Leaf(ViewMigrationManager):
        uses = (Root, Middle)

        def up(self):
            operations.append("leaf up")

        def down(self):
            operations.append("leaf down")

        def __enter__(self):
            operations.append("leaf enter")
            return super().__enter__()

        def __exit__(self, exc_type, exc_value, tb):
            operations.append("leaf exit")
            return super().__exit__(exc_type, exc_value, tb)

    db = DAL("sqlite:memory")
    try:
        with Root(db):
            operations.append("migration body")
        assert operations == [
            "leaf enter",
            "leaf down",
            "middle enter",
            "leaf enter",
            "leaf down",
            "middle down",
            "root down",
            "migration body",
            "root up",
            "middle exit",
            "middle up",
            "leaf exit",
            "leaf up",
            "leaf exit",
        ]
    finally:
        db.close()
