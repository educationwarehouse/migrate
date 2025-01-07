from sqlite3 import OperationalError

import pytest

from src.edwh_migrate import ViewMigrationManager, setup_db

from .fixtures import clean_migrate


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


def test_resolving_manager_order(clean_migrate):
    db = setup_db(migrate=True, migrate_enabled=True)

    # one should be fine:
    with MyChildView2(db):
        ...

    with MyBaseView(db):
        ...

    # multiple without combine may crash:
    with pytest.raises(OperationalError):
        with MyChildView2(db), MyBaseView(db), MyChildView1(db):
            ...
