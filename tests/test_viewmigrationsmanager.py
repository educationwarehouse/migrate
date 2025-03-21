import os
from sqlite3 import OperationalError

import pytest

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
