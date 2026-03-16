from sqlite3 import OperationalError

import pytest

from src.edwh_migrate import (
    ViewMigrationManager,
    migrate,
)

from .fixtures import (  # noqa
    clean_migrate,
    sqlite_empty,
    tmp_empty_sqlite_db_file,
    tmp_just_implemented_features_sqlite_db_file,
    tmp_sqlite_folder,
)


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


class UntilCurrentMigrationView(ViewMigrationManager):
    until = "drop_legacy_view"
    calls: list[str] = []

    def up(self) -> None:
        self.calls.append("up")

    def down(self) -> None:
        self.calls.append("down")


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


def test_until_current_migration_runs_down_but_not_up(tmp_just_implemented_features_sqlite_db_file, clean_migrate):
    UntilCurrentMigrationView.calls = []

    @migrate.migration()
    def drop_legacy_view(db):
        with UntilCurrentMigrationView(db):
            ...

        return True

    assert migrate.activate_migrations()
    assert UntilCurrentMigrationView.calls == ["down"]
